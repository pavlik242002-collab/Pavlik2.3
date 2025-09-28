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
load_dotenv()  # Загружаем .env для локального запуска
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
YANDEX_TOKEN = os.environ.get("YANDEX_TOKEN")
XAI_TOKEN = os.environ.get("XAI_TOKEN")

# Проверка токенов с улучшенным логированием
missing_tokens = []
if not TELEGRAM_TOKEN:
    missing_tokens.append("TELEGRAM_TOKEN")
if not YANDEX_TOKEN:
    missing_tokens.append("YANDEX_TOKEN")
if not XAI_TOKEN:
    missing_tokens.append("XAI_TOKEN")

if missing_tokens:
    logger.error(f"Отсутствуют токены: {', '.join(missing_tokens)}")
    raise ValueError(f"Укажите следующие токены в настройках Railway или .env: {', '.join(missing_tokens)}")

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

# Функции для профилей пользователей
def load_user_profiles() -> Dict[int, Dict[str, str]]:
    """Загружает профили пользователей из файла."""
    try:
        if not os.path.exists('user_profiles.json'):
            logger.warning("Файл user_profiles.json не найден, создаётся новый.")
            with open('user_profiles.json', 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False)
        with open('user_profiles.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке user_profiles.json: {str(e)}")
        return {}

def save_user_profiles(user_profiles: Dict[int, Dict[str, str]]) -> None:
    """Сохраняет профили пользователей в файл."""
    try:
        with open('user_profiles.json', 'w', encoding='utf-8') as f:
            json.dump(user_profiles, f, ensure_ascii=False, indent=2)
            logger.info("Профили пользователей сохранены.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении user_profiles.json: {str(e)}")

# Загрузка глобальных переменных
ALLOWED_ADMINS = load_allowed_admins()
ALLOWED_USERS = load_allowed_users()
USER_PROFILES = load_user_profiles()
KNOWLEDGE_BASE = []
histories = {}

# Главное меню
default_keyboard = [
    ['Вернуться в главное меню'],
    ['/getfile', '/learn', '/forget']
]
default_reply_markup = ReplyKeyboardMarkup(default_keyboard, resize_keyboard=True)

# Системный промпт для AI
system_prompt = "Ты - полезный и дружелюбный ассистент, созданный xAI. Отвечай кратко и по делу, используя предоставленные факты и результаты поиска, если они есть. Если информации недостаточно, предложи поискать или уточнить запрос."

# Функции для работы с Yandex Disk (вставьте из оригинального bot.py)
def create_yandex_folder(path: str) -> bool:
    # Вставьте реализацию из оригинального bot.py
    pass

def upload_to_yandex(file_path: str, yandex_path: str) -> bool:
    # Вставьте реализацию из оригинального bot.py
    pass

def list_yandex_files(path: str) -> List[Dict[str, Any]]:
    # Вставьте реализацию из оригинального bot.py
    pass

def get_yandex_download_link(path: str) -> str:
    # Вставьте реализацию из оригинального bot.py
    pass

# Функция веб-поиска (вставьте из оригинального bot.py)
def web_search(query: str) -> str:
    # Вставьте реализацию из оригинального bot.py
    pass

# Обработчик /start
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Доступ запрещён. Обратитесь к администратору.", reply_markup=default_reply_markup)
        return
    await update.message.reply_text("Добро пожаловать! Напишите сообщение для чата с AI.", reply_markup=default_reply_markup)
    logger.info(f"Пользователь {user_id} запустил бота.")

# Обработчик /getfile
async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Доступ запрещён.", reply_markup=default_reply_markup)
        return
    buttons = [[InlineKeyboardButton(district, callback_data=f"district:{district}")] for district in FEDERAL_DISTRICTS.keys()]
    buttons.append([InlineKeyboardButton("Вернуться в главное меню", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Выберите федеральный округ:", reply_markup=reply_markup)
    logger.info(f"Пользователь {user_id} запросил список файлов.")

# Обработчик /learn
async def handle_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Только администраторы могут добавлять знания.", reply_markup=default_reply_markup)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Укажите факт для добавления, например: /learn Новый факт", reply_markup=default_reply_markup)
        return
    fact = " ".join(args)
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE.append(fact)
    try:
        with open('knowledge_base.json', 'w', encoding='utf-8') as f:
            json.dump({"facts": KNOWLEDGE_BASE}, f, ensure_ascii=False, indent=2)
        await update.message.reply_text(f"Факт добавлен: {fact}", reply_markup=default_reply_markup)
        logger.info(f"Администратор {user_id} добавил факт: {fact}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при сохранении факта: {str(e)}", reply_markup=default_reply_markup)
        logger.error(f"Ошибка при сохранении факта: {str(e)}")

# Обработчик /forget
async def handle_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Только администраторы могут удалять знания.", reply_markup=default_reply_markup)
        return
    global KNOWLEDGE_BASE
    if not KNOWLEDGE_BASE:
        await update.message.reply_text("База знаний пуста.", reply_markup=default_reply_markup)
        return
    buttons = [[InlineKeyboardButton(fact[:50], callback_data=f"forget:{i}")] for i, fact in enumerate(KNOWLEDGE_BASE)]
    buttons.append([InlineKeyboardButton("Вернуться в главное меню", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Выберите факт для удаления:", reply_markup=reply_markup)
    logger.info(f"Администратор {user_id} запросил удаление факта.")

# Обработчик документов
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Доступ запрещён.", reply_markup=default_reply_markup)
        return
    document = update.message.document
    if not document:
        await update.message.reply_text("Пожалуйста, отправьте документ.", reply_markup=default_reply_markup)
        return
    file = await document.get_file()
    file_name = document.file_name
    file_path = f"temp_{file_name}"
    await file.download_to_drive(file_path)
    buttons = [[InlineKeyboardButton(district, callback_data=f"upload_district:{district}:{file_name}")] for district in FEDERAL_DISTRICTS.keys()]
    buttons.append([InlineKeyboardButton("Вернуться в главное меню", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Выберите федеральный округ для загрузки документа:", reply_markup=reply_markup)
    context.user_data["file_path"] = file_path
    logger.info(f"Пользователь {user_id} отправил документ: {file_name}")

# Обработчик callback-запросов
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await query.message.reply_text("Доступ запрещён.", reply_markup=default_reply_markup)
        await query.answer()
        return
    if data == "main_menu":
        await query.message.reply_text("Возвращение в главное меню.", reply_markup=default_reply_markup)
        await query.answer()
        return
    if data.startswith("district:"):
        district = data.split(":", 1)[1]
        regions = FEDERAL_DISTRICTS.get(district, [])
        buttons = [[InlineKeyboardButton(region, callback_data=f"region:{district}:{region}")] for region in regions]
        buttons.append([InlineKeyboardButton("Вернуться в главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.reply_text(f"Выберите регион в {district}:", reply_markup=reply_markup)
        await query.answer()
        return
    if data.startswith("region:"):
        _, district, region = data.split(":", 2)
        files = list_yandex_files(f"/regions/{district}/{region}/")
        if not files:
            await query.message.reply_text(f"Файлы в регионе {region} не найдены.", reply_markup=default_reply_markup)
            await query.answer()
            return
        buttons = [[InlineKeyboardButton(file["name"], callback_data=f"file:{district}:{region}:{file['name']}")] for file in files]
        buttons.append([InlineKeyboardButton("Вернуться в главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.reply_text(f"Файлы в регионе {region}:", reply_markup=reply_markup)
        await query.answer()
        return
    if data.startswith("file:"):
        _, district, region, file_name = data.split(":", 3)
        file_path = f"/regions/{district}/{region}/{file_name}"
        download_link = get_yandex_download_link(file_path)
        if download_link:
            await query.message.reply_document(document=download_link, filename=file_name)
            await query.message.reply_text("Файл отправлен. Теперь вы можете общаться с AI.", reply_markup=default_reply_markup)
        else:
            await query.message.reply_text("Ошибка при получении файла.", reply_markup=default_reply_markup)
        await query.answer()
        return
    if data.startswith("upload_district:"):
        _, district, file_name = data.split(":", 2)
        file_path = context.user_data.get("file_path")
        if not file_path or not os.path.exists(file_path):
            await query.message.reply_text("Файл не найден, попробуйте загрузить снова.", reply_markup=default_reply_markup)
            await query.answer()
            return
        regions = FEDERAL_DISTRICTS.get(district, [])
        buttons = [[InlineKeyboardButton(region, callback_data=f"upload_region:{district}:{region}:{file_name}")] for region in regions]
        buttons.append([InlineKeyboardButton("Вернуться в главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.reply_text(f"Выберите регион в {district} для загрузки:", reply_markup=reply_markup)
        await query.answer()
        return
    if data.startswith("upload_region:"):
        _, district, region, file_name = data.split(":", 3)
        file_path = context.user_data.get("file_path")
        if not file_path or not os.path.exists(file_path):
            await query.message.reply_text("Файл не найден, попробуйте загрузить снова.", reply_markup=default_reply_markup)
            await query.answer()
            return
        yandex_path = f"/regions/{district}/{region}/{file_name}"
        if upload_to_yandex(file_path, yandex_path):
            await query.message.reply_text(f"Файл {file_name} успешно загружен в регион {region}.", reply_markup=default_reply_markup)
            os.remove(file_path)
            context.user_data.pop("file_path", None)
        else:
            await query.message.reply_text(f"Ошибка при загрузке файла {file_name}.", reply_markup=default_reply_markup)
        await query.answer()
        return
    if data.startswith("forget:"):
        fact_index = int(data.split(":", 1)[1])
        global KNOWLEDGE_BASE
        try:
            removed_fact = KNOWLEDGE_BASE.pop(fact_index)
            with open('knowledge_base.json', 'w', encoding='utf-8') as f:
                json.dump({"facts": KNOWLEDGE_BASE}, f, ensure_ascii=False, indent=2)
            await query.message.reply_text(f"Факт удалён: {removed_fact}", reply_markup=default_reply_markup)
            logger.info(f"Администратор {user_id} удалил факт: {removed_fact}")
        except Exception as e:
            await query.message.reply_text(f"Ошибка при удалении факта: {str(e)}", reply_markup=default_reply_markup)
            logger.error(f"Ошибка при удалении факта: {str(e)}")
        await query.answer()
        return
    await query.message.reply_text("Неизвестная команда.", reply_markup=default_reply_markup)
    await query.answer()

# Обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_input = update.message.text.strip()

    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Доступ запрещён.", reply_markup=default_reply_markup)
        return

    # Обработка админ-команд
    if user_id in ALLOWED_ADMINS and user_input.lower().startswith("adduser"):
        try:
            new_user_id = int(user_input.split()[1])
            if new_user_id not in ALLOWED_USERS:
                ALLOWED_USERS.append(new_user_id)
                save_allowed_users(ALLOWED_USERS)
                await update.message.reply_text(f"Пользователь {new_user_id} добавлен.", reply_markup=default_reply_markup)
                logger.info(f"Администратор {user_id} добавил пользователя {new_user_id}")
            else:
                await update.message.reply_text(f"Пользователь {new_user_id} уже в списке.", reply_markup=default_reply_markup)
        except (IndexError, ValueError):
            await update.message.reply_text("Укажите ID пользователя: adduser <ID>", reply_markup=default_reply_markup)
        return
    if user_id in ALLOWED_ADMINS and user_input.lower().startswith("deluser"):
        try:
            del_user_id = int(user_input.split()[1])
            if del_user_id in ALLOWED_USERS:
                ALLOWED_USERS.remove(del_user_id)
                save_allowed_users(ALLOWED_USERS)
                await update.message.reply_text(f"Пользователь {del_user_id} удалён.", reply_markup=default_reply_markup)
                logger.info(f"Администратор {user_id} удалил пользователя {del_user_id}")
            else:
                await update.message.reply_text(f"Пользователь {del_user_id} не найден.", reply_markup=default_reply_markup)
        except (IndexError, ValueError):
            await update.message.reply_text("Укажите ID пользователя: deluser <ID>", reply_markup=default_reply_markup)
        return
    if user_id in ALLOWED_ADMINS and user_input.lower() == "listusers":
        if not ALLOWED_USERS:
            await update.message.reply_text("Список пользователей пуст.", reply_markup=default_reply_markup)
            return
        users_list = "\n".join([f"ID: {uid}" for uid in ALLOWED_USERS])
        await update.message.reply_text(f"Пользователи:\n{users_list}", reply_markup=default_reply_markup)
        logger.info(f"Администратор {user_id} запросил список пользователей.")
        return
    if user_id in ALLOWED_ADMINS and user_input.lower() == "listadmins":
        if not ALLOWED_ADMINS:
            await update.message.reply_text("Список администраторов пуст.", reply_markup=default_reply_markup)
            return
        admins_list = "\n".join([f"ID: {uid}" for uid in ALLOWED_ADMINS])
        await update.message.reply_text(f"Администраторы:\n{admins_list}", reply_markup=default_reply_markup)
        logger.info(f"Администратор {user_id} запросил список администраторов.")
        return

    # Обработка текстового сообщения через API
    if chat_id not in histories:
        histories[chat_id] = {"name": None, "messages": [{"role": "system", "content": system_prompt}]}

    # Добавляем базу знаний в контекст
    if KNOWLEDGE_BASE:
        knowledge_text = "Известные факты для использования в ответах: " + "; ".join(KNOWLEDGE_BASE)
        histories[chat_id]["messages"].insert(1, {"role": "system", "content": knowledge_text})
        logger.info(f"Добавлены знания в контекст для user_id {user_id}: {len(KNOWLEDGE_BASE)} фактов")

    # Проверка необходимости веб-поиска
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
                extracted_text = "\n".join([f"Источник: {r.get('title', '')}\n{r.get('body', '')}" for r in results if r.get('body')])
            else:
                extracted_text = search_results_json
            histories[chat_id]["messages"].append({"role": "system", "content": f"Актуальные факты: {extracted_text}"})
            logger.info(f"Извлечено из поиска: {extracted_text[:200]}...")
        except json.JSONDecodeError:
            histories[chat_id]["messages"].append({"role": "system", "content": f"Ошибка поиска: {search_results_json}"})

    histories[chat_id]["messages"].append({"role": "user", "content": user_input})
    if len(histories[chat_id]["messages"]) > 20:
        histories[chat_id]["messages"] = histories[chat_id]["messages"][:1] + histories[chat_id]["messages"][-19:]

    messages = histories[chat_id]["messages"]

    # Запрос к API
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
    logger.info(f"Отправлен ответ пользователю {user_id}: {final_response[:200]}...")

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("Произошла ошибка, попробуйте позже.", reply_markup=default_reply_markup)

# Главная функция
def main() -> None:
    logger.info("Запуск Telegram бота...")
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