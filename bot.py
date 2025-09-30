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
    except json.JSONDecodeError:
        logger.error("Файл user_profiles.json повреждён, возвращается пустой словарь.")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке user_profiles.json: {str(e)}")
        return {}

def save_user_profiles(profiles: Dict[int, Dict[str, str]]) -> None:
    """Сохраняет профили пользователей в файл."""
    try:
        with open('user_profiles.json', 'w', encoding='utf-8') as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
            logger.info(f"Профили успешно сохранены: {profiles}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении user_profiles.json: {str(e)}")
        raise

# Функции для базы знаний
def load_knowledge_base() -> List[str]:
    """Загружает базу знаний из файла."""
    try:
        if not os.path.exists('knowledge_base.json'):
            logger.warning("Файл knowledge_base.json не найден, создаётся новый.")
            with open('knowledge_base.json', 'w', encoding='utf-8') as f:
                json.dump({"facts": []}, f, ensure_ascii=False)
        with open('knowledge_base.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            facts = data.get('facts', [])
            logger.info(f"Загружено {len(facts)} фактов из knowledge_base.json")
            return facts
    except json.JSONDecodeError:
        logger.error("Ошибка чтения knowledge_base.json.")
        return []
    except Exception as e:
        logger.error(f"Ошибка при загрузке knowledge_base.json: {str(e)}")
        return []

def add_knowledge(fact: str, facts: List[str]) -> List[str]:
    """Добавляет новый факт в список знаний."""
    if fact.strip() and fact not in facts:
        facts.append(fact.strip())
        logger.info(f"Добавлен факт: {fact}")
    return facts

def remove_knowledge(fact: str, facts: List[str]) -> List[str]:
    """Удаляет факт из списка знаний."""
    fact = fact.strip()
    if fact in facts:
        facts.remove(fact)
        logger.info(f"Факт удалён: {fact}")
    else:
        logger.warning(f"Факт не найден в базе знаний: {fact}")
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

# Инициализация глобальных переменных
ALLOWED_ADMINS = load_allowed_admins()
ALLOWED_USERS = load_allowed_users()
USER_PROFILES = load_user_profiles()
KNOWLEDGE_BASE = load_knowledge_base()

# Новый системный промпт для ИИ
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

# Функции для работы с Яндекс.Диском
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
    """Возвращает список элементов (файлов или директорий) в папке на Яндекс.Диске."""
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
    """Возвращает список имен поддиректорий в папке."""
    items = list_yandex_disk_items(folder_path, item_type='dir')
    return [item['name'] for item in items]

def list_yandex_disk_files(folder_path: str) -> List[Dict[str, str]]:
    """Возвращает список файлов в папке на Яндекс.Диске (с фильтром по расширениям)."""
    folder_path = folder_path.rstrip('/')
    items = list_yandex_disk_items(folder_path, item_type='file')
    supported_extensions = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')
    files = [item for item in items if item['name'].lower().endswith(supported_extensions)]
    logger.info(f"Найдено {len(files)} файлов в папке {folder_path}: {[item['name'] for item in files]}")
    return files

def get_yandex_disk_file(file_path: str) -> str | None:
    """Получает ссылку для скачивания файла с Яндекс.Диска."""
    file_path = file_path.rstrip('/')
    encoded_path = quote(file_path, safe='/')  # Улучшенное экранирование пути
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
                logger.error(
                    f"Ошибка загрузки файла {file_path}: код {upload_response.status_code}, ответ: {upload_response.text}")
                return False
            logger.error(f"Не получен URL для загрузки файла {file_path}")
            return False
        logger.error(
            f"Ошибка получения URL для загрузки {file_path}: код {response.status_code}, ответ: {response.text}")
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
        logger.error(f"Ошибка удаления файла {file_path}: код {response.status_code}, ответ: {response.text}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при удалении файла {file_path}: {str(e)}")
        return False

# Функция веб-поиска
def web_search(query: str) -> str:
    """Выполняет поиск в интернете и кэширует результаты."""
    cache_file = 'search_cache.json'
    try:
        if not os.path.exists(cache_file):
            logger.warning("Файл search_cache.json не найден, создаётся новый.")
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

# Обработчик команды /learn
async def handle_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команды /learn для добавления знаний."""
    user_id: int = update.effective_user.id
    if user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Только администраторы могут обучать бота.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /learn <факт>. Например: /learn Земля круглая.")
        return

    fact = ' '.join(context.args)
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE = add_knowledge(fact, KNOWLEDGE_BASE)
    save_knowledge_base(KNOWLEDGE_BASE)
    await update.message.reply_text(f"Факт добавлен: '{fact}'. Теперь бот использует его во всех ответах!")
    logger.info(f"Администратор {user_id} добавил факт: {fact}")

# Обработчик команды /forget
async def handle_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команды /forget для удаления факта из базы знаний."""
    user_id: int = update.effective_user.id
    if user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Только администраторы могут удалять факты.")
        logger.info(f"Пользователь {user_id} попытался использовать команду /forget.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /forget <факт>. Например: /forget Земля круглая.")
        return

    fact = ' '.join(context.args)
    global KNOWLEDGE_BASE
    if fact in KNOWLEDGE_BASE:
        KNOWLEDGE_BASE = remove_knowledge(fact, KNOWLEDGE_BASE)
        save_knowledge_base(KNOWLEDGE_BASE)
        await update.message.reply_text(f"Факт удалён: '{fact}'.")
        logger.info(f"Администратор {user_id} удалил факт: {fact}")
    else:
        await update.message.reply_text(f"Факт '{fact}' не найден в базе знаний.")
        logger.info(f"Администратор {user_id} пытался удалить несуществующий факт: {fact}")

# Обработчик команды /start
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команды /start: регистрация или главное меню."""
    if update.effective_user is None or update.effective_chat is None:
        logger.error("Ошибка: update.effective_user или update.effective_chat is None")
        await update.message.reply_text("Ошибка: не удалось определить пользователя или чат.")
        return

    user_id: int = update.effective_user.id
    chat_id: int = update.effective_chat.id

    # Очистка временных данных
    context.user_data.clear()

    # Проверка доступа
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        welcome_message = f"Ваш user_id: {user_id}\nИзвините, у вас нет доступа. Передайте user_id администратору."
        await update.message.reply_text(welcome_message, reply_markup=ReplyKeyboardRemove())
        logger.info(f"Пользователь {user_id} попытался получить доступ.")
        return

    # Проверка профиля
    if user_id not in USER_PROFILES:
        context.user_data["awaiting_fio"] = True
        welcome_message = "Доброго времени суток!\nДля начала работы напишите своё ФИО."
        await update.message.reply_text(welcome_message, reply_markup=ReplyKeyboardRemove())
        logger.info(f"Пользователь {chat_id} начал регистрацию.")
        return

    profile = USER_PROFILES[user_id]
    if profile.get("name") is None:
        context.user_data["awaiting_name"] = True
        await update.message.reply_text("Как я могу к Вам обращаться (кратко для удобства)?",
                                        reply_markup=ReplyKeyboardRemove())
    else:
        await show_main_menu(update, context)

# Отображение главного меню
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает главное меню с командами."""
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
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)

# Обработчик команды /getfile
async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команды /getfile: скачивание файла."""
    if update.effective_user is None or update.effective_chat is None:
        logger.error("Ошибка: update.effective_user или update.effective_chat is None")
        await update.message.reply_text("Ошибка: не удалось определить пользователя или чат.")
        return

    user_id: int = update.effective_user.id
    chat_id: int = update.effective_chat.id

    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Извините, у вас нет доступа.", reply_markup=ReplyKeyboardRemove())
        logger.info(f"Пользователь {user_id} попытался скачать файл.")
        return

    if user_id not in USER_PROFILES:
        await update.message.reply_text("Сначала пройдите регистрацию с /start.")
        return

    if not context.args:
        await update.message.reply_text("Укажите название файла (например, file.pdf).")
        return

    file_name = ' '.join(context.args).strip()
    await search_and_send_file(update, context, file_name)

# Поиск и отправка файла из региона
async def search_and_send_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_name: str) -> None:
    """Ищет и отправляет файл с Яндекс.Диска из региональной папки."""
    user_id: int = update.effective_user.id
    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        await update.message.reply_text("Ошибка: регион не определён. Перезапустите /start.")
        logger.error(f"Ошибка: регион не определён для пользователя {user_id}.")
        return

    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        await update.message.reply_text("Ошибка: не удалось проверить или создать папку региона.")
        logger.error(f"Не удалось создать папку {region_folder} для пользователя {user_id}.")
        return

    if not file_name.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')):
        await update.message.reply_text("Поддерживаются только файлы .pdf, .doc, .docx, .xls, .xlsx, .cdr, .eps, .png, .jpg, .jpeg.")
        logger.error(f"Неподдерживаемый формат файла {file_name} для пользователя {user_id}.")
        return

    files = list_yandex_disk_files(region_folder)
    matching_file = next((item for item in files if item['name'].lower() == file_name.lower()), None)

    if not matching_file:
        await update.message.reply_text(f"Файл '{file_name}' не найден в папке {region_folder}.")
        logger.info(f"Файл '{file_name}' не найден для пользователя {user_id}.")
        return

    file_path = matching_file['path']
    download_url = get_yandex_disk_file(file_path)
    if not download_url:
        await update.message.reply_text("Ошибка: не удалось получить ссылку для скачивания.")
        logger.error(f"Не удалось получить ссылку для файла {file_path}.")
        return

    try:
        file_response = requests.get(download_url)
        if file_response.status_code == 200:
            file_size = len(file_response.content) / (1024 * 1024)
            if file_size > 20:
                await update.message.reply_text("Файл слишком большой (>20 МБ).")
                logger.error(f"Файл {file_name} слишком большой: {file_size} МБ")
                return
            await update.message.reply_document(
                document=InputFile(file_response.content, filename=file_name)
            )
            logger.info(f"Файл {file_name} отправлен пользователю {user_id}.")
        else:
            await update.message.reply_text("Не удалось загрузить файл с Яндекс.Диска.")
            logger.error(
                f"Ошибка загрузки файла {file_path}: код {file_response.status_code}, ответ: {file_response.text}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при отправке файла: {str(e)}")
        logger.error(f"Ошибка при отправке файла {file_path}: {str(e)}")

# Обработка загруженных документов
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка загруженных документов."""
    user_id: int = update.effective_user.id
    if not context.user_data.get('awaiting_upload', False):
        await update.message.reply_text("Используйте кнопку 'Загрузить файл' перед отправкой документа.")
        return

    document = update.message.document
    file_name = document.file_name
    if not file_name.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')):
        await update.message.reply_text("Поддерживаются только файлы .pdf, .doc, .docx, .xls, .xlsx, .cdr, .eps, .png, .jpg, .jpeg.")
        return

    file_size = document.file_size / (1024 * 1024)
    if file_size > 50:
        await update.message.reply_text("Файл слишком большой (>50 МБ).")
        return

    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        await update.message.reply_text("Ошибка: регион не определён. Обновите профиль с /start.")
        return
    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        await update.message.reply_text("Ошибка: не удалось создать папку региона.")
        logger.error(f"Не удалось создать папку {region_folder} для пользователя {user_id}.")
        return

    try:
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        if upload_to_yandex_disk(file_content, file_name, region_folder):
            await update.message.reply_text(f"Файл успешно загружен в папку {region_folder}")
        else:
            await update.message.reply_text("Ошибка при загрузке файла на Яндекс.Диск.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при обработке файла: {str(e)}")
        logger.error(f"Ошибка обработки документа от {user_id}: {str(e)}")

    context.user_data.pop('awaiting_upload', None)
    logger.info(f"Пользователь {user_id} загрузил файл {file_name} в {region_folder}.")

# Отображение списка файлов (для регионов)
async def show_file_list(update: Update, context: ContextTypes.DEFAULT_TYPE, for_deletion: bool = False) -> None:
    """Показывает список файлов в папке региона."""
    user_id: int = update.effective_user.id
    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        await update.message.reply_text("Ошибка: регион не определён. Обновите профиль с /start.",
                                        reply_markup=context.user_data.get('default_reply_markup',
                                                                           ReplyKeyboardRemove()))
        logger.error(f"Ошибка: регион не определён для пользователя {user_id}.")
        return

    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        await update.message.reply_text("Ошибка: не удалось создать папку региона.")
        logger.error(f"Не удалось создать папку {region_folder} для пользователя {user_id}.")
        return

    files = list_yandex_disk_files(region_folder)
    if not files:
        await update.message.reply_text(f"В папке {region_folder} нет файлов.",
                                        reply_markup=context.user_data.get('default_reply_markup',
                                                                           ReplyKeyboardRemove()))
        logger.info(f"Папка {region_folder} пуста для пользователя {user_id}.")
        return

    # Сохраняем список файлов в context.user_data
    context.user_data['file_list'] = files
    keyboard = []
    for idx, item in enumerate(files):
        action = 'delete' if for_deletion else 'download'
        callback_data = f"{action}:{idx}"
        keyboard.append([InlineKeyboardButton(item['name'], callback_data=callback_data)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    action_text = "Выберите файл для удаления:" if for_deletion else "Список всех файлов:"
    await update.message.reply_text(action_text, reply_markup=reply_markup)
    logger.info(f"Пользователь {user_id} запросил список файлов в {region_folder}: {[item['name'] for item in files]}")

# Отображение содержимого текущей папки в /documents/
async def show_current_docs(update: Update, context: ContextTypes.DEFAULT_TYPE, is_return: bool = False) -> None:
    """Показывает файлы и/или поддиректории в текущей папке в /documents/."""
    user_id: int = update.effective_user.id
    context.user_data.pop('file_list', None)
    current_path = context.user_data.get('current_path', '/documents/')
    folder_name = current_path.rstrip('/').split('/')[-1] or "Документы"
    if not create_yandex_folder(current_path):
        await update.message.reply_text(f"Ошибка: не удалось создать папку {current_path}.",
                                        reply_markup=context.user_data.get('default_reply_markup',
                                                                           ReplyKeyboardRemove()))
        logger.error(f"Не удалось создать папку {current_path} для пользователя {user_id}.")
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
        await update.message.reply_text(f"Файлы в папке {folder_name}:", reply_markup=file_reply_markup)
        logger.info(
            f"Пользователь {user_id} получил список файлов в {current_path}: {[item['name'] for item in files]}")
    elif dirs:
        if not is_return:
            message = "Документы для РО" if current_path == '/documents/' else f"Папки в {folder_name}:"
            await update.message.reply_text(message, reply_markup=reply_markup)
        logger.info(f"Пользователь {user_id} получил список подпапок в {current_path}: {dirs}")
    else:
        await update.message.reply_text(f"Папка {folder_name} пуста.", reply_markup=reply_markup)
        logger.info(f"Папка {current_path} пуста для пользователя {user_id}.")

# Обработка callback-запросов
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка кнопок для скачивания/удаления файлов."""
    query = update.callback_query
    await query.answer()

    user_id: int = update.effective_user.id
    profile = USER_PROFILES.get(user_id)
    default_reply_markup = context.user_data.get('default_reply_markup', ReplyKeyboardRemove())

    if not query.message:
        logger.error(f"Ошибка: query.message is None для user_id {user_id}")
        await query.message.reply_text("Ошибка: сообщение недоступно.", reply_markup=default_reply_markup)
        return

    if not profile or "region" not in profile:
        await query.message.reply_text("Ошибка: регион не определён. Перезапустите /start.",
                                       reply_markup=default_reply_markup)
        logger.error(f"Ошибка: регион не определён для пользователя {user_id}.")
        return

    region_folder = f"/regions/{profile['region']}/"
    if not create_yandex_folder(region_folder):
        await query.message.reply_text("Ошибка: не удалось создать папку региона.", reply_markup=default_reply_markup)
        logger.error(f"Не удалось создать папку {region_folder} для пользователя {user_id}.")
        return

    if query.data.startswith("doc_download:"):
        parts = query.data.split(":", 1)
        if len(parts) != 2:
            await query.message.reply_text("Ошибка: неверный формат запроса.", reply_markup=default_reply_markup)
            logger.error(f"Неверный формат callback_data: {query.data}")
            return
        try:
            file_idx = int(parts[1])
        except ValueError:
            await query.message.reply_text("Ошибка: неверный индекс файла.", reply_markup=default_reply_markup)
            logger.error(f"Неверный индекс в callback_data: {query.data}")
            return
        current_path = context.user_data.get('current_path', '/documents/')
        files = context.user_data.get('file_list', [])
        if not files:
            files = list_yandex_disk_files(current_path)
            context.user_data['file_list'] = files
            logger.info(f"Перезагружен file_list для {current_path}: {[item['name'] for item in files]}")
        if not files or file_idx >= len(files):
            await query.message.reply_text("Ошибка: файл не найден. Попробуйте обновить список.",
                                           reply_markup=default_reply_markup)
            logger.error(
                f"Файл с индексом {file_idx} не найден в file_list для user_id {user_id}, file_list: {[item['name'] for item in files]}")
            return
        file_name = files[file_idx]['name']
        file_path = f"{current_path.rstrip('/')}/{file_name}"
        download_url = get_yandex_disk_file(file_path)
        if not download_url:
            await query.message.reply_text("Ошибка: не удалось получить ссылку для скачивания.",
                                           reply_markup=default_reply_markup)
            logger.error(f"Не удалось получить ссылку для файла {file_path}.")
            return

        try:
            file_response = requests.get(download_url)
            if file_response.status_code == 200:
                file_size = len(file_response.content) / (1024 * 1024)
                if file_size > 20:
                    await query.message.reply_text("Файл слишком большой (>20 МБ).", reply_markup=default_reply_markup)
                    logger.error(f"Файл {file_name} слишком большой: {file_size} МБ")
                    return
                await query.message.reply_document(
                    document=InputFile(file_response.content, filename=file_name)
                )
                logger.info(f"Файл {file_name} из {current_path} отправлен пользователю {user_id}.")
            else:
                await query.message.reply_text("Не удалось загрузить файл с Яндекс.Диска.",
                                               reply_markup=default_reply_markup)
                logger.error(
                    f"Ошибка загрузки файла {file_path}: код {file_response.status_code}, ответ: {file_response.text}")
        except Exception as e:
            await query.message.reply_text(f"Ошибка при отправке файла: {str(e)}", reply_markup=default_reply_markup)
            logger.error(f"Ошибка при отправке файла {file_path}: {str(e)}")
        return

    if query.data.startswith("download:") or query.data.startswith("delete:"):
        action, file_idx_str = query.data.split(":", 1)
        try:
            file_idx = int(file_idx_str)
        except ValueError:
            await query.message.reply_text("Ошибка: неверный индекс файла.", reply_markup=default_reply_markup)
            logger.error(f"Неверный индекс в callback_data: {query.data}")
            return

        files = context.user_data.get('file_list', [])
        if not files:
            files = list_yandex_disk_files(region_folder)
            context.user_data['file_list'] = files
            logger.info(f"Перезагружен file_list для {region_folder}: {[item['name'] for item in files]}")
        if not files or file_idx >= len(files):
            await query.message.reply_text("Ошибка: файл не найден. Попробуйте обновить список.",
                                           reply_markup=default_reply_markup)
            logger.error(
                f"Файл с индексом {file_idx} не найден в file_list для user_id {user_id}, file_list: {[item['name'] for item in files]}")
            return

        file_name = files[file_idx]['name']
        file_path = f"{region_folder.rstrip('/')}/{file_name}"

        if action == "download":
            if not file_name.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.cdr', '.eps', '.png', '.jpg', '.jpeg')):
                await query.message.reply_text("Поддерживаются только файлы .pdf, .doc, .docx, .xls, .xlsx, .cdr, .eps, .png, .jpg, .jpeg.",
                                               reply_markup=default_reply_markup)
                logger.error(f"Неподдерживаемый формат файла {file_name} для пользователя {user_id}.")
                return

            download_url = get_yandex_disk_file(file_path)
            if not download_url:
                await query.message.reply_text("Ошибка: не удалось получить ссылку для скачивания.",
                                               reply_markup=default_reply_markup)
                logger.error(f"Не удалось получить ссылку для файла {file_path}.")
                return

            try:
                file_response = requests.get(download_url)
                if file_response.status_code == 200:
                    file_size = len(file_response.content) / (1024 * 1024)
                    if file_size > 20:
                        await query.message.reply_text("Файл слишком большой (>20 МБ).",
                                                       reply_markup=default_reply_markup)
                        logger.error(f"Файл {file_name} слишком большой: {file_size} МБ")
                        return
                    await query.message.reply_document(
                        document=InputFile(file_response.content, filename=file_name)
                    )
                    logger.info(f"Файл {file_name} отправлен пользователю {user_id}.")
                else:
                    await query.message.reply_text("Не удалось загрузить файл с Яндекс.Диска.",
                                                   reply_markup=default_reply_markup)
                    logger.error(
                        f"Ошибка загрузки файла {file_path}: код {file_response.status_code}, ответ: {file_response.text}")
            except Exception as e:
                await query.message.reply_text(f"Ошибка при отправке файла: {str(e)}",
                                               reply_markup=default_reply_markup)
                logger.error(f"Ошибка при отправке файла {file_path}: {str(e)}")

        elif action == "delete":
            if user_id not in ALLOWED_ADMINS:
                await query.message.reply_text("Только администраторы могут удалять файлы.",
                                               reply_markup=default_reply_markup)
                logger.info(f"Пользователь {user_id} попытался удалить файл.")
                return

            if delete_yandex_disk_file(file_path):
                await query.message.reply_text(f"Файл '{file_name}' удалён из папки {region_folder}.",
                                               reply_markup=default_reply_markup)
                logger.info(f"Администратор {user_id} удалил файл {file_name}.")
            else:
                await query.message.reply_text(f"Ошибка при удалении файла '{file_name}'.",
                                               reply_markup=default_reply_markup)
                logger.error(f"Ошибка при удалении файла {file_name} для пользователя {user_id}.")

            # Обновляем список файлов после удаления
            context.user_data.pop('file_list', None)
            await show_file_list(update, context, for_deletion=True)

# Вспомогательная функция для отображения главного меню через callback_query
async def show_main_menu_with_query(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает главное меню через callback_query."""
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
    await query.message.reply_text("Выберите действие:", reply_markup=reply_markup)

# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений: регистрация, команды, поиск."""
    if update.effective_user is None or update.effective_chat is None:
        logger.error("Ошибка: update.effective_user или update.effective_chat is None")
        await update.message.reply_text("Ошибка: не удалось определить пользователя или чат.")
        return

    user_id: int = update.effective_user.id
    chat_id: int = update.effective_chat.id
    user_input: str = update.message.text.strip()
    logger.info(f"Получено сообщение от {chat_id} (user_id: {user_id}): {user_input}")

    # Проверка доступа
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text("Извините, у вас нет доступа.", reply_markup=ReplyKeyboardRemove())
        logger.info(f"Пользователь {user_id} попытался отправить сообщение.")
        return

    # Проверка профиля и регистрация
    if user_id not in USER_PROFILES:
        if context.user_data.get("awaiting_fio", False):
            logger.info(f"Сохранение ФИО для user_id {user_id}: {user_input}")
            USER_PROFILES[user_id] = {"fio": user_input, "name": None, "region": None}
            try:
                save_user_profiles(USER_PROFILES)
            except Exception as e:
                await update.message.reply_text("Ошибка при сохранении профиля. Попробуйте снова.")
                logger.error(f"Ошибка при сохранении профиля для user_id {user_id}: {str(e)}")
                return
            context.user_data["awaiting_fio"] = False
            context.user_data["awaiting_federal_district"] = True
            keyboard = [[district] for district in FEDERAL_DISTRICTS.keys()]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text("Выберите федеральный округ:", reply_markup=reply_markup)
            return
        else:
            await update.message.reply_text("Сначала пройдите регистрацию с /start.")
            return

    # Определение клавиатуры
    admin_keyboard = [
        ['Управление пользователями', 'Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ] if user_id in ALLOWED_ADMINS else [
        ['Загрузить файл'],
        ['Архив документов РО', 'Документы для РО']
    ]
    default_reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)

    # Обработка выбора федерального округа
    if context.user_data.get("awaiting_federal_district", False):
        if user_input in FEDERAL_DISTRICTS:
            context.user_data["selected_federal_district"] = user_input
            context.user_data["awaiting_federal_district"] = False
            context.user_data["awaiting_region"] = True
            regions = FEDERAL_DISTRICTS[user_input]
            keyboard = [[region] for region in regions]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text("Выберите регион:", reply_markup=reply_markup)
            return
        else:
            await update.message.reply_text("Пожалуйста, выберите из предложенных округов.",
                                            reply_markup=ReplyKeyboardMarkup(
                                                [[district] for district in FEDERAL_DISTRICTS.keys()],
                                                resize_keyboard=True))
            return

    # Обработка выбора региона
    if context.user_data.get("awaiting_region", False):
        selected_district = context.user_data.get("selected_federal_district")
        regions = FEDERAL_DISTRICTS.get(selected_district, [])
        if user_input in regions:
            logger.info(f"Сохранение региона для user_id {user_id}: {user_input}")
            USER_PROFILES[user_id]["region"] = user_input
            try:
                save_user_profiles(USER_PROFILES)
            except Exception as e:
                await update.message.reply_text("Ошибка при сохранении региона. Попробуйте снова.")
                logger.error(f"Ошибка при сохранении региона для user_id {user_id}: {str(e)}")
                return
            region_folder = f"/regions/{user_input}/"
            if not create_yandex_folder(region_folder):
                await update.message.reply_text("Ошибка: не удалось создать папку региона.")
                logger.error(f"Не удалось создать папку {region_folder} для пользователя {user_id}.")
                return
            context.user_data.pop("awaiting_region", None)
            context.user_data.pop("selected_federal_district", None)
            context.user_data["awaiting_name"] = True
            await update.message.reply_text("Как я могу к Вам обращаться (кратко для удобства)?",
                                            reply_markup=ReplyKeyboardRemove())
            logger.info(f"Пользователь {user_id} зарегистрирован с регионом {user_input}.")
            return
        else:
            await update.message.reply_text("Пожалуйста, выберите из предложенных регионов.",
                                            reply_markup=ReplyKeyboardMarkup([[region] for region in regions],
                                                                             resize_keyboard=True))
            return

    # Обработка ввода имени
    if context.user_data.get("awaiting_name", False):
        logger.info(f"Сохранение имени для user_id {user_id}: {user_input}")
        profile = USER_PROFILES[user_id]
        profile["name"] = user_input
        try:
            save_user_profiles(USER_PROFILES)
        except Exception as e:
            await update.message.reply_text("Ошибка при сохранении имени. Попробуйте снова.")
            logger.error(f"Ошибка при сохранении имени для user_id {user_id}: {str(e)}")
            return
        context.user_data["awaiting_name"] = False
        await show_main_menu(update, context)
        reply_markup = context.user_data.get('default_reply_markup', ReplyKeyboardRemove())
        await update.message.reply_text(
            f"Рад знакомству, {user_input}! Задавайте вопросы или используйте меню.",
            reply_markup=reply_markup
        )
        logger.info(f"Имя пользователя {chat_id} сохранено: {user_input}")
        return

    handled = False

    # Обработка команд меню
    if user_input == "Документы для РО":
        context.user_data['current_mode'] = 'documents_nav'
        context.user_data['current_path'] = '/documents/'
        context.user_data.pop('file_list', None)
        if not create_yandex_folder('/documents/'):
            await update.message.reply_text("Ошибка: не удалось создать папку /documents/.")
            logger.error(f"Не удалось создать папку /documents/ для пользователя {user_id}.")
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
            await update.message.reply_text("Только администраторы могут управлять пользователями.",
                                            reply_markup=default_reply_markup)
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
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
        logger.info(f"Администратор {user_id} запросил управление пользователями.")
        handled = True

    if user_input == "Загрузить файл":
        profile = USER_PROFILES.get(user_id)
        if not profile or "region" not in profile:
            await update.message.reply_text("Ошибка: регион не определён. Обновите профиль с /start.",
                                            reply_markup=default_reply_markup)
            return
        context.user_data.pop('current_mode', None)
        context.user_data.pop('current_path', None)
        context.user_data.pop('file_list', None)
        await update.message.reply_text(
            "Отправьте файл для загрузки.",
            reply_markup=default_reply_markup
        )
        context.user_data['awaiting_upload'] = True
        logger.info(f"Пользователь {user_id} начал загрузку файла.")
        handled = True

    if user_input == "Удалить файл":
        if user_id not in ALLOWED_ADMINS:
            await update.message.reply_text("Только администраторы могут удалять файлы.",
                                            reply_markup=default_reply_markup)
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
        handled = True

    # Обработка навигации по documents
    if context.user_data.get('current_mode') == 'documents_nav':
        current_path = context.user_data.get('current_path', '/documents/')
        logger.info(f"Пользователь {user_id} пытается перейти в папку: {user_input}, текущий путь: {current_path}")
        dirs = list_yandex_disk_directories(current_path)
        if user_input in dirs:
            context.user_data.pop('file_list', None)
            context.user_data['current_path'] = f"{current_path.rstrip('/')}/{user_input}/"
            logger.info(f"Пользователь {user_id} перешёл в папку: {context.user_data['current_path']}")
            if not create_yandex_folder(context.user_data['current_path']):
                await update.message.reply_text(
                    f"Ошибка: не удалось создать папку {context.user_data['current_path']}.",
                    reply_markup=default_reply_markup)
                logger.error(
                    f"Не удалось создать папку {context.user_data['current_path']} для пользователя {user_id}.")
                return
            await show_current_docs(update, context)
            handled = True
        elif user_input == 'В главное меню':
            logger.info(f"Пользователь {user_id} вернулся в главное меню из {current_path}")
            await show_main_menu(update, context)
            handled = True
        elif user_input == 'Назад' and current_path != '/documents/':
            context.user_data.pop('file_list', None)
            parts = current_path.rstrip('/').split('/')
            new_path = '/'.join(parts[:-1]) + '/' if len(parts) > 2 else '/documents/'
            context.user_data['current_path'] = new_path
            logger.info(f"Пользователь {user_id} вернулся назад в {new_path}")
            await show_current_docs(update, context, is_return=True)
            handled = True

    if context.user_data.get('awaiting_user_id'):
        try:
            new_id = int(user_input)
            if context.user_data['awaiting_user_id'] == 'add_user':
                if new_id in ALLOWED_USERS:
                    await update.message.reply_text(f"Пользователь с ID {new_id} уже имеет доступ.",
                                                    reply_markup=default_reply_markup)
                    return
                ALLOWED_USERS.append(new_id)
                save_allowed_users(ALLOWED_USERS)
                await update.message.reply_text(f"Пользователь с ID {new_id} добавлен!",
                                                reply_markup=default_reply_markup)
                logger.info(f"Администратор {user_id} добавил пользователя {new_id}.")
            elif context.user_data['awaiting_user_id'] == 'add_admin':
                if new_id in ALLOWED_ADMINS:
                    await update.message.reply_text(f"Пользователь с ID {new_id} уже администратор.",
                                                    reply_markup=default_reply_markup)
                    return
                ALLOWED_ADMINS.append(new_id)
                save_allowed_admins(ALLOWED_ADMINS)
                await update.message.reply_text(f"Пользователь с ID {new_id} назначен администратором!",
                                                reply_markup=default_reply_markup)
                logger.info(f"Администратор {user_id} назначил администратора {new_id}.")
            context.user_data.pop('awaiting_user_id', None)
            handled = True
        except ValueError:
            await update.message.reply_text("Ошибка: user_id должен быть числом.", reply_markup=default_reply_markup)
            logger.error(f"Ошибка: Неверный формат user_id от {user_id}.")
            handled = True

    if user_input == "Добавить пользователя":
        if user_id not in ALLOWED_ADMINS:
            await update.message.reply_text("Только администраторы могут добавлять пользователей.",
                                            reply_markup=default_reply_markup)
            logger.info(f"Пользователь {user_id} попытался добавить пользователя.")
            return
        await update.message.reply_text("Укажите user_id для добавления.",
                                        reply_markup=default_reply_markup)
        context.user_data['awaiting_user_id'] = 'add_user'
        logger.info(f"Администратор {user_id} запросил добавление пользователя.")
        handled = True

    if user_input == "Добавить администратора":
        if user_id not in ALLOWED_ADMINS:
            await update.message.reply_text("Только администраторы могут назначать администраторов.",
                                            reply_markup=default_reply_markup)
            logger.info(f"Пользователь {user_id} попытался добавить администратора.")
            return
        await update.message.reply_text("Укажите user_id для назначения администратором.",
                                        reply_markup=default_reply_markup)
        context.user_data['awaiting_user_id'] = 'add_admin'
        logger.info(f"Администратор {user_id} запросил добавление администратора.")
        handled = True

    if user_input == "Список пользователей":
        if user_id not in ALLOWED_ADMINS:
            await update.message.reply_text("Только администраторы могут просматривать список пользователей.",
                                            reply_markup=default_reply_markup)
            logger.info(f"Пользователь {user_id} попытался просмотреть список пользователей.")
            return
        if not ALLOWED_USERS:
            await update.message.reply_text("Список пользователей пуст.", reply_markup=default_reply_markup)
            return
        users_list = "\n".join([f"ID: {uid}" for uid in ALLOWED_USERS])
        await update.message.reply_text(f"Разрешённые пользователи:\n{users_list}", reply_markup=default_reply_markup)
        logger.info(f"Администратор {user_id} запросил список пользователей.")
        handled = True

    if user_input == "Список администраторов":
        if user_id not in ALLOWED_ADMINS:
            await update.message.reply_text("Только администраторы могут просматривать список администраторов.",
                                            reply_markup=default_reply_markup)
            logger.info(f"Пользователь {user_id} попытался просмотреть список администраторов.")
            return
        if not ALLOWED_ADMINS:
            await update.message.reply_text("Список администраторов пуст.", reply_markup=default_reply_markup)
            return
        admins_list = "\n".join([f"ID: {uid}" for uid in ALLOWED_ADMINS])
        await update.message.reply_text(f"Администраторы:\n{admins_list}", reply_markup=default_reply_markup)
        logger.info(f"Администратор {user_id} запросил список администраторов.")
        handled = True

    # Если сообщение не было обработано как специальная команда или состояние, обрабатываем как запрос к AI
    if not handled:
        # Обработка текстового сообщения через API
        if chat_id not in histories:
            histories[chat_id] = {"name": None, "messages": [{"role": "system", "content": system_prompt}]}

        # Добавляем базу знаний в контекст для всех пользователей
        global KNOWLEDGE_BASE
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

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ошибок бота."""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("Произошла ошибка, попробуйте позже.")

# Главная функция
def main() -> None:
    """Запуск бота."""
    logger.info("Запуск Telegram бота...")
    # Создание корневых папок
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