from __future__ import annotations

import os
import json
import logging
import openai
import requests
from typing import Dict, List, Any
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram import InputFile
from urllib.parse import quote
from openai import OpenAI
import psycopg2

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

# Проверка токенов и DATABASE_URL
if not all([TELEGRAM_TOKEN, YANDEX_TOKEN, XAI_TOKEN, DATABASE_URL]):
    logger.error("Токены или DATABASE_URL не найдены в .env файле!")
    raise ValueError("Укажите TELEGRAM_TOKEN, YANDEX_TOKEN, XAI_TOKEN, DATABASE_URL в .env")

# Подключение к Postgres
try:
    conn = psycopg2.connect(DATABASE_URL)
    logger.info("Подключение к Postgres успешно.")
except Exception as e:
    logger.error(f"Ошибка подключения к Postgres: {str(e)}")
    raise ValueError("Не удалось подключиться к базе данных.")

# Инициализация клиента OpenAI
client = OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=XAI_TOKEN,
)


# Функция для загрузки knowledge_base.json
def load_knowledge_base_json() -> Dict[str, str]:
    """Загружает базу знаний из файла knowledge_base.json."""
    try:
        if not os.path.exists('knowledge_base.json'):
            logger.warning("Файл knowledge_base.json не найден, создаётся пустой.")
            with open('knowledge_base.json', 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False)
            return {}
        with open('knowledge_base.json', 'r', encoding='utf-8') as f:
            knowledge = json.load(f)
            logger.info(f"Загружено {len(knowledge)} записей из knowledge_base.json")
            return knowledge
    except Exception as e:
        logger.error(f"Ошибка при загрузке knowledge_base.json: {str(e)}")
        return {}


# Инициализация таблиц в PostgreSQL
def init_db(conn, force_recreate=False):
    try:
        with conn.cursor() as cur:
            if force_recreate:
                cur.execute(
                    "DROP TABLE IF EXISTS request_logs, knowledge_base, user_profiles, allowed_users, allowed_admins;")
                logger.info("Старые таблицы удалены.")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS allowed_admins (
                    id BIGINT NOT NULL PRIMARY KEY
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS allowed_users (
                    id BIGINT NOT NULL PRIMARY KEY
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id BIGINT NOT NULL PRIMARY KEY,
                    fio TEXT,
                    name TEXT,
                    region TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id SERIAL PRIMARY KEY,
                    fact TEXT NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    request TEXT NOT NULL,
                    response TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                INSERT INTO allowed_admins (id) VALUES (6909708460) ON CONFLICT DO NOTHING;
            """)
            conn.commit()
            logger.info(f"Все таблицы успешно созданы или обновлены. Force recreate: {force_recreate}")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {str(e)}")
        conn.rollback()
        raise


init_db(conn, force_recreate=False)

# Словарь федеральных округов
FEDERAL_DISTRICTS = {
    "Центральный федеральный округ": [
        "Белгородская область", "Брянская область", "Владимирская область", "Воронежская область",
        "Ивановская область", "Калужская область", "Костромская область", "Курская область",
        "Липецкая область", "Московская область", "Орловская область", "Рязанская область",
        "Смоленская область", "Тамбовская область", "Тверская область", "Тульская область",
        "Ярославская область", "Москва"
    ],
    # ... (остальные округа остаются без изменений)
}


# Функции для работы с администраторами
def load_allowed_admins() -> List[int]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM allowed_admins")
            admins = [row[0] for row in cur.fetchall()]
            logger.info(f"Загружено {len(admins)} администраторов")
            if not admins:
                cur.execute("INSERT INTO allowed_admins (id) VALUES (%s) ON CONFLICT DO NOTHING", (6909708460,))
                conn.commit()
                admins = [6909708460]
            return admins
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_admins: {str(e)}")
        conn.rollback()
        return [6909708460]


def save_allowed_admins(allowed_admins: List[int]) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM allowed_admins")
            for admin_id in allowed_admins:
                cur.execute("INSERT INTO allowed_admins (id) VALUES (%s)", (admin_id,))
            conn.commit()
            logger.info(f"Сохранено {len(allowed_admins)} администраторов")
    except Exception as e:
        logger.error(f"Ошибка при сохранении allowed_admins: {str(e)}")
        conn.rollback()


# Функции для работы с пользователями
def load_allowed_users() -> List[int]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM allowed_users")
            users = [row[0] for row in cur.fetchall()]
            logger.info(f"Загружено {len(users)} пользователей")
            return users
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_users: {str(e)}")
        conn.rollback()
        return []


def save_allowed_users(allowed_users: List[int]) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM allowed_users")
            for user_id in allowed_users:
                cur.execute("INSERT INTO allowed_users (id) VALUES (%s)", (user_id,))
            conn.commit()
            logger.info(f"Сохранено {len(allowed_users)} пользователей")
    except Exception as e:
        logger.error(f"Ошибка при сохранении allowed_users: {str(e)}")
        conn.rollback()


# Функции для профилей пользователей
def load_user_profiles() -> Dict[int, Dict[str, str]]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, fio, name, region FROM user_profiles")
            profiles = {}
            for row in cur.fetchall():
                profiles[row[0]] = {"fio": row[1], "name": row[2], "region": row[3]}
            logger.info(f"Загружено {len(profiles)} профилей пользователей")
            return profiles
    except Exception as e:
        logger.error(f"Ошибка при загрузке user_profiles: {str(e)}")
        conn.rollback()
        return {}


def save_user_profiles(profiles: Dict[int, Dict[str, str]]) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_profiles")
            for user_id, profile in profiles.items():
                cur.execute(
                    "INSERT INTO user_profiles (user_id, fio, name, region) VALUES (%s, %s, %s, %s)",
                    (user_id, profile.get("fio"), profile.get("name"), profile.get("region"))
                )
            conn.commit()
            logger.info(f"Сохранено {len(profiles)} профилей пользователей")
    except Exception as e:
        logger.error(f"Ошибка при сохранении user_profiles: {str(e)}")
        conn.rollback()


# Функции для работы с базой знаний в PostgreSQL
def load_knowledge_base_db() -> List[str]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT fact FROM knowledge_base")
            facts = [row[0] for row in cur.fetchall()]
            logger.info(f"Загружено {len(facts)} фактов из knowledge_base")
            return facts
    except Exception as e:
        logger.error(f"Ошибка при загрузке knowledge_base: {str(e)}")
        conn.rollback()
        return []


def add_knowledge_db(fact: str, facts: List[str]) -> List[str]:
    if fact.strip() and fact not in facts:
        facts.append(fact.strip())
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO knowledge_base (fact) VALUES (%s)", (fact.strip(),))
                conn.commit()
                logger.info(f"Добавлен факт в БД: {fact}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении факта: {str(e)}")
            conn.rollback()
    return facts


# Функция для логирования запросов
def log_request(user_id: int, request: str, response: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO request_logs (user_id, request, response, timestamp) VALUES (%s, %s, %s, NOW())",
                (user_id, request, response)
            )
            conn.commit()
            logger.info(f"Запрос от {user_id} залогирован")
    except Exception as e:
        logger.error(f"Ошибка при логировании запроса: {str(e)}")
        conn.rollback()


# Функции для работы с Яндекс.Диском
def create_yandex_folder(folder_path: str) -> bool:
    folder_path = folder_path.rstrip('/')
    url = f'https://cloud-api.yandex.net/v1/disk/resources?path={quote(folder_path)}'
    headers = {'Authorization': f'OAuth {YANDEX_TOKEN}', 'Content-Type': 'application/json'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return True
        response = requests.put(url, headers=headers)
        if response.status_code in (201, 409):
            logger.info(f"Папка {folder_path} создана")
            return True
        logger.error(f"Ошибка создания папки {folder_path}: {response.status_code}")
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
        logger.error(f"Ошибка Яндекс.Диска: {response.status_code}")
        return []
    except Exception as e:
        logger.error(f"Ошибка при запросе списка элементов: {str(e)}")
        return []


def list_yandex_disk_directories(folder_path: str) -> List[str]:
    items = list_yandex_disk_items(folder_path, item_type='dir')
    return [item['name'] for item in items]


def list_yandex_disk_files(folder_path: str) -> List[Dict[str, str]]:
    folder_path = folder_path.rstrip('/')
    items = list_yandex_disk_items(folder_path, item_type='file')
    supported_extensions = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')
    files = [item for item in items if item['name'].lower().endswith(supported_extensions)]
    logger.info(f"Найдено {len(files)} файлов в папке {folder_path}")
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
        logger.error(f"Ошибка Яндекс.Диска для файла {file_path}: {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при запросе файла {file_path}: {str(e)}")
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
            upload_response = requests.put(upload_url, data=file_content)
            if upload_response.status_code in (201, 202):
                logger.info(f"Файл {file_name} загружен")
                return True
            logger.error(f"Ошибка загрузки файла {file_path}: {upload_response.status_code}")
            return False
        logger.error(f"Ошибка получения URL для загрузки {file_path}: {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при загрузке файла {file_path}: {str(e)}")
        return False


# Инициализация глобальных переменных
ALLOWED_ADMINS = load_allowed_admins()
ALLOWED_USERS = load_allowed_users()
USER_PROFILES = load_user_profiles()
KNOWLEDGE_BASE_JSON = load_knowledge_base_json()
KNOWLEDGE_BASE_DB = load_knowledge_base_db()

# Системный промпт для ИИ
system_prompt = """
Вы — полезный чат-бот, который логически анализирует историю переписки. 
Сначала проверяй базу знаний из knowledge_base.json и PostgreSQL. Если ответа нет, используй свои знания.
Отвечай кратко, на русском языке, без лишних объяснений.
"""

# Хранение истории переписки
histories: Dict[int, Dict[str, Any]] = {}


# Обработчик команды /start
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text(f"Ваш user_id: {user_id}\nИзвините, у вас нет доступа.",
                                        reply_markup=ReplyKeyboardRemove())
        return
    if user_id not in USER_PROFILES:
        context.user_data["awaiting_fio"] = True
        await update.message.reply_text("Напишите своё ФИО.", reply_markup=ReplyKeyboardRemove())
        return
    profile = USER_PROFILES[user_id]
    if profile.get("name") is None:
        context.user_data["awaiting_name"] = True
        await update.message.reply_text("Как я могу к Вам обращаться?", reply_markup=ReplyKeyboardRemove())
    else:
        await show_main_menu(update, context)


# Отображение главного меню
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
    context.user_data.pop('current_path', None)
    context.user_data.pop('file_list', None)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)


# Отображение содержимого папки в /documents/
async def show_current_docs(update: Update, context: ContextTypes.DEFAULT_TYPE, is_return: bool = False) -> None:
    user_id: int = update.effective_user.id
    context.user_data.pop('file_list', None)
    current_path = context.user_data.get('current_path', '/documents/')
    folder_name = current_path.rstrip('/').split('/')[-1] or "Документы"
    if not create_yandex_folder(current_path):
        await update.message.reply_text(f"Ошибка: не удалось создать папку {current_path}.",
                                        reply_markup=context.user_data.get('default_reply_markup',
                                                                           ReplyKeyboardRemove()))
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
        file_keyboard = [[InlineKeyboardButton(item['name'], callback_data=f"doc_download:{idx}")] for idx, item in
                         enumerate(files)]
        file_reply_markup = InlineKeyboardMarkup(file_keyboard)
        await update.message.reply_text(f"Файлы в папке {folder_name}:", reply_markup=file_reply_markup)
    elif dirs:
        if not is_return:
            message = "Документы для РО" if current_path == '/documents/' else f"Папки в {folder_name}:"
            await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(f"Папка {folder_name} пуста.", reply_markup=reply_markup)


# Обработка callback-запросов
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id: int = update.effective_user.id
    default_reply_markup = context.user_data.get('default_reply_markup', ReplyKeyboardRemove())
    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        await query.message.reply_text("Ошибка: регион не определён.", reply_markup=default_reply_markup)
        return
    if query.data.startswith("doc_download:"):
        try:
            file_idx = int(query.data.split(":", 1)[1])
            current_path = context.user_data.get('current_path', '/documents/')
            files = context.user_data.get('file_list', []) or list_yandex_disk_files(current_path)
            context.user_data['file_list'] = files
            if file_idx >= len(files):
                await query.message.reply_text("Ошибка: файл не найден.", reply_markup=default_reply_markup)
                return
            file_name = files[file_idx]['name']
            file_path = f"{current_path.rstrip('/')}/{file_name}"
            download_url = get_yandex_disk_file(file_path)
            if not download_url:
                await query.message.reply_text("Ошибка: не удалось получить ссылку.", reply_markup=default_reply_markup)
                return
            file_response = requests.get(download_url)
            if file_response.status_code == 200:
                file_size = len(file_response.content) / (1024 * 1024)
                if file_size > 20:
                    await query.message.reply_text("Файл слишком большой (>20 МБ).", reply_markup=default_reply_markup)
                    return
                await query.message.reply_document(document=InputFile(file_response.content, filename=file_name))
                logger.info(f"Файл {file_name} отправлен пользователю {user_id}.")
            else:
                await query.message.reply_text("Не удалось загрузить файл.", reply_markup=default_reply_markup)
        except Exception as e:
            await query.message.reply_text(f"Ошибка: {str(e)}", reply_markup=default_reply_markup)
            logger.error(f"Ошибка при отправке файла: {str(e)}")


# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    chat_id: int = update.effective_chat.id
    user_input: str = update.message.text.strip()
    logger.info(f"Получено сообщение от {chat_id} (user_id: {user_id}): {user_input}")
    log_request(user_id, user_input, "Обработка сообщения...")

    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Извините, у вас нет доступа.", reply_markup=ReplyKeyboardRemove())
        return

    if user_id not in USER_PROFILES:
        if context.user_data.get("awaiting_fio", False):
            USER_PROFILES[user_id] = {"fio": user_input, "name": None, "region": None}
            save_user_profiles(USER_PROFILES)
            if user_id not in ALLOWED_USERS:
                ALLOWED_USERS.append(user_id)
                save_allowed_users(ALLOWED_USERS)
            context.user_data["awaiting_fio"] = False
            context.user_data["awaiting_federal_district"] = True
            keyboard = [[district] for district in FEDERAL_DISTRICTS.keys()]
            await update.message.reply_text("Выберите федеральный округ:",
                                            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            return
        await update.message.reply_text("Сначала пройдите регистрацию с /start.")
        return

    admin_keyboard = [
        ['Управление пользователями', 'Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ] if user_id in ALLOWED_ADMINS else [
        ['Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ]
    default_reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
    context.user_data['default_reply_markup'] = default_reply_markup

    # Обработка регистрации
    if context.user_data.get("awaiting_federal_district", False):
        if user_input in FEDERAL_DISTRICTS:
            context.user_data["selected_federal_district"] = user_input
            context.user_data["awaiting_federal_district"] = False
            context.user_data["awaiting_region"] = True
            regions = FEDERAL_DISTRICTS[user_input]
            keyboard = [[region] for region in regions]
            await update.message.reply_text("Выберите регион:",
                                            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            return
        await update.message.reply_text("Выберите из предложенных округов.", reply_markup=ReplyKeyboardMarkup(
            [[district] for district in FEDERAL_DISTRICTS.keys()]))
        return

    if context.user_data.get("awaiting_region", False):
        selected_district = context.user_data.get("selected_federal_district")
        regions = FEDERAL_DISTRICTS.get(selected_district, [])
        if user_input in regions:
            USER_PROFILES[user_id]["region"] = user_input
            save_user_profiles(USER_PROFILES)
            region_folder = f"/regions/{user_input}/"
            create_yandex_folder(region_folder)
            context.user_data.pop("awaiting_region", None)
            context.user_data.pop("selected_federal_district", None)
            context.user_data["awaiting_name"] = True
            await update.message.reply_text("Как я могу к Вам обращаться?", reply_markup=ReplyKeyboardRemove())
            return
        await update.message.reply_text("Выберите из предложенных регионов.",
                                        reply_markup=ReplyKeyboardMarkup([[region] for region in regions]))
        return

    if context.user_data.get("awaiting_name", False):
        USER_PROFILES[user_id]["name"] = user_input
        save_user_profiles(USER_PROFILES)
        context.user_data["awaiting_name"] = False
        await show_main_menu(update, context)
        await update.message.reply_text(f"Рад знакомству, {user_input}! Задавайте вопросы или используйте меню.",
                                        reply_markup=default_reply_markup)
        return

    handled = False

    # Обработка команд меню
    if user_input == "Документы для РО":
        context.user_data['current_mode'] = 'documents_nav'
        context.user_data['current_path'] = '/documents/'
        context.user_data.pop('file_list', None)
        create_yandex_folder('/documents/')
        await show_current_docs(update, context)
        handled = True

    elif user_input == "Архив документов РО":
        context.user_data.pop('current_mode', None)
        context.user_data.pop('current_path', None)
        context.user_data.pop('file_list', None)
        await show_file_list(update, context)
        handled = True

    elif user_input == "Управление пользователями":
        if user_id not in ALLOWED_ADMINS:
            await update.message.reply_text("Только администраторы могут управлять пользователями.",
                                            reply_markup=default_reply_markup)
            return
        keyboard = [['Добавить пользователя', 'Добавить администратора'],
                    ['Список пользователей', 'Список администраторов'], ['Удалить файл'], ['Назад']]
        await update.message.reply_text("Выберите действие:",
                                        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        handled = True

    elif user_input == "Загрузить файл":
        if not USER_PROFILES.get(user_id, {}).get("region"):
            await update.message.reply_text("Ошибка: регион не определён.", reply_markup=default_reply_markup)
            return
        context.user_data['awaiting_upload'] = True
        await update.message.reply_text("Отправьте файл для загрузки.", reply_markup=default_reply_markup)
        handled = True

    elif user_input == "Назад":
        await show_main_menu(update, context)
        handled = True

    # Обработка навигации по documents
    if context.user_data.get('current_mode') == 'documents_nav':
        current_path = context.user_data.get('current_path', '/documents/')
        dirs = list_yandex_disk_directories(current_path)
        dirs_lower = [d.lower() for d in dirs]
        user_input_lower = user_input.lower()
        if user_input_lower in dirs_lower:
            original_dir = next(d for d in dirs if d.lower() == user_input_lower)
            context.user_data['current_path'] = f"{current_path.rstrip('/')}/{original_dir}/"
            create_yandex_folder(context.user_data['current_path'])
            await show_current_docs(update, context)
            handled = True
        elif user_input == 'В главное меню':
            await show_main_menu(update, context)
            handled = True
        elif user_input == 'Назад' and current_path != '/documents/':
            parts = current_path.rstrip('/').split('/')
            context.user_data['current_path'] = '/'.join(parts[:-1]) + '/' if len(parts) > 2 else '/documents/'
            await show_current_docs(update, context, is_return=True)
            handled = True

    # Обработка запросов к базе знаний и ИИ
    if not handled:
        # Проверка в knowledge_base.json
        response = KNOWLEDGE_BASE_JSON.get(user_input, None)
        if response:
            await update.message.reply_text(response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, response)
            return

        # Проверка в базе знаний PostgreSQL
        for fact in KNOWLEDGE_BASE_DB:
            if user_input.lower() in fact.lower():
                await update.message.reply_text(fact, reply_markup=default_reply_markup)
                log_request(user_id, user_input, fact)
                return

        # Запрос к Grok API
        if chat_id not in histories:
            histories[chat_id] = {"name": USER_PROFILES[user_id]["name"],
                                  "messages": [{"role": "system", "content": system_prompt}]}
        histories[chat_id]["messages"].append({"role": "user", "content": user_input})
        try:
            response = client.chat.completions.create(
                model="grok",
                messages=histories[chat_id]["messages"],
                max_tokens=1000
            )
            ai_response = response.choices[0].message.content.strip()
            histories[chat_id]["messages"].append({"role": "assistant", "content": ai_response})
            await update.message.reply_text(ai_response, reply_markup=default_reply_markup)
            log_request(user_id, user_input, ai_response)
        except Exception as e:
            await update.message.reply_text("Ошибка при обращении к ИИ.", reply_markup=default_reply_markup)
            logger.error(f"Ошибка Grok API: {str(e)}")
            log_request(user_id, user_input, "Ошибка ИИ")


# Обработка загруженных документов
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    if not context.user_data.get('awaiting_upload', False):
        await update.message.reply_text("Используйте кнопку 'Загрузить файл' перед отправкой документа.")
        return
    document = update.message.document
    file_name = document.file_name
    if not file_name.lower().endswith(
            ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')):
        await update.message.reply_text(
            "Поддерживаются только файлы .pdf, .doc, .docx, .xls, .xlsx, .cdr, .eps, .png, .jpg, .jpeg.")
        return
    file_size = document.file_size / (1024 * 1024)
    if file_size > 50:
        await update.message.reply_text("Файл слишком большой (>50 МБ).")
        return
    profile = USER_PROFILES.get(user_id)
    region_folder = f"/regions/{profile['region']}/"
    try:
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        if upload_to_yandex_disk(file_content, file_name, region_folder):
            await update.message.reply_text(f"Файл успешно загружен в папку {region_folder}")
        else:
            await update.message.reply_text("Ошибка при загрузке файла.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")
        logger.error(f"Ошибка обработки документа: {str(e)}")
    context.user_data.pop('awaiting_upload', None)


# Отображение списка файлов
async def show_file_list(update: Update, context: ContextTypes.DEFAULT_TYPE, for_deletion: bool = False) -> None:
    user_id: int = update.effective_user.id
    profile = USER_PROFILES.get(user_id)
    region_folder = f"/regions/{profile['region']}/"
    create_yandex_folder(region_folder)
    files = list_yandex_disk_files(region_folder)
    if not files:
        await update.message.reply_text(f"В папке {region_folder} нет файлов.",
                                        reply_markup=context.user_data.get('default_reply_markup',
                                                                           ReplyKeyboardRemove()))
        return
    context.user_data['file_list'] = files
    keyboard = [[InlineKeyboardButton(item['name'], callback_data=f"{'delete' if for_deletion else 'download'}:{idx}")]
                for idx, item in enumerate(files)]
    await update.message.reply_text("Выберите файл для удаления:" if for_deletion else "Список всех файлов:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))


# Основная функция
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", send_welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.run_polling()


if __name__ == '__main__':
    main()