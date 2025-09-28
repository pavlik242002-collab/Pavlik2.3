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

# Проверка токенов
if not all([TELEGRAM_TOKEN, YANDEX_TOKEN, XAI_TOKEN]):
    logger.error("Токены не найдены в .env файле!")
    raise ValueError("Укажите TELEGRAM_TOKEN, YANDEX_TOKEN, XAI_TOKEN в .env")

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

# Функции для работы с администраторами
def load_allowed_admins() -> List[int]:
    """Загружает список ID администраторов из файла."""
    try:
        if not os.path.exists('allowed_admins.json'):
            logger.warning("Файл allowed_admins.json не найден, создаётся новый.")
            with open('allowed_admins.json', 'w', encoding='utf-8') as f:
                json.dump([123456789], f, ensure_ascii=False)  # Замени на свой Telegram ID
        with open('allowed_admins.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_admins.json: {str(e)}")
        return [123456789]  # Замени на свой Telegram ID

def save_allowed_admins(allowed_admins: List[int]) -> None:
    """Сохраняет список ID администраторов в файл."""
    try:
        with open('allowed_admins.json', 'w', encoding='utf-8') as f:
            json.dump(allowed_admins, f, ensure_ascii=False, indent=2)
            logger.info("Список администраторов сохранён.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении allowed_admins.json: {str(e)}")

# Функции для работы с пользователями
def load_allowed_users() -> List[int]:
    """Загружает список ID разрешённых пользователей."""
    try:
        if not os.path.exists('allowed_users.json'):
            logger.warning("Файл allowed_users.json не найден, создаётся новый.")
            with open('allowed_users.json', 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False)
        with open('allowed_users.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке allowed_users.json: {str(e)}")
        return []

def save_allowed_users(allowed_users: List[int]) -> None:
    """Сохраняет список ID разрешённых пользователей."""
    try:
        with open('allowed_users.json', 'w', encoding='utf-8') as f:
            json.dump(allowed_users, f, ensure_ascii=False, indent=2)
            logger.info("Список пользователей сохранён.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении allowed_users.json: {str(e)}")

# Загрузка глобальных переменных (админы, пользователи и т.д.)
ALLOWED_ADMINS = load_allowed_admins()
ALLOWED_USERS = load_allowed_users()

# ... (остальной код, включая функции для Yandex Disk, web_search, load_knowledge_base и т.д. Я опустил их для краткости, но они остаются без изменений. Если нужно, добавьте из оригинала.)

# Главное меню (reply keyboard)
default_keyboard = [
    ['Вернуться в главное меню'],  # Кнопка для ручного возврата, если нужно
    ['/getfile', '/learn', '/forget']
]
default_reply_markup = ReplyKeyboardMarkup(default_keyboard, resize_keyboard=True)

# Обработчик /start
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Доступ запрещён. Обратитесь к администратору.")
        return
    await update.message.reply_text("Добро пожаловать! Напишите сообщение для чата с AI.", reply_markup=default_reply_markup)

# ... (остальные функции, такие как get_file, handle_learn, handle_forget, handle_document - с добавлением return to menu)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Доступ запрещён.")
        return
    # ... (оригинальная логика загрузки документа на Yandex)
    # После успешной загрузки:
    await update.message.reply_text("Документ загружен успешно. Теперь вы можете общаться с AI.", reply_markup=default_reply_markup)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    # ... (оригинальная логика для choice_district, choice_region и т.д.)
    # После любой обработки callback:
    await query.answer()
    await query.message.reply_text("Операция завершена. Теперь вы можете общаться с AI.", reply_markup=default_reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_input = update.message.text.strip()

    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Доступ запрещён.", reply_markup=default_reply_markup)
        return

    # Обработка админ-команд (adduser, deluser и т.д.) - остаётся как в оригинале

    # Обработка текстового сообщения через AI (всегда, без условий на меню)
    # ... (оригинальная логика чата с Grok, добавление знаний, поиск)
    # В конце всегда возвращаем меню
    await update.message.reply_text(final_response, reply_markup=default_reply_markup)

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("Произошла ошибка. Вернитесь в меню.", reply_markup=default_reply_markup)

# Главная функция
def main() -> None:
    logger.info("Запуск Telegram бота...")
    # Создание корневых папок на Yandex
    if not create_yandex_folder('/regions/'):
        logger.error("Не удалось создать папку /regions/")
    if not create_yandex_folder('/documents/'):
        logger.error("Не удалось создать папку /documents/")
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", send_welcome))
        app.add_handler(CommandHandler("getfile", get_file))
        app.add_handler(CommandHandler("learn", handle_learn))
        app.add_handler(CommandHandler("forget", handle_forget))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        app.add_handler(CallbackQueryHandler(handle_callback_query))
        app.add_error_handler(error_handler)
        app.run_polling()
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")

if __name__ == "__main__":
    main()