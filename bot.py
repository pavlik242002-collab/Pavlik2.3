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
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Инициализирует таблицы в БД."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS allowed_admins (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS allowed_users (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            fio TEXT,
            name TEXT,
            region TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            request_text TEXT,
            response_text TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Инициализируем с дефолтным админом (замените на свой ID)
    default_admin = 123456789
    cur.execute("INSERT INTO allowed_admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING;", (default_admin,))
    conn.commit()
    cur.close()
    conn.close()
    logger.info("База данных инициализирована.")

def log_request(user_id: int, request_text: str, response_text: str) -> None:
    """Сохраняет запрос и ответ в таблицу user_requests."""
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

def load_allowed_admins() -> List[int]:
    """Загружает список ID администраторов из БД."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM allowed_admins;")
    admins = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return admins

def save_allowed_admins(allowed_admins: List[int]) -> None:
    """Сохраняет список ID администраторов в БД."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM allowed_admins;")
    for admin_id in allowed_admins:
        cur.execute("INSERT INTO allowed_admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING;", (admin_id,))
    conn.commit()
    cur.close()
    conn.close()
    logger.info("Список администраторов сохранён в БД.")

def load_allowed_users() -> List[int]:
    """Загружает список ID разрешённых пользователей из БД."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM allowed_users;")
    users = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return users

def save_allowed_users(allowed_users: List[int]) -> None:
    """Сохраняет список ID разрешённых пользователей в БД."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM allowed_users;")
    for user_id in allowed_users:
        cur.execute("INSERT INTO allowed_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING;", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    logger.info("Список пользователей сохранён в БД.")

def load_user_profiles() -> Dict[int, Dict[str, str]]:
    """Загружает профили пользователей из БД."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM user_profiles;")
    profiles = {row['user_id']: dict(row) for row in cur.fetchall()}
    cur.close()
    conn.close()
    return profiles

def save_user_profiles(profiles: Dict[int, Dict[str, str]]) -> None:
    """Сохраняет профили пользователей в БД."""
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

# Функции для Яндекс.Диска
def create_yandex_folder(folder_path: str) -> bool:
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
    items = list_yandex_disk_items(folder_path, item_type='dir')
    return [item['name'] for item in items]

def list_yandex_disk_files(folder_path: str) -> List[Dict[str, str]]:
    folder_path = folder_path.rstrip('/')
    items = list_yandex_disk_items(folder_path, item_type='file')
    supported_extensions = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')
    files = [item for item in items if item['name'].lower().endswith(supported_extensions)]
    logger.info(f"Найдено {len(files)} файлов в папке {folder_path}: {[item['name'] for item in files]}")
    return files

def get_yandex_disk_file(file_path: str) -> str | None:
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

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global ALLOWED_USERS, ALLOWED_ADMINS, USER_PROFILES
    if update.effective_user is None or update.effective_chat is None:
        response = "Ошибка: не удалось определить пользователя или чат."
        await update.message.reply_text(response)
        log_request(0, "/start", response)
        logger.error("Ошибка: update.effective_user или update.effective_chat is None")
        return

    user_id: int = update.effective_user.id
    chat_id: int = update.effective_chat.id
    context.user_data.clear()

    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        response = f"Ваш user_id: {user_id}\nИзвините, у вас нет доступа. Передайте user_id администратору."
        await update.message.reply_text(response, reply_markup=ReplyKeyboardRemove())
        log_request(user_id, "/start", response)
        logger.info(f"Пользователь {user_id} попытался получить доступ.")
        return

    if user_id not in USER_PROFILES:
        context.user_data["awaiting_fio"] = True
        response = "Доброго времени суток!\nДля начала работы напишите своё ФИО."
        await update.message.reply_text(response, reply_markup=ReplyKeyboardRemove())
        log_request(user_id, "/start", response)
        logger.info(f"Пользователь {chat_id} начал регистрацию.")
        return

    profile = USER_PROFILES[user_id]
    if profile.get("name") is None:
        context.user_data["awaiting_name"] = True
        response = "Как я могу к Вам обращаться (кратко для удобства)?"
        await update.message.reply_text(response, reply_markup=ReplyKeyboardRemove())
        log_request(user_id, "/start", response)
    else:
        await show_main_menu(update, context)
        response = "Выберите действие:"
        log_request(user_id, "/start", response)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    admin_keyboard = [
        ['Управление пользователями', 'Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ] if user_id in ALLOWED_ADMINS else [
        ['Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ]
    reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
    context.user_data['default_reply_markup'] = reply_markup
    context.user_data.pop('current_mode', None)
    context.user_data.pop('current_dir', None)
    context.user_data.pop('file_list', None)
    context.user_data.pop('current_path', None)
    response = "Выберите действие:"
    await update.message.reply_text(response, reply_markup=reply_markup)
    log_request(user_id, "show_main_menu", response)

async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global ALLOWED_USERS, ALLOWED_ADMINS
    user_id: int = update.effective_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        response = "Извините, у вас нет доступа."
        await update.message.reply_text(response, reply_markup=ReplyKeyboardRemove())
        log_request(user_id, "/getfile", response)
        logger.info(f"Пользователь {user_id} попытался скачать файл.")
        return

    if user_id not in USER_PROFILES:
        response = "Сначала пройдите регистрацию с /start."
        await update.message.reply_text(response)
        log_request(user_id, "/getfile", response)
        return

    if not context.args:
        response = "Укажите название файла (например, file.pdf)."
        await update.message.reply_text(response)
        log_request(user_id, "/getfile", response)
        return

    file_name = ' '.join(context.args).strip()
    await search_and_send_file(update, context, file_name)

async def search_and_send_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_name: str) -> None:
    user_id: int = update.effective_user.id
    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        response = "Ошибка: регион не определён. Перезапустите /start."
        await update.message.reply_text(response)
        log_request(user_id, f"getfile {file_name}", response)
        logger.error(f"Ошибка: регион не определён для пользователя {user_id}.")
        return

    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        response = "Ошибка: не удалось проверить или создать папку региона."
        await update.message.reply_text(response)
        log_request(user_id, f"getfile {file_name}", response)
        logger.error(f"Не удалось создать папку {region_folder}.")
        return

    if not file_name.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')):
        response = "Поддерживаются только файлы .pdf, .doc, .docx, .xls, .xlsx, .cdr, .eps, .png, .jpg, .jpeg."
        await update.message.reply_text(response)
        log_request(user_id, f"getfile {file_name}", response)
        logger.error(f"Неподдерживаемый формат файла {file_name}.")
        return

    files = list_yandex_disk_files(region_folder)
    matching_file = next((item for item in files if item['name'].lower() == file_name.lower()), None)

    if not matching_file:
        response = f"Файл '{file_name}' не найден в папке {region_folder}."
        await update.message.reply_text(response)
        log_request(user_id, f"getfile {file_name}", response)
        logger.info(f"Файл '{file_name}' не найден.")
        return

    file_path = matching_file['path']
    download_url = get_yandex_disk_file(file_path)
    if not download_url:
        response = "Ошибка: не удалось получить ссылку для скачивания."
        await update.message.reply_text(response)
        log_request(user_id, f"getfile {file_name}", response)
        logger.error(f"Не удалось получить ссылку для файла {file_path}.")
        return

    try:
        file_response = requests.get(download_url)
        if file_response.status_code == 200:
            file_size = len(file_response.content) / (1024 * 1024)
            if file_size > 20:
                response = "Файл слишком большой (>20 МБ)."
                await update.message.reply_text(response)
                log_request(user_id, f"getfile {file_name}", response)
                logger.error(f"Файл {file_name} слишком большой: {file_size} МБ")
                return
            await update.message.reply_document(
                document=InputFile(file_response.content, filename=file_name)
            )
            response = f"Файл {file_name} отправлен."
            log_request(user_id, f"getfile {file_name}", response)
            logger.info(f"Файл {file_name} отправлен пользователю {user_id}.")
        else:
            response = "Не удалось загрузить файл с Яндекс.Диска."
            await update.message.reply_text(response)
            log_request(user_id, f"getfile {file_name}", response)
            logger.error(f"Ошибка загрузки файла {file_path}: код {file_response.status_code}")
    except Exception as e:
        response = f"Ошибка при отправке файла: {str(e)}"
        await update.message.reply_text(response)
        log_request(user_id, f"getfile {file_name}", response)
        logger.error(f"Ошибка при отправке файла {file_path}: {str(e)}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    if not context.user_data.get('awaiting_upload', False):
        response = "Используйте кнопку 'Загрузить файл' перед отправкой документа."
        await update.message.reply_text(response)
        log_request(user_id, "upload_file", response)
        return

    document = update.message.document
    file_name = document.file_name
    if not file_name.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')):
        response = "Поддерживаются только файлы .pdf, .doc, .docx, .xls, .xlsx, .cdr, .eps, .png, .jpg, .jpeg."
        await update.message.reply_text(response)
        log_request(user_id, f"upload_file {file_name}", response)
        return

    file_size = document.file_size / (1024 * 1024)
    if file_size > 50:
        response = "Файл слишком большой (>50 МБ)."
        await update.message.reply_text(response)
        log_request(user_id, f"upload_file {file_name}", response)
        return

    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        response = "Ошибка: регион не определён. Обновите профиль с /start."
        await update.message.reply_text(response)
        log_request(user_id, f"upload_file {file_name}", response)
        return
    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        response = "Ошибка: не удалось создать папку региона."
        await update.message.reply_text(response)
        log_request(user_id, f"upload_file {file_name}", response)
        logger.error(f"Не удалось создать папку {region_folder}.")
        return

    try:
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        if upload_to_yandex_disk(file_content, file_name, region_folder):
            response = f"Файл успешно загружен в папку {region_folder}"
            await update.message.reply_text(response)
            log_request(user_id, f"upload_file {file_name}", response)
        else:
            response = "Ошибка при загрузке файла на Яндекс.Диск."
            await update.message.reply_text(response)
            log_request(user_id, f"upload_file {file_name}", response)
    except Exception as e:
        response = f"Ошибка при обработке файла: {str(e)}"
        await update.message.reply_text(response)
        log_request(user_id, f"upload_file {file_name}", response)
        logger.error(f"Ошибка обработки документа от {user_id}: {str(e)}")

    context.user_data.pop('awaiting_upload', None)
    logger.info(f"Пользователь {user_id} загрузил файл {file_name} в {region_folder}.")

async def show_file_list(update: Update, context: ContextTypes.DEFAULT_TYPE, for_deletion: bool = False) -> None:
    user_id: int = update.effective_user.id
    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        response = "Ошибка: регион не определён. Обновите профиль с /start."
        await update.message.reply_text(response, reply_markup=context.user_data.get('default_reply_markup', ReplyKeyboardRemove()))
        log_request(user_id, "show_file_list", response)
        logger.error(f"Ошибка: регион не определён для пользователя {user_id}.")
        return

    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        response = "Ошибка: не удалось создать папку региона."
        await update.message.reply_text(response)
        log_request(user_id, "show_file_list", response)
        logger.error(f"Не удалось создать папку {region_folder}.")
        return

    files = list_yandex_disk_files(region_folder)
    if not files:
        response = f"В папке {region_folder} нет файлов."
        await update.message.reply_text(response, reply_markup=context.user_data.get('default_reply_markup', ReplyKeyboardRemove()))
        log_request(user_id, "show_file_list", response)
        logger.info(f"Папка {region_folder} пуста.")
        return

    context.user_data['file_list'] = files
    keyboard = []
    for idx, item in enumerate(files):
        action = 'delete' if for_deletion else 'download'
        callback_data = f"{action}:{idx}"
        keyboard.append([InlineKeyboardButton(item['name'], callback_data=callback_data)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    action_text = "Выберите файл для удаления:" if for_deletion else "Список всех файлов:"
    await update.message.reply_text(action_text, reply_markup=reply_markup)
    log_request(user_id, "show_file_list", action_text)
    logger.info(f"Пользователь {user_id} запросил список файлов в {region_folder}.")

async def show_current_docs(update: Update, context: ContextTypes.DEFAULT_TYPE, is_return: bool = False) -> None:
    user_id: int = update.effective_user.id
    context.user_data.pop('file_list', None)
    current_path = context.user_data.get('current_path', '/documents/')
    folder_name = current_path.rstrip('/').split('/')[-1] or "Документы"
    if not create_yandex_folder(current_path):
        response = f"Ошибка: не удалось создать папку {current_path}."
        await update.message.reply_text(response, reply_markup=context.user_data.get('default_reply_markup', ReplyKeyboardRemove()))
        log_request(user_id, "show_current_docs", response)
        logger.error(f"Не удалось создать папку {current_path}.")
        return

    files = list_yandex_disk_files(current_path)
    dirs = list_yandex_disk_directories(current_path)

    logger.info(f"Пользователь {user_id} в папке {current_path}, найдено файлов: {len(files)}, папок: {len(dirs)}")

    keyboard = [[dir_name] for dir_name in dirs]
    if current_path != '/documents/':
        keyboard.append(['Назад'])
    keyboard.append(['В главное меню'])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    if files:
        context.user_data['file_list'] = files
        file_keyboard = []
        for idx, item in enumerate(files):
            callback_data = f"doc_download:{idx}"
            file_keyboard.append([InlineKeyboardButton(item['name'], callback_data=callback_data)])
        file_reply_markup = InlineKeyboardMarkup(file_keyboard)
        response = f"Файлы в папке {folder_name}:"
        await update.message.reply_text(response, reply_markup=file_reply_markup)
        log_request(user_id, "show_current_docs", response)
        logger.info(f"Пользователь {user_id} получил список файлов в {current_path}.")
    elif dirs:
        if not is_return:
            message = "Документы для РО" if current_path == '/documents/' else f"Папки в {folder_name}:"
            await update.message.reply_text(message, reply_markup=reply_markup)
            log_request(user_id, "show_current_docs", message)
        logger.info(f"Пользователь {user_id} получил список подпапок в {current_path}.")
    else:
        response = f"Папка {folder_name} пуста."
        await update.message.reply_text(response, reply_markup=reply_markup)
        log_request(user_id, "show_current_docs", response)
        logger.info(f"Папка {current_path} пуста.")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id: int = update.effective_user.id
    profile = USER_PROFILES.get(user_id)
    default_reply_markup = context.user_data.get('default_reply_markup', ReplyKeyboardRemove())

    if not query.message:
        response = "Ошибка: сообщение недоступно."
        await query.message.reply_text(response, reply_markup=default_reply_markup)
        log_request(user_id, f"callback_query {query.data}", response)
        logger.error(f"Ошибка: query.message is None для user_id {user_id}")
        return

    if not profile or "region" not in profile:
        response = "Ошибка: регион не определён. Перезапустите /start."
        await query.message.reply_text(response, reply_markup=default_reply_markup)
        log_request(user_id, f"callback_query {query.data}", response)
        logger.error(f"Ошибка: регион не определён для пользователя {user_id}.")
        return

    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        response = "Ошибка: не удалось создать папку региона."
        await query.message.reply_text(response, reply_markup=default_reply_markup)
        log_request(user_id, f"callback_query {query.data}", response)
        logger.error(f"Не удалось создать папку {region_folder}.")
        return

    if query.data.startswith("doc_download:"):
        parts = query.data.split(":", 1)
        if len(parts) != 2:
            response = "Ошибка: неверный формат запроса."
            await query.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, f"callback_query {query.data}", response)
            logger.error(f"Неверный формат callback_data: {query.data}")
            return
        try:
            file_idx = int(parts[1])
        except ValueError:
            response = "Ошибка: неверный индекс файла."
            await query.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, f"callback_query {query.data}", response)
            logger.error(f"Неверный индекс в callback_data: {query.data}")
            return
        current_path = context.user_data.get('current_path', '/documents/')
        files = context.user_data.get('file_list', [])
        if not files:
            files = list_yandex_disk_files(current_path)
            context.user_data['file_list'] = files
            logger.info(f"Перезагружен file_list для {current_path}.")
        if not files or file_idx >= len(files):
            response = "Ошибка: файл не найден. Попробуйте обновить список."
            await query.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, f"callback_query {query.data}", response)
            logger.error(f"Файл с индексом {file_idx} не найден.")
            return
        file_name = files[file_idx]['name']
        file_path = f"{current_path.rstrip('/')}/{file_name}"
        download_url = get_yandex_disk_file(file_path)
        if not download_url:
            response = "Ошибка: не удалось получить ссылку для скачивания."
            await query.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, f"callback_query {query.data}", response)
            logger.error(f"Не удалось получить ссылку для файла {file_path}.")
            return
        try:
            file_response = requests.get(download_url)
            if file_response.status_code == 200:
                file_size = len(file_response.content) / (1024 * 1024)
                if file_size > 20:
                    response = "Файл слишком большой (>20 МБ)."
                    await query.message.reply_text(response, reply_markup=default_reply_markup)
                    log_request(user_id, f"callback_query {query.data}", response)
                    logger.error(f"Файл {file_name} слишком большой: {file_size} МБ")
                    return
                await query.message.reply_document(
                    document=InputFile(file_response.content, filename=file_name)
                )
                response = f"Файл {file_name} отправлен."
                log_request(user_id, f"callback_query {query.data}", response)
                logger.info(f"Файл {file_name} из {current_path} отправлен пользователю {user_id}.")
            else:
                response = "Не удалось загрузить файл с Яндекс.Диска."
                await query.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"callback_query {query.data}", response)
                logger.error(f"Ошибка загрузки файла {file_path}: код {file_response.status_code}")
        except Exception as e:
            response = f"Ошибка при отправке файла: {str(e)}"
            await query.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, f"callback_query {query.data}", response)
            logger.error(f"Ошибка при отправке файла {file_path}: {str(e)}")
        return

    if query.data.startswith("download:") or query.data.startswith("delete:"):
        action, file_idx_str = query.data.split(":", 1)
        try:
            file_idx = int(file_idx_str)
        except ValueError:
            response = "Ошибка: неверный индекс файла."
            await query.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, f"callback_query {query.data}", response)
            logger.error(f"Неверный индекс в callback_data: {query.data}")
            return

        files = context.user_data.get('file_list', [])
        if not files:
            files = list_yandex_disk_files(region_folder)
            context.user_data['file_list'] = files
            logger.info(f"Перезагружен file_list для {region_folder}.")
        if not files or file_idx >= len(files):
            response = "Ошибка: файл не найден. Попробуйте обновить список."
            await query.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, f"callback_query {query.data}", response)
            logger.error(f"Файл с индексом {file_idx} не найден.")
            return

        file_name = files[file_idx]['name']
        file_path = f"{region_folder.rstrip('/')}/{file_name}"

        if action == "download":
            if not file_name.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')):
                response = "Поддерживаются только файлы .pdf, .doc, .docx, .xls, .xlsx, .cdr, .eps, .png, .jpg, .jpeg."
                await query.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"callback_query {query.data}", response)
                logger.error(f"Неподдерживаемый формат файла {file_name}.")
                return

            download_url = get_yandex_disk_file(file_path)
            if not download_url:
                response = "Ошибка: не удалось получить ссылку для скачивания."
                await query.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"callback_query {query.data}", response)
                logger.error(f"Не удалось получить ссылку для файла {file_path}.")
                return

            try:
                file_response = requests.get(download_url)
                if file_response.status_code == 200:
                    file_size = len(file_response.content) / (1024 * 1024)
                    if file_size > 20:
                        response = "Файл слишком большой (>20 МБ)."
                        await query.message.reply_text(response, reply_markup=default_reply_markup)
                        log_request(user_id, f"callback_query {query.data}", response)
                        logger.error(f"Файл {file_name} слишком большой: {file_size} МБ")
                        return
                    await query.message.reply_document(
                        document=InputFile(file_response.content, filename=file_name)
                    )
                    response = f"Файл {file_name} отправлен."
                    log_request(user_id, f"callback_query {query.data}", response)
                    logger.info(f"Файл {file_name} отправлен пользователю {user_id}.")
                else:
                    response = "Не удалось загрузить файл с Яндекс.Диска."
                    await query.message.reply_text(response, reply_markup=default_reply_markup)
                    log_request(user_id, f"callback_query {query.data}", response)
                    logger.error(f"Ошибка загрузки файла {file_path}: код {file_response.status_code}")
            except Exception as e:
                response = f"Ошибка при отправке файла: {str(e)}"
                await query.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"callback_query {query.data}", response)
                logger.error(f"Ошибка при отправке файла {file_path}: {str(e)}")

        elif action == "delete":
            if user_id not in ALLOWED_ADMINS:
                response = "Только администраторы могут удалять файлы."
                await query.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"callback_query {query.data}", response)
                logger.info(f"Пользователь {user_id} попытался удалить файл.")
                return

            if delete_yandex_disk_file(file_path):
                response = f"Файл '{file_name}' удалён из папки {region_folder}."
                await query.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"callback_query {query.data}", response)
                logger.info(f"Администратор {user_id} удалил файл {file_name}.")
            else:
                response = f"Ошибка при удалении файла '{file_name}'."
                await query.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"callback_query {query.data}", response)
                logger.error(f"Ошибка при удалении файла {file_name}.")

            context.user_data.pop('file_list', None)
            await show_file_list(update, context, for_deletion=True)

async def show_main_menu_with_query(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = query.from_user.id
    admin_keyboard = [
        ['Управление пользователями', 'Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ] if user_id in ALLOWED_ADMINS else [
        ['Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ]
    reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
    context.user_data['default_reply_markup'] = reply_markup
    context.user_data.pop('current_mode', None)
    context.user_data.pop('current_dir', None)
    context.user_data.pop('file_list', None)
    context.user_data.pop('current_path', None)
    response = "Выберите действие:"
    await query.message.reply_text(response, reply_markup=reply_markup)
    log_request(user_id, "show_main_menu_with_query", response)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global ALLOWED_USERS, ALLOWED_ADMINS, USER_PROFILES, KNOWLEDGE_BASE
    if update.effective_user is None or update.effective_chat is None:
        response = "Ошибка: не удалось определить пользователя или чат."
        await update.message.reply_text(response)
        log_request(0, "message", response)
        logger.error("Ошибка: update.effective_user или update.effective_chat is None")
        return

    user_id: int = update.effective_user.id
    chat_id: int = update.effective_chat.id
    user_input: str = update.message.text.strip()
    logger.info(f"Получено сообщение от {chat_id} (user_id: {user_id}): {user_input}")

    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        response = "Извините, у вас нет доступа."
        await update.message.reply_text(response, reply_markup=ReplyKeyboardRemove())
        log_request(user_id, user_input, response)
        logger.info(f"Пользователь {user_id} попытался отправить сообщение.")
        return

    if user_id not in USER_PROFILES:
        if context.user_data.get("awaiting_fio", False):
            USER_PROFILES[user_id] = {"fio": user_input, "name": None, "region": None}
            try:
                save_user_profiles(USER_PROFILES)
                response = "Выберите федеральный округ:"
                context.user_data["awaiting_fio"] = False
                context.user_data["awaiting_federal_district"] = True
                keyboard = [[district] for district in FEDERAL_DISTRICTS.keys()]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(response, reply_markup=reply_markup)
                log_request(user_id, f"register_fio {user_input}", response)
                logger.info(f"Сохранение ФИО для user_id {user_id}: {user_input}")
            except Exception as e:
                response = "Ошибка при сохранении профиля. Попробуйте снова."
                await update.message.reply_text(response)
                log_request(user_id, f"register_fio {user_input}", response)
                logger.error(f"Ошибка при сохранении профиля для user_id {user_id}: {str(e)}")
            return
        else:
            response = "Сначала пройдите регистрацию с /start."
            await update.message.reply_text(response)
            log_request(user_id, user_input, response)
            return

    admin_keyboard = [
        ['Управление пользователями', 'Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ] if user_id in ALLOWED_ADMINS else [
        ['Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ]
    default_reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)

    if context.user_data.get("awaiting_federal_district", False):
        if user_input in FEDERAL_DISTRICTS:
            context.user_data["selected_federal_district"] = user_input
            context.user_data["awaiting_federal_district"] = False
            context.user_data["awaiting_region"] = True
            regions = FEDERAL_DISTRICTS[user_input]
            keyboard = [[region] for region in regions]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            response = "Выберите регион:"
            await update.message.reply_text(response, reply_markup=reply_markup)
            log_request(user_id, f"register_district {user_input}", response)
            return
        else:
            response = "Пожалуйста, выберите из предложенных округов."
            await update.message.reply_text(response, reply_markup=ReplyKeyboardMarkup(
                [[district] for district in FEDERAL_DISTRICTS.keys()], resize_keyboard=True))
            log_request(user_id, f"register_district {user_input}", response)
            return

    if context.user_data.get("awaiting_region", False):
        selected_district = context.user_data.get("selected_federal_district")
        regions = FEDERAL_DISTRICTS.get(selected_district, [])
        if user_input in regions:
            USER_PROFILES[user_id]["region"] = user_input
            try:
                save_user_profiles(USER_PROFILES)
                region_folder = f"/regions/{user_input}/"
                if not create_yandex_folder(region_folder):
                    response = "Ошибка: не удалось создать папку региона."
                    await update.message.reply_text(response)
                    log_request(user_id, f"register_region {user_input}", response)
                    logger.error(f"Не удалось создать папку {region_folder}.")
                    return
                context.user_data.pop("awaiting_region", None)
                context.user_data.pop("selected_federal_district", None)
                context.user_data["awaiting_name"] = True
                response = "Как я могу к Вам обращаться (кратко для удобства)?"
                await update.message.reply_text(response, reply_markup=ReplyKeyboardRemove())
                log_request(user_id, f"register_region {user_input}", response)
                logger.info(f"Сохранение региона для user_id {user_id}: {user_input}")
            except Exception as e:
                response = "Ошибка при сохранении региона. Попробуйте снова."
                await update.message.reply_text(response)
                log_request(user_id, f"register_region {user_input}", response)
                logger.error(f"Ошибка при сохранении региона для user_id {user_id}: {str(e)}")
            return
        else:
            response = "Пожалуйста, выберите из предложенных регионов."
            await update.message.reply_text(response, reply_markup=ReplyKeyboardMarkup(
                [[region] for region in regions], resize_keyboard=True))
            log_request(user_id, f"register_region {user_input}", response)
            return

    if context.user_data.get("awaiting_name", False):
        profile = USER_PROFILES[user_id]
        profile["name"] = user_input
        try:
            save_user_profiles(USER_PROFILES)
            context.user_data["awaiting_name"] = False
            await show_main_menu(update, context)
            response = f"Рад знакомству, {user_input}! Задавайте вопросы или используйте меню."
            await update.message.reply_text(response, reply_markup=context.user_data.get('default_reply_markup', ReplyKeyboardRemove()))
            log_request(user_id, f"register_name {user_input}", response)
            logger.info(f"Сохранение имени для user_id {user_id}: {user_input}")
        except Exception as e:
            response = "Ошибка при сохранении имени. Попробуйте снова."
            await update.message.reply_text(response)
            log_request(user_id, f"register_name {user_input}", response)
            logger.error(f"Ошибка при сохранении имени для user_id {user_id}: {str(e)}")
        return

    handled = False

    if user_input == "Документы для РО":
        context.user_data['current_mode'] = 'documents_nav'
        context.user_data['current_path'] = '/documents/'
        context.user_data.pop('file_list', None)
        if not create_yandex_folder('/documents/'):
            response = "Ошибка: не удалось создать папку /documents/."
            await update.message.reply_text(response)
            log_request(user_id, user_input, response)
            logger.error(f"Не удалось создать папку /documents/.")
            return
        await show_current_docs(update, context)
        handled = True

    if user_input == "Архив документов РО":
        context.user_data.pop('current_mode', None)
        context.user_data.pop('current_path', None)
        context.user_data.pop('file_list', None)
        await show_file_list(update, context)
        handled = True

    if user_input == "Управление пользователями":
        if user_id not in ALLOWED_ADMINS:
            response = "Только администраторы могут управлять пользователями."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            logger.info(f"Пользователь {user_id} попытался использовать управление пользователями.")
            return
        keyboard = [
            ['Добавить пользователя', 'Добавить администратора'],
            ['Список пользователей', 'Список администраторов'],
            ['Удалить файл'],
            ['Назад']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        context.user_data.pop('current_mode', None)
        context.user_data.pop('current_path', None)
        context.user_data.pop('file_list', None)
        response = "Выберите действие:"
        await update.message.reply_text(response, reply_markup=reply_markup)
        log_request(user_id, user_input, response)
        logger.info(f"Администратор {user_id} запросил управление пользователями.")
        handled = True

    if user_input == "Загрузить файл":
        profile = USER_PROFILES.get(user_id)
        if not profile or "region" not in profile:
            response = "Ошибка: регион не определён. Обновите профиль с /start."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            return
        context.user_data.pop('current_mode', None)
        context.user_data.pop('current_path', None)
        context.user_data.pop('file_list', None)
        response = "Отправьте файл для загрузки."
        await update.message.reply_text(response, reply_markup=default_reply_markup)
        context.user_data['awaiting_upload'] = True
        log_request(user_id, user_input, response)
        logger.info(f"Пользователь {user_id} начал загрузку файла.")
        handled = True

    if user_input == "Удалить файл":
        if user_id not in ALLOWED_ADMINS:
            response = "Только администраторы могут удалять файлы."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            logger.info(f"Пользователь {user_id} попытался удалить файл.")
            return
        context.user_data['awaiting_delete'] = True
        context.user_data.pop('current_mode', None)
        context.user_data.pop('current_path', None)
        context.user_data.pop('file_list', None)
        await show_file_list(update, context, for_deletion=True)
        handled = True

    if user_input == "Назад":
        await show_main_menu(update, context)
        log_request(user_id, user_input, "Вернулся в главное меню.")
        handled = True

    if context.user_data.get('current_mode') == 'documents_nav':
        current_path = context.user_data.get('current_path', '/documents/')
        dirs = list_yandex_disk_directories(current_path)
        if user_input in dirs:
            context.user_data.pop('file_list', None)
            context.user_data['current_path'] = f"{current_path.rstrip('/')}/{user_input}/"
            if not create_yandex_folder(context.user_data['current_path']):
                response = f"Ошибка: не удалось создать папку {context.user_data['current_path']}."
                await update.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"navigate {user_input}", response)
                logger.error(f"Не удалось создать папку {context.user_data['current_path']}.")
                return
            await show_current_docs(update, context)
            log_request(user_id, f"navigate {user_input}", f"Перешёл в папку {context.user_data['current_path']}")
            handled = True
        elif user_input == 'В главное меню':
            await show_main_menu(update, context)
            log_request(user_id, user_input, "Вернулся в главное меню.")
            handled = True
        elif user_input == 'Назад' and current_path != '/documents/':
            context.user_data.pop('file_list', None)
            parts = current_path.rstrip('/').split('/')
            new_path = '/'.join(parts[:-1]) + '/' if len(parts) > 2 else '/documents/'
            context.user_data['current_path'] = new_path
            await show_current_docs(update, context, is_return=True)
            log_request(user_id, user_input, f"Вернулся назад в {new_path}")
            handled = True

    if context.user_data.get('awaiting_user_id'):
        try:
            new_id = int(user_input)
            if context.user_data['awaiting_user_id'] == 'add_user':
                if new_id in ALLOWED_USERS:
                    response = f"Пользователь с ID {new_id} уже имеет доступ."
                    await update.message.reply_text(response, reply_markup=default_reply_markup)
                    log_request(user_id, f"add_user {user_input}", response)
                    return
                ALLOWED_USERS.append(new_id)
                save_allowed_users(ALLOWED_USERS)
                response = f"Пользователь с ID {new_id} добавлен!"
                await update.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"add_user {user_input}", response)
                logger.info(f"Администратор {user_id} добавил пользователя {new_id}.")
            elif context.user_data['awaiting_user_id'] == 'add_admin':
                if new_id in ALLOWED_ADMINS:
                    response = f"Пользователь с ID {new_id} уже администратор."
                    await update.message.reply_text(response, reply_markup=default_reply_markup)
                    log_request(user_id, f"add_admin {user_input}", response)
                    return
                ALLOWED_ADMINS.append(new_id)
                save_allowed_admins(ALLOWED_ADMINS)
                response = f"Пользователь с ID {new_id} назначен администратором!"
                await update.message.reply_text(response, reply_markup=default_reply_markup)
                log_request(user_id, f"add_admin {user_input}", response)
                logger.info(f"Администратор {user_id} назначил администратора {new_id}.")
            context.user_data.pop('awaiting_user_id', None)
            handled = True
        except ValueError:
            response = "Ошибка: user_id должен быть числом."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            logger.error(f"Ошибка: Неверный формат user_id от {user_id}.")
            handled = True

    if user_input == "Добавить пользователя":
        if user_id not in ALLOWED_ADMINS:
            response = "Только администраторы могут добавлять пользователей."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            logger.info(f"Пользователь {user_id} попытался добавить пользователя.")
            return
        response = "Укажите user_id для добавления."
        await update.message.reply_text(response, reply_markup=default_reply_markup)
        context.user_data['awaiting_user_id'] = 'add_user'
        log_request(user_id, user_input, response)
        logger.info(f"Администратор {user_id} запросил добавление пользователя.")
        handled = True

    if user_input == "Добавить администратора":
        if user_id not in ALLOWED_ADMINS:
            response = "Только администраторы могут назначать администраторов."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            logger.info(f"Пользователь {user_id} попытался добавить администратора.")
            return
        response = "Укажите user_id для назначения администратором."
        await update.message.reply_text(response, reply_markup=default_reply_markup)
        context.user_data['awaiting_user_id'] = 'add_admin'
        log_request(user_id, user_input, response)
        logger.info(f"Администратор {user_id} запросил добавление администратора.")
        handled = True

    if user_input == "Список пользователей":
        if user_id not in ALLOWED_ADMINS:
            response = "Только администраторы могут просматривать список пользователей."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            logger.info(f"Пользователь {user_id} попытался просмотреть список пользователей.")
            return
        if not ALLOWED_USERS:
            response = "Список пользователей пуст."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            return
        users_list = "\n".join([f"ID: {uid}" for uid in ALLOWED_USERS])
        response = f"Разрешённые пользователи:\n{users_list}"
        await update.message.reply_text(response, reply_markup=default_reply_markup)
        log_request(user_id, user_input, response)
        logger.info(f"Администратор {user_id} запросил список пользователей.")
        handled = True

    if user_input == "Список администраторов":
        if user_id not in ALLOWED_ADMINS:
            response = "Только администраторы могут просматривать список администраторов."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            logger.info(f"Пользователь {user_id} попытался просмотреть список администраторов.")
            return
        if not ALLOWED_ADMINS:
            response = "Список администраторов пуст."
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            return
        admins_list = "\n".join([f"ID: {uid}" for uid in ALLOWED_ADMINS])
        response = f"Администраторы:\n{admins_list}"
        await update.message.reply_text(response, reply_markup=default_reply_markup)
        log_request(user_id, user_input, response)
        logger.info(f"Администратор {user_id} запросил список администраторов.")
        handled = True

    if not handled:
        if chat_id not in histories:
            histories[chat_id] = {"name": None, "messages": [{"role": "system", "content": system_prompt}]}

        if KNOWLEDGE_BASE:
            knowledge_text = "Известные факты для использования в ответах: " + "; ".join(KNOWLEDGE_BASE)
            histories[chat_id]["messages"].insert(1, {"role": "system", "content": knowledge_text})
            logger.info(f"Добавлены знания в контекст для user_id {user_id}: {len(KNOWLEDGE_BASE)} фактов")

        need_search = any(word in user_input.lower() for word in [
            "актуальная информация", "последние новости", "найди в интернете", "поиск",
            "что такое", "информация о", "расскажи о", "найди", "поиск по", "детали о",
            "вскс", "спасатели", "корпус спасателей"
        ])

        if need_search:
            logger.info(f"Выполняется поиск для запроса: {user_input}")
            search_results_json = web_search(user_input)
            try:
                results = json.loads(search_results_json)
                if isinstance(results, list):
                    extracted_text = "\n".join(
                        [f"Источник: {r.get('title', '')}\n{r.get('body', '')}" for r in results if r.get('body')])
                else:
                    extracted_text = search_results_json
                histories[chat_id]["messages"].append({"role": "system", "content": f"Актуальные факты: {extracted_text}"})
                logger.info(f"Извлечено из поиска: {extracted_text[:200]}...")
            except json.JSONDecodeError:
                histories[chat_id]["messages"].append(
                    {"role": "system", "content": f"Ошибка поиска: {search_results_json}"})

        histories[chat_id]["messages"].append({"role": "user", "content": user_input})
        if len(histories[chat_id]["messages"]) > 20:
            histories[chat_id]["messages"] = histories[chat_id]["messages"][:1] + histories[chat_id]["messages"][-19:]

        messages = histories[chat_id]["messages"]

        models_to_try = ["grok-3-mini", "grok-beta"]
        response_text = "Извините, не удалось получить ответ от API. Проверьте подписку на SuperGrok или X Premium+."

        for model in models_to_try:
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    stream=False
                )
                response_text = completion.choices[0].message.content.strip()
                logger.info(f"Ответ модели {model} для user_id {user_id}: {response_text}")
                break
            except openai.AuthenticationError as auth_err:
                logger.error(f"Ошибка авторизации для {model}: {str(auth_err)}")
                response_text = "Ошибка авторизации: неверный API-ключ. Проверьте XAI_TOKEN."
                break
            except openai.APIError as api_err:
                if "403" in str(api_err):
                    logger.warning(f"403 Forbidden для {model}. Пробуем следующую модель.")
                    continue
                logger.error(f"Ошибка API для {model}: {str(api_err)}")
                response_text = f"Ошибка API: {str(api_err)}"
                break
            except openai.RateLimitError as rate_err:
                logger.error(f"Превышен лимит для {model}: {str(rate_err)}")
                response_text = "Превышен лимит запросов. Попробуйте позже."
                break
            except Exception as e:
                logger.error(f"Неизвестная ошибка для {model}: {str(e)}")
                response_text = f"Неизвестная ошибка: {str(e)}"
                break
        else:
            logger.error("Все модели недоступны (403). Проверьте токен и подписку.")
            response_text = "Все модели недоступны (403). Обновите SuperGrok или X Premium+."

        user_name = USER_PROFILES.get(user_id, {}).get("name", "Друг")
        final_response = f"{user_name}, {response_text}"
        histories[chat_id]["messages"].append({"role": "assistant", "content": response_text})
        await update.message.reply_text(final_response, reply_markup=default_reply_markup)
        log_request(user_id, user_input, final_response)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        response = "Произошла ошибка, попробуйте позже."
        await update.message.reply_text(response)
        log_request(update.effective_user.id if update.effective_user else 0, "error", response)

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.process_update(update)
    return 'OK'

application: Optional[Application] = None

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