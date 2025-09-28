from __future__ import annotations

import os
import json
import logging
import openai
import requests
from typing import Dict, List, Any
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram import InputFile
from urllib.parse import quote
from openai import OpenAI
import psycopg2  # Добавляем для работы с Postgres
from psycopg2.extras import Json  # Для хранения JSON в БД

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
load_dotenv()  # Загружаем .env для локального запуска
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
YANDEX_TOKEN = os.environ.get("YANDEX_TOKEN")
XAI_TOKEN = os.environ.get("XAI_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")  # URL для Postgres из Railway

# Проверка токенов и DATABASE_URL
missing_tokens = []
if not TELEGRAM_TOKEN:
    missing_tokens.append("TELEGRAM_TOKEN")
if not YANDEX_TOKEN:
    missing_tokens.append("YANDEX_TOKEN")
if not XAI_TOKEN:
    missing_tokens.append("XAI_TOKEN")
if not DATABASE_URL:
    missing_tokens.append("DATABASE_URL")

if missing_tokens:
    logger.error(f"Отсутствуют токены: {', '.join(missing_tokens)}")
    raise ValueError(f"Укажите следующие токены в настройках Railway или .env: {', '.join(missing_tokens)}")

# Инициализация клиента OpenAI
client = OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=XAI_TOKEN,
)

# Словарь федеральных округов (остаётся без изменений)
FEDERAL_DISTRICTS = {
    # ... (ваш словарь, без изменений)
}

# Функции для работы с Postgres
def get_db_connection():
    """Создаёт соединение с Postgres."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {str(e)}")
        raise

def init_db():
    """Инициализирует таблицы в БД, если они не существуют."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Таблица для администраторов (ID как BIGINT для Telegram IDs)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_admins (
                id BIGINT PRIMARY KEY
            );
        """)
        # Таблица для пользователей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                id BIGINT PRIMARY KEY
            );
        """)
        # Таблица для профилей пользователей (user_id как ключ, profile как JSON)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id BIGINT PRIMARY KEY,
                profile JSONB
            );
        """)
        # Таблица для базы знаний (facts как массив строк, но для простоты - отдельные записи)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id SERIAL PRIMARY KEY,
                fact TEXT NOT NULL
            );
        """)
        # Таблица для логов запросов (для просмотра registrations и запросов)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                request_text TEXT,
                response_text TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        logger.info("Таблицы в БД инициализированы.")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {str(e)}")
    finally:
        cur.close()
        conn.close()

# Вызываем инициализацию БД при запуске
init_db()

# Функции для работы с администраторами (теперь с БД)
def load_allowed_admins() -> List[int]:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM allowed_admins;")
        admins = [row[0] for row in cur.fetchall()]
        if not admins:
            # Добавляем дефолтного админа, если пусто (замените на ваш ID)
            default_admin = 123456789
            cur.execute("INSERT INTO allowed_admins (id) VALUES (%s) ON CONFLICT DO NOTHING;", (default_admin,))
            conn.commit()
            admins.append(default_admin)
        return admins
    except Exception as e:
        logger.error(f"Ошибка загрузки admins: {str(e)}")
        return []
    finally:
        cur.close()
        conn.close()

def save_allowed_admins(allowed_admins: List[int]) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM allowed_admins;")
        for admin_id in allowed_admins:
            cur.execute("INSERT INTO allowed_admins (id) VALUES (%s);", (admin_id,))
        conn.commit()
        logger.info("Админы сохранены в БД.")
    except Exception as e:
        logger.error(f"Ошибка сохранения admins: {str(e)}")
    finally:
        cur.close()
        conn.close()

# Аналогично для allowed_users
def load_allowed_users() -> List[int]:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM allowed_users;")
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка загрузки users: {str(e)}")
        return []
    finally:
        cur.close()
        conn.close()

def save_allowed_users(allowed_users: List[int]) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM allowed_users;")
        for user_id in allowed_users:
            cur.execute("INSERT INTO allowed_users (id) VALUES (%s);", (user_id,))
        conn.commit()
        logger.info("Пользователи сохранены в БД.")
    except Exception as e:
        logger.error(f"Ошибка сохранения users: {str(e)}")
    finally:
        cur.close()
        conn.close()

# Для user_profiles
def load_user_profiles() -> Dict[int, Dict[str, str]]:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, profile FROM user_profiles;")
        profiles = {row[0]: row[1] for row in cur.fetchall()}
        return profiles
    except Exception as e:
        logger.error(f"Ошибка загрузки profiles: {str(e)}")
        return {}
    finally:
        cur.close()
        conn.close()

def save_user_profiles(user_profiles: Dict[int, Dict[str, str]]) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM user_profiles;")
        for user_id, profile in user_profiles.items():
            cur.execute("INSERT INTO user_profiles (user_id, profile) VALUES (%s, %s);", (user_id, Json(profile)))
        conn.commit()
        logger.info("Профили сохранены в БД.")
    except Exception as e:
        logger.error(f"Ошибка сохранения profiles: {str(e)}")
    finally:
        cur.close()
        conn.close()

# Для knowledge_base
def load_knowledge_base() -> List[str]:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT fact FROM knowledge_base ORDER BY id;")
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка загрузки knowledge_base: {str(e)}")
        return []
    finally:
        cur.close()
        conn.close()

def save_knowledge_base(knowledge_base: List[str]) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM knowledge_base;")
        for fact in knowledge_base:
            cur.execute("INSERT INTO knowledge_base (fact) VALUES (%s);", (fact,))
        conn.commit()
        logger.info("Knowledge base сохранена в БД.")
    except Exception as e:
        logger.error(f"Ошибка сохранения knowledge_base: {str(e)}")
    finally:
        cur.close()
        conn.close()

# Функция для логирования запросов
def log_request(user_id: int, request_text: str, response_text: str) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO request_logs (user_id, request_text, response_text) 
            VALUES (%s, %s, %s);
        """, (user_id, request_text, response_text))
        conn.commit()
        logger.info(f"Запрос от {user_id} залогирован.")
    except Exception as e:
        logger.error(f"Ошибка логирования запроса: {str(e)}")
    finally:
        cur.close()
        conn.close()

# Загрузка глобальных переменных (теперь из БД)
ALLOWED_ADMINS = load_allowed_admins()
ALLOWED_USERS = load_allowed_users()
USER_PROFILES = load_user_profiles()
KNOWLEDGE_BASE = load_knowledge_base()
histories = {}

# Главное меню (без изменений)
default_keyboard = [
    ['Вернуться в главное меню'],
    ['/getfile', '/learn', '/forget']
]
default_reply_markup = ReplyKeyboardMarkup(default_keyboard, resize_keyboard=True)

# Системный промпт для AI (без изменений)
system_prompt = "Ты - полезный и дружелюбный ассистент, созданный xAI. Отвечай кратко и по делу, используя предоставленные факты и результаты поиска, если они есть. Если информации недостаточно, предложи поискать или уточнить запрос."

# Функции для Yandex Disk (вставьте реализацию, как в оригинале)
def create_yandex_folder(path: str) -> bool:
    # ... (ваша реализация)

# ... (остальные функции для Yandex, web_search без изменений)

# Обработчики (с минимальными изменениями: теперь save/load используют БД)
# Например, в handle_learn:
async def handle_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (основной код)
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE.append(fact)
    save_knowledge_base(KNOWLEDGE_BASE)  # Теперь сохраняет в БД
    # ...

# Аналогично для других: handle_forget, adduser, deluser и т.д. - замените save/load на новые функции

# В handle_message: добавляем логирование запроса
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (основной код)
    # После получения response_text:
    log_request(user_id, user_input, response_text)  # Логируем запрос и ответ
    # ...

# Главная функция (без изменений, кроме init_db выше)
def main() -> None:
    # ... (ваш код)

if __name__ == "__main__":
    main()