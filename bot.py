from __future__ import annotations

import os
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import openai
import requests
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram import InputFile
from urllib.parse import quote
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
XAI_TOKEN = os.getenv("XAI_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Проверка токенов
if not all([TELEGRAM_TOKEN, YANDEX_TOKEN, XAI_TOKEN, DATABASE_URL]):
    logger.error("Токены или DATABASE_URL не найдены в .env файле!")
    raise ValueError("Укажите TELEGRAM_TOKEN, YANDEX_TOKEN, XAI_TOKEN, DATABASE_URL в .env")

# Инициализация клиента OpenAI
client = OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=XAI_TOKEN,
)

# Flask app для webhook
flask_app = Flask(__name__)

# Словарь федеральных округов
FEDERAL_DISTRICTS = {
    "Центральный федеральный округ": [
        "Белгородская область", "Брянская область", "Владимирская область", "Воронежская область",
        "Ивановская область", "Калужская область", "Костромская область", "Курская область",
        "Липецкая область", "Московская область", "Орловская область", "Рязанская область",
        "Смоленская область", "Тамбовская область", "Тверская область", "Тульская область",
        "Ярославская область", "Москва"
    ],
    "Северо-Западный федеральный округ": [
        "Республика Карелия", "Республика Коми", "Архангельская область", "Вологодская область",
        "Ленинградская область", "Мурманская область", "Новгородская область", "Псковская область",
        "Калининградская область", "Ненецкий автономный округ", "Санкт-Петербург"
    ],
    "Южный федеральный округ": [
        "Республика Адыгея", "Республика Калмыкия", "Республика Крым", "Краснодарский край",
        "Астраханская область", "Волгоградская область", "Ростовская область", "Севастополь"
    ],
    "Северо-Кавказский федеральный округ": [
        "Республика Дагестан", "Республика Ингушетия", "Кабардино-Балкарская Республика",
        "Карачаево-Черкесская Республика", "Республика Северная Осетия — Алания",
        "Чеченская Республика", "Ставропольский край"
    ],
    "Приволжский федеральный округ": [
        "Республика Башкортостан", "Республика Марий Эл", "Республика Мордовия", "Республика Татарстан",
        "Удмуртская Республика", "Чувашская Республика", "Кировская область", "Нижегородская область",
        "Оренбургская область", "Пензенская область", "Пермский край", "Самарская область",
        "Саратовская область", "Ульяновская область"
    ],
    "Уральский федеральный округ": [
        "Курганская область", "Свердловская область", "Тюменская область", "Ханты-Мансийский автономный округ — Югра",
        "Челябинская область", "Ямало-Ненецкий автономный округ"
    ],
    "Сибирский федеральный округ": [
        "Республика Алтай", "Республика Тыва", "Республика Хакасия", "Алтайский край",
        "Красноярский край", "Иркутская область", "Кемеровская область", "Новосибирская область",
        "Омская область", "Томская область", "Забайкальский край"
    ],
    "Дальневосточный федеральный округ": [
        "Республика Саха (Якутия)", "Приморский край", "Хабаровский край", "Амурская область",
        "Камчатский край", "Магаданская область", "Сахалинская область", "Еврейская автономная область",
        "Чукотский автономный округ"
    ]
}

# Функции для работы с PostgreSQL
def get_db_connection():
    """Получает соединение с БД."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL не установлен!")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("Успешное соединение с PostgreSQL.")
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к базе данных: {str(e)}")
        raise

def init_db():
    """Инициализирует таблицы в БД."""
    try:
        conn = get_db_connection()
        logger.info("Соединение с базой данных установлено.")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_admins (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE NOT NULL
            );
        """)
        logger.info("Таблица allowed_admins создана или уже существует.")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE NOT NULL
            );
        """)
        logger.info("Таблица allowed_users создана или уже существует.")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                fio TEXT,
                name TEXT,
                region TEXT
            );
        """)
        logger.info("Таблица user_profiles создана или уже существует.")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                request_text TEXT,
                response_text TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        logger.info("Таблица user_requests создана или уже существует.")
        # Инициализируем с дефолтным админом (замените на свой ID)
        default_admin = 123456789  # Замените на ваш Telegram user_id
        cur.execute("INSERT INTO allowed_admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING;", (default_admin,))
        logger.info(f"Добавлен дефолтный админ с user_id {default_admin}.")
        conn.commit()
        cur.close()
        conn.close()
        logger.info("База данных успешно инициализирована.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {str(e)}")
        raise

# Функция логирования запросов
def log_request(user_id: int, request_text: str, response_text: str) -> None:
    """Сохраняет запрос и ответ в таблицу user_requests."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_requests (user_id, request_text, response_text, timestamp)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP);
        """, (user_id, request_text, response_text))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Логирован запрос user_id {user_id}: {request_text} -> {response_text[:50]}...")
    except Exception as e:
        logger.error(f"Ошибка при логировании запроса: {str(e)}")

# Функции для администраторов
def load_allowed_admins() -> List[int]:
    """Загружает список ID администраторов из БД."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM allowed_admins;")
        admins = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return admins
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_admins: {str(e)}")
        return []

def save_allowed_admins(allowed_admins: List[int]) -> None:
    """Сохраняет список ID администраторов в БД."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM allowed_admins;")
        for admin_id in allowed_admins:
            cur.execute("INSERT INTO allowed_admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING;", (admin_id,))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Список администраторов сохранён в БД.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении allowed_admins: {str(e)}")

# Функции для пользователей
def load_allowed_users() -> List[int]:
    """Загружает список ID разрешённых пользователей из БД."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM allowed_users;")
        users = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return users
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_users: {str(e)}")
        return []

def save_allowed_users(allowed_users: List[int]) -> None:
    """Сохраняет список ID разрешённых пользователей в БД."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM allowed_users;")
        for user_id in allowed_users:
            cur.execute("INSERT INTO allowed_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING;", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Список пользователей сохранён в БД.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении allowed_users: {str(e)}")

# Функции для профилей пользователей
def load_user_profiles() -> Dict[int, Dict[str, str]]:
    """Загружает профили пользователей из БД."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM user_profiles;")
        profiles = {row['user_id']: dict(row) for row in cur.fetchall()}
        cur.close()
        conn.close()
        return profiles
    except Exception as e:
        logger.error(f"Ошибка при загрузке user_profiles: {str(e)}")
        return {}

def save_user_profiles(profiles: Dict[int, Dict[str, str]]) -> None:
    """Сохраняет профили пользователей в БД."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for user_id, data in profiles.items():
            cur.execute("""
                INSERT INTO user_profiles (user_id, fio, name, region) 
                VALUES (%s, %s, %s, %s) 
                ON CONFLICT (user_id) DO UPDATE SET 
                fio = EXCLUDED.fio, name = EXCLUDED.name, region = EXCLUDED.region;
            """, (user_id, data.get('fio'), data.get('name'), data.get('region')))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Профили сохранены в БД.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении user_profiles: {str(e)}")

# Функции для базы знаний
def load_knowledge_base() -> List[str]:
    """Загружает базу знаний из файла."""
    try:
        if not os.path.exists('knowledge_base.json'):
            with open('knowledge_base.json', 'w', encoding='utf-8') as f:
                json.dump({"facts": []}, f, ensure_ascii=False)
        with open('knowledge_base.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('facts', [])
    except Exception as e:
        logger.error(f"Ошибка при загрузке knowledge_base.json: {str(e)}")
        return []

def add_knowledge(fact: str, facts: List[str]) -> List[str]:
    if fact.strip() and fact not in facts:
        facts.append(fact.strip())
        logger.info(f"Добавлен факт: {fact}")
    return facts

def remove_knowledge(fact: str, facts: List[str]) -> List[str]:
    fact = fact.strip()
    if fact in facts:
        facts.remove(fact)
        logger.info(f"Факт удалён: {fact}")
    return facts

def save_knowledge_base(facts: List[str]) -> None:
    """Сохраняет базу знаний в файл."""
    try:
        data = {"facts": facts}
        with open('knowledge_base.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"База знаний сохранена с {len(facts)} фактами.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении knowledge_base.json: {str(e)}")

# Инициализация глобальных переменных (после функций БД)
ALLOWED_ADMINS = load_allowed_admins()
ALLOWED_USERS = load_allowed_users()
USER_PROFILES = load_user_profiles()
KNOWLEDGE_BASE = load_knowledge_base()

# Системный промпт
system_prompt = """
Вы — полезный чат-бот, который логически анализирует всю историю переписки, чтобы давать последовательные ответы.
Обязательно используй актуальные данные из поиска в истории сообщений для ответов на вопросы о фактах, организациях или событиях.
Если данные из поиска доступны, основывайся только на них и отвечай подробно, но кратко.
Если данных нет, используй свои знания и базу знаний, предоставленную системой.
Не упоминай процесс поиска, источники или фразы вроде "не знаю" или "уточните".
Всегда учитывай полный контекст разговора.
Отвечай кратко, по делу, на русском языке, без лишних объяснений.
"""

# Хранение истории переписки
histories: Dict[int, Dict[str, Any]] = {}

# Функции для Яндекс.Диска (без изменений, но с логированием в функциях)
# ... (код функций create_yandex_folder, list_yandex_disk_items, list_yandex_disk_directories, list_yandex_disk_files, get_yandex_disk_file, upload_to_yandex_disk, delete_yandex_disk_file - без изменений, как в предыдущих версиях)

# Обработчики команд (с global и логированием)
# ... (код функций handle_learn, handle_forget, send_welcome, show_main_menu, get_file, search_and_send_file, handle_document, show_file_list, show_current_docs, handle_callback_query, show_main_menu_with_query, handle_message, error_handler - без изменений, как в предыдущих версиях, но с global в начале функций, где нужно)

# Webhook endpoint
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.process_update(update)
    return 'OK'

# Глобальное приложение Telegram
application: Optional[Application] = None

# Главная функция
def main() -> None:
    global application
    logger.info("Запуск Telegram бота на Railway...")
    init_db()
    create_yandex_folder('/regions/')
    create_yandex_folder('/documents/')

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", send_welcome))
    application.add_handler(CommandHandler("getfile", get_file))
    application.add_handler(CommandHandler("learn", handle_learn))
    application.add_handler(CommandHandler("forget", handle_forget))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_error_handler(error_handler)

    port = int(os.environ.get('PORT', 5000))
    webhook_url = f"https://{os.environ.get('RAILWAY_STATIC_URL', 'your-app.railway.app')}/webhook"
    application.bot.set_webhook(webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

    flask_app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    main()