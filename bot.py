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
    """Получает соединение с БД с повторными попытками."""
    import time
    attempts = 3
    for attempt in range(attempts):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            logger.info("Успешное соединение с PostgreSQL.")
            return conn
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных (попытка {attempt + 1}/{attempts}): {str(e)}")
            if attempt < attempts - 1:
                time.sleep(2)  # Ждать 2 секунды перед повторной попыткой
            else:
                raise

def check_table_exists(table_name: str) -> bool:
    """Проверяет, существует ли таблица в базе данных."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = %s
            );
        """, (table_name,))
        exists = cur.fetchone()[0]
        cur.close()
        conn.close()
        logger.info(f"Таблица {table_name} {'существует' if exists else 'не существует'}.")
        return exists
    except Exception as e:
        logger.error(f"Ошибка при проверке таблицы {table_name}: {str(e)}")
        return False

def init_db():
    """Инициализирует таблицы в БД."""
    try:
        conn = get_db_connection()
        logger.info("Соединение с базой данных установлено.")
        cur = conn.cursor()
        # Создание таблицы allowed_admins
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_admins (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE NOT NULL
            );
        """)
        logger.info("Таблица allowed_admins создана или уже существует.")
        # Создание таблицы allowed_users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE NOT NULL
            );
        """)
        logger.info("Таблица allowed_users создана или уже существует.")
        # Создание таблицы user_profiles
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                fio TEXT,
                name TEXT,
                region TEXT
            );
        """)
        logger.info("Таблица user_profiles создана или уже существует.")
        # Создание таблицы user_requests
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
        # Инициализируем с дефолтным админом
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

def check_allowed_users() -> List[Dict[str, Any]]:
    """Проверяет содержимое таблицы allowed_users."""
    try:
        if not check_table_exists("allowed_users"):
            logger.error("Таблица allowed_users не существует. Инициализируем базу данных.")
            init_db()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM public.allowed_users LIMIT 10;")
        users = cur.fetchall()
        cur.close()
        conn.close()
        logger.info(f"Найдено {len(users)} пользователей в таблице allowed_users.")
        return users
    except Exception as e:
        logger.error(f"Ошибка при проверке таблицы allowed_users: {str(e)}")
        return []

def log_request(user_id: int, request_text: str, response_text: str) -> None:
    """Сохраняет запрос и ответ в таблицу user_requests."""
    try:
        if not check_table_exists("user_requests"):
            logger.error("Таблица user_requests не существует. Инициализируем базу данных.")
            init_db()
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

def load_allowed_admins() -> List[int]:
    """Загружает список ID администраторов из БД."""
    try:
        if not check_table_exists("allowed_admins"):
            logger.error("Таблица allowed_admins не существует. Инициализируем базу данных.")
            init_db()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM allowed_admins;")
        admins = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Загружено {len(admins)} администраторов.")
        return admins
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_admins: {str(e)}")
        return []

def save_allowed_admins(allowed_admins: List[int]) -> None:
    """Сохраняет список ID администраторов в БД."""
    try:
        if not check_table_exists("allowed_admins"):
            logger.error("Таблица allowed_admins не существует. Инициализируем базу данных.")
            init_db()
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

def load_allowed_users() -> List[int]:
    """Загружает список ID разрешённых пользователей из БД."""
    try:
        if not check_table_exists("allowed_users"):
            logger.error("Таблица allowed_users не существует. Инициализируем базу данных.")
            init_db()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM allowed_users;")
        users = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        logger.info(f"Загружено {len(users)} пользователей.")
        return users
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_users: {str(e)}")
        return []

def save_allowed_users(allowed_users: List[int]) -> None:
    """Сохраняет список ID разрешённых пользователей в БД."""
    try:
        if not check_table_exists("allowed_users"):
            logger.error("Таблица allowed_users не существует. Инициализируем базу данных.")
            init_db()
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

def load_user_profiles() -> Dict[int, Dict[str, str]]:
    """Загружает профили пользователей из БД."""
    try:
        if not check_table_exists("user_profiles"):
            logger.error("Таблица user_profiles не существует. Инициализируем базу данных.")
            init_db()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM user_profiles;")
        profiles = {row['user_id']: dict(row) for row in cur.fetchall()}
        cur.close()
        conn.close()
        logger.info(f"Загружено {len(profiles)} профилей пользователей.")
        return profiles
    except Exception as e:
        logger.error(f"Ошибка при загрузке user_profiles: {str(e)}")
        return {}

def save_user_profiles(profiles: Dict[int, Dict[str, str]]) -> None:
    """Сохраняет профили пользователей в БД."""
    try:
        if not check_table_exists("user_profiles"):
            logger.error("Таблица user_profiles не существует. Инициализируем базу данных.")
            init_db()
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

# Функции для Яндекс.Диска
def create_yandex_folder(folder_path: str) -> bool:
    """Создаёт папку на Яндекс.Диске."""
    folder_path = folder_path.rstrip('/')
    url = f'https://cloud-api.yandex.net/v1/disk/resources?path={quote(folder_path)}'
    headers = {'Authorization': f'OAuth {YANDEX_TOKEN}', 'Content-Type': 'application/json'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            logger.info(f"Папка {folder_path} уже существует.")
            return True
        response = requests.put(url, headers=headers)
        if response.status_code in (201, 409):
            logger.info(f"Папка {folder_path} создана.")
            return True
        logger.error(f"Ошибка создания папки {folder_path}: код {response.status_code}, ответ: {response.text}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при создании папки {folder_path}: {str(e)}")
        return False

def list_yandex_disk_items(folder_path: str, item_type: str = None) -> List[Dict[str, str]]:
    """Получает список элементов на Яндекс.Диске."""
    folder_path = folder_path.rstrip('/')
    url = f'https://cloud-api.yandex.net/v1/disk/resources?path={quote(folder_path)}&fields=_embedded.items.name,_embedded.items.type,_embedded.items.path&limit=100'
    headers = {'Authorization': f'OAuth {YANDEX_TOKEN}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            items = response.json().get('_embedded', {}).get('items', [])
            if item_type:
                return [item for item in items if item['type'] == item_type]
            return items
        logger.error(f"Ошибка Яндекс.Диска: код {response.status_code}, ответ: {response.text}")
        return []
    except Exception as e:
        logger.error(f"Ошибка при запросе списка элементов в {folder_path}: {str(e)}")
        return []

def list_yandex_disk_directories(folder_path: str) -> List[str]:
    """Получает список папок на Яндекс.Диске."""
    items = list_yandex_disk_items(folder_path, item_type='dir')
    return [item['name'] for item in items]

def list_yandex_disk_files(folder_path: str) -> List[Dict[str, str]]:
    """Получает список файлов на Яндекс.Диске."""
    folder_path = folder_path.rstrip('/')
    items = list_yandex_disk_items(folder_path, item_type='file')
    supported_extensions = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')
    files = [item for item in items if item['name'].lower().endswith(supported_extensions)]
    logger.info(f"Найдено {len(files)} файлов в папке {folder_path}: {[item['name'] for item in files]}")
    return files

def get_yandex_disk_file(file_path: str) -> str | None:
    """Получает ссылку на скачивание файла с Яндекс.Диска."""
    file_path = file_path.rstrip('/')
    encoded_path = quote(file_path, safe='/')
    url = f'https://cloud-api.yandex.net/v1/disk/resources/download?path={encoded_path}'
    headers = {'Authorization': f'OAuth {YANDEX_TOKEN}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('href')
        logger.error(f"Ошибка Яндекс.Диска для файла {file_path}: код {response.status_code}, ответ: {response.text}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при запросе к Яндекс.Диску для файла {file_path}: {str(e)}")
        return None

def upload_to_yandex_disk(file_content: bytes, file_name: str, folder_path: str) -> bool:
    """Загружает файл на Яндекс.Диск."""
    folder_path = folder_path.rstrip('/')
    file_path = f"{folder_path}/{file_name}"
    encoded_path = quote(file_path, safe='/')
    url = f'https://cloud-api.yandex.net/v1/disk/resources/upload?path={encoded_path}&overwrite=true'
    headers = {'Authorization': f'OAuth {YANDEX_TOKEN}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            upload_url = response.json().get('href')
            if upload_url:
                upload_response = requests.put(upload_url, data=file_content)
                if upload_response.status_code in (201, 202):
                    logger.info(f"Файл {file_name} загружен в {folder_path}")
                    return True
                logger.error(f"Ошибка загрузки файла {file_path}: код {upload_response.status_code}")
                return False
            logger.error(f"Не получен URL для загрузки файла {file_path}")
            return False
        logger.error(f"Ошибка получения URL для загрузки {file_path}: код {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при загрузке файла {file_path}: {str(e)}")
        return False

def delete_yandex_disk_file(file_path: str) -> bool:
    """Удаляет файл с Яндекс.Диска."""
    file_path = file_path.rstrip('/')
    encoded_path = quote(file_path, safe='/')
    url = f'https://cloud-api.yandex.net/v1/disk/resources?path={encoded_path}'
    headers = {'Authorization': f'OAuth {YANDEX_TOKEN}'}
    try:
        response = requests.delete(url, headers=headers)
        if response.status_code in (204, 202):
            logger.info(f"Файл {file_path} удалён.")
            return True
        logger.error(f"Ошибка удаления файла {file_path}: код {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при удалении файла {file_path}: {str(e)}")
        return False

# Функция веб-поиска
def web_search(query: str) -> str:
    """Выполняет поиск в интернете через DuckDuckGo."""
    cache_file = 'search_cache.json'
    try:
        if not os.path.exists(cache_file):
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False)
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке search_cache.json: {str(e)}")
        cache = {}
    if query in cache:
        logger.info(f"Использую кэш для запроса: {query}")
        return cache[query]
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, max_results=3)]
        search_results = json.dumps(results, ensure_ascii=False, indent=2)
        cache[query] = search_results
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"Поиск выполнен для запроса: {query}")
        return search_results
    except Exception as e:
        logger.error(f"Ошибка при поиске: {str(e)}")
        return json.dumps({"error": "Не удалось выполнить поиск."}, ensure_ascii=False)

# Инициализация глобальных переменных
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

# Обработчики команд
async def handle_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global KNOWLEDGE_BASE
    user_id: int = update.effective_user.id
    if user_id not in ALLOWED_ADMINS:
        response = "Только администраторы могут обучать бота."
        await update.message.reply_text(response)
        log_request(user_id, "/learn", response)
        return
    if not context.args:
        response = "Использование: /learn <факт>. Например: /learn Земля круглая."
        await update.message.reply_text(response)
        log_request(user_id, "/learn", response)
        return
    fact = ' '.join(context.args)
    KNOWLEDGE_BASE = add_knowledge(fact, KNOWLEDGE_BASE)
    save_knowledge_base(KNOWLEDGE_BASE)
    response = f"Факт добавлен: '{fact}'."
    await update.message.reply_text(response)
    log_request(user_id, f"/learn {fact}", response)
    logger.info(f"Администратор {user_id} добавил факт: {fact}")

async def handle_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global KNOWLEDGE_BASE
    user_id: int = update.effective_user.id
    if user_id not in ALLOWED_ADMINS:
        response = "Только администраторы могут удалять факты."
        await update.message.reply_text(response)
        log_request(user_id, "/forget", response)
        return
    if not context.args:
        response = "Использование: /forget <факт>."
        await update.message.reply_text(response)
        log_request(user_id, "/forget", response)
        return
    fact = ' '.join(context.args)
    KNOWLEDGE_BASE = remove_knowledge(fact, KNOWLEDGE_BASE)
    save_knowledge_base(KNOWLEDGE_BASE)
    response = f"Факт удалён: '{fact}'." if fact not in KNOWLEDGE_BASE else f"Факт '{fact}' не найден."
    await update.message.reply_text(response)
    log_request(user_id, f"/forget {fact}", response)
    logger.info(f"Администратор {user_id} удалил факт: {fact}")

async def handle_check_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ALLOWED_ADMINS:
        response = "Только администраторы могут просматривать таблицу allowed_users."
        await update.message.reply_text(response)
        log_request(user_id, "/check_users", response)
        return
    users = check_allowed_users()
    if not users:
        response = "Таблица allowed_users пуста или произошла ошибка."
    else:
        users_list = "\n".join([f"ID: {user['id']}, User ID: {user['user_id']}" for user in users])
        response = f"Первые