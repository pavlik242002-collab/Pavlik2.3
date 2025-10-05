from __future__ import annotations

import os
import logging
import requests
import json
from typing import Dict, List, Any
from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram import InputFile
from urllib.parse import quote
from openai import OpenAI
import psycopg2
from duckduckgo_search import DDGS

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
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3")

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


# Инициализация таблиц в PostgreSQL
def init_db(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'allowed_admins'
                );
            """)
            if not cur.fetchone()[0]:
                cur.execute("""
                    CREATE TABLE allowed_admins (
                        id BIGINT NOT NULL PRIMARY KEY
                    );
                    INSERT INTO allowed_admins (id) VALUES (6909708460) ON CONFLICT DO NOTHING;
                """)
                logger.info("Таблица allowed_admins создана.")
            else:
                logger.info("Таблица allowed_admins уже существует.")

            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'allowed_users'
                );
            """)
            if not cur.fetchone()[0]:
                cur.execute("""
                    CREATE TABLE allowed_users (
                        id BIGINT NOT NULL PRIMARY KEY
                    );
                """)
                logger.info("Таблица allowed_users создана.")
            else:
                logger.info("Таблица allowed_users уже существует.")

            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'user_profiles'
                );
            """)
            if not cur.fetchone()[0]:
                cur.execute("""
                    CREATE TABLE user_profiles (
                        user_id BIGINT NOT NULL PRIMARY KEY,
                        fio TEXT,
                        name TEXT,
                        region TEXT
                    );
                """)
                logger.info("Таблица user_profiles создана.")
            else:
                logger.info("Таблица user_profiles уже существует.")

            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'request_logs'
                );
            """)
            if not cur.fetchone()[0]:
                cur.execute("""
                    CREATE TABLE request_logs (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        request_text TEXT NOT NULL,
                        response_text TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                logger.info("Таблица request_logs создана.")
            else:
                logger.info("Таблица request_logs уже существует.")

            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'knowledge_base'
                );
            """)
            if not cur.fetchone()[0]:
                cur.execute("""
                    CREATE TABLE knowledge_base (
                        id SERIAL PRIMARY KEY,
                        fact_text TEXT NOT NULL,
                        added_by BIGINT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                initial_facts = [
                    ("Привет! Чем могу помочь?", 6909708460),
                    ("Документы по награждениям находятся в папке /documents/Награждения.", 6909708460),
                    ("Всё отлично, спасибо за вопрос!", 6909708460),
                    ("ВСКС - Всероссийский студенческий корпус спасателей, основанный 22 апреля 2001 года. Организация объединяет свыше 8 000 добровольцев из 88 субъектов России, которые участвуют в ликвидации последствий чрезвычайных ситуаций, таких как пожары и наводнения, а также проводят гуманитарные миссии.",
                     6909708460),
                    ("Козеев Евгений Викторович - Руководитель ВСКС", 6909708460),
                    ("Гуманитарные миссии - Всероссийский студенческий корпус спасателей (ВСКС) проводит гуманитарные миссии по нескольким направлениям: Ростовская область, Курская область, Запорожская область, Херсонская область, Донецкая Народная Республика, Луганская Народная Республика. Гуманитарные миссии проводятся 2 раза в месяц, каждые 1-15 и 15-30 числа месяца. Условия: проживание, питание и проезд за счёт ВСКС и партнёров. Заявки для участия можно подать через @kristina_pavlik.",
                     6909708460),
                    ("ЧС в которых ВСКС принимал участие - Добровольцы ВСКС приняли участие в ликвидации свыше 50 крупных чрезвычайных ситуаций и их последствий. Студенты-спасатели участвовали в ликвидации последствий лесных пожаров в Центральном федеральном округе, Тюменской области, Красноярском и Забайкальском краях; наводнений в Иркутской, Оренбургской, Курганской областях, Краснодарском и Алтайском краях, на Дальнем Востоке, в Республике Крым; степных пожаров в Забайкальском крае, ликвидации последствий разлива нефтепродуктов в Чёрное море и других ЧС. Добровольцы также помогают в ликвидации ЧС и их последствий на региональном уровне.",
                     6909708460),
                    ("В ВСКС - Свыше 8 000 добровольцев из 88 субъектов Российской Федерации.", 6909708460),
                    ("ВСКС основан - 22 апреля 2001 года по инициативе министра МЧС России того времени Сергея Кужугетовича Шойгу.",
                     6909708460),
                    ("Багаутдинов Ахмет Айратович - Начальник отдела регионального взаимодействия ЦУ ВСКС, координирует работу отдела, контакт: @baa_msk.",
                     6909708460),
                    ("Павлик Кристина Валентиновна - Заместитель начальника отдела регионального взаимодействия ЦУ ВСКС, занимается набором добровольцев на гуманитарные миссии ВСКС и ликвидации последствий ЧС, контакт: @kristina_pavlik.",
                     6909708460),
                    ("Кременецкая Галина Сергеевна - Сотрудник отдела регионального взаимодействия ЦУ ВСКС, занимается набором добровольцев из региональных отделений ВСКС на обучение по первоначальной подготовке спасателей на базе Всероссийского центра координации, подготовки и переподготовки студенческих добровольных спасательных формирований (ВЦПСФ), контакт: @ikremenetskaya.",
                     6909708460),
                    ("Локтионова Дарья Петровна - Сотрудник отдела регионального взаимодействия ЦУ ВСКС, занимается обработкой служебных записок региональных отделений ВСКС по выдаче форменной одежды, контакт: @otoorukun.",
                     6909708460),
                    ("Форум ВСКС - Всероссийский форум волонтёров безопасности.", 6909708460),
                    ("Слёт ВСКС - Всероссийский слёт студентов-спасателей и добровольцев в ЧС, V Всероссийский слёт студентов-спасателей и добровольцев в ЧС пройдёт с 30 сентября по 5 октября 2025 года на территории учебно-тренировочного полигона пожарных и спасателей в Московской области.",
                     6909708460),
                    ("Андреев Алексей Евгеньевич - Заместитель руководителя ВСКС по развитию региональных отделений ВСКС и взаимодействию с ними.",
                     6909708460)
                ]
                for fact, admin_id in initial_facts:
                    cur.execute("""
                        INSERT INTO knowledge_base (fact_text, added_by) VALUES (%s, %s) ON CONFLICT DO NOTHING
                    """, (fact, admin_id))
                logger.info("Таблица knowledge_base создана с начальными фактами.")
            else:
                logger.info("Таблица knowledge_base уже существует.")

            conn.commit()
            logger.info("Все таблицы проверены и созданы при необходимости.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {str(e)}")
        conn.rollback()
        raise


init_db(conn)

# Словарь федеральных округов
FEDERAL_DISTRICTS = {
    "Центральный федеральный округ": [
        "Москва", "Белгородская область", "Брянская область", "Владимирская область", "Воронежская область",
        "Ивановская область", "Калужская область", "Костромская область", "Курская область",
        "Липецкая область", "Московская область", "Орловская область", "Рязанская область",
        "Смоленская область", "Тамбовская область", "Тверская область", "Тульская область",
        "Ярославская область"
    ],
    "Северо-Западный федеральный округ": [
        "Республика Карелия", "Республика Коми", "Архангельская область", "Вологодская область",
        "Ленинградская область", "Мурманская область", "Новгородская область", "Псковская область",
        "Калининградская область", "Ненецкий автономный округ", "Санкт-Петербург"
    ],
    "Южный федеральный округ": [
        "Республика Адыгея", "Республика Калмыкия", "Республика Крым", "Краснодарский край",
        "Астраханская область", "Волгоградская область", "Ростовская область", "Севастополь",
        "Донецкая Народная Республика", "Луганская Народная Республика", "Запорожская область", "Херсонская область"
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
        "Омская область", "Томская область"
    ],
    "Дальневосточный федеральный округ": [
        "Республика Бурятия", "Республика Саха (Якутия)", "Забайкальский край", "Камчатский край",
        "Приморский край", "Хабаровский край", "Амурская область", "Магаданская область",
        "Сахалинская область", "Еврейская автономная область", "Чукотский автономный округ"
    ]
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


def delete_allowed_user(user_id_to_delete: int, admin_id: int) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM allowed_users WHERE id = %s", (user_id_to_delete,))
            if cur.rowcount > 0:
                conn.commit()
                logger.info(f"Пользователь с ID {user_id_to_delete} удален администратором {admin_id}")
                return True
            else:
                logger.warning(
                    f"Пользователь с ID {user_id_to_delete} не найден для удаления администратором {admin_id}")
                return False
    except Exception as e:
        logger.error(f"Ошибка при удалении пользователя с ID {user_id_to_delete}: {str(e)}")
        conn.rollback()
        return False


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


# Функции для работы с базой знаний в Postgres
def load_knowledge_base() -> List[Dict[str, Any]]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, fact_text FROM knowledge_base ORDER BY timestamp DESC")
            facts = [{"id": row[0], "text": row[1]} for row in cur.fetchall()]
            logger.info(f"Загружено {len(facts)} фактов из таблицы knowledge_base")
            return facts
    except Exception as e:
        logger.error(f"Ошибка при загрузке knowledge_base: {str(e)}")
        conn.rollback()
        return []


def save_knowledge_fact(fact: str, added_by: int) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO knowledge_base (fact_text, added_by) VALUES (%s, %s)",
                (fact.strip(), added_by)
            )
            conn.commit()
            logger.info(f"Факт '{fact}' добавлен в knowledge_base администратором {added_by}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении факта в knowledge_base: {str(e)}")
        conn.rollback()


def delete_knowledge_fact(fact_id: int, admin_id: int) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_base WHERE id = %s", (fact_id,))
            if cur.rowcount > 0:
                conn.commit()
                logger.info(f"Факт с ID {fact_id} удален администратором {admin_id}")
                return True
            else:
                logger.warning(f"Факт с ID {fact_id} не найден для удаления администратором {admin_id}")
                return False
    except Exception as e:
        logger.error(f"Ошибка при удалении факта с ID {fact_id}: {str(e)}")
        conn.rollback()
        return False


# Улучшенный поиск фактов (топ-5 релевантных)
def find_knowledge_facts(query: str, knowledge_base: List[Dict[str, Any]]) -> List[str]:
    query_lower = query.lower().strip()
    # Ключевые слова и синонимы для тематики ВСКС
    synonyms = {
        "вскс": ["вскс", "студенческий корпус спасателей", "спасатели"],
        "андреев": ["андреев", "алексей евгеньевич"],
        "гуманитарные миссии": ["гуманитарные", "миссии", "помощь"],
        # Добавьте больше синонимов по необходимости
    }

    scores = []
    for fact in knowledge_base:
        fact_lower = fact['text'].lower()
        score = 0
        # Точное совпадение запроса
        if query_lower in fact_lower:
            score += 3
        # Совпадение по словам
        query_words = query_lower.split()
        score += sum(1 for word in query_words if word in fact_lower)
        # Совпадение по синонимам
        for syn_key, syn_list in synonyms.items():
            if syn_key in query_lower:
                score += sum(1 for syn in syn_list if syn in fact_lower)
        if score > 0:
            scores.append((score, fact['text']))

    # Сортировка по релевантности, топ-5
    scores.sort(key=lambda x: x[0], reverse=True)
    matching_facts = [fact for _, fact in scores[:5]]
    logger.info(
        f"Найдено {len(matching_facts)} релевантных фактов для '{query}': {[f[:50] + '...' for f in matching_facts]}")
    return matching_facts


# Функция для веб-поиска
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


# Функции для работы с Яндекс.Диском (без изменений)
def create_yandex_folder(folder_path: str) -> bool:
    folder_path = folder_path.rstrip('/')
    url = f'https://cloud-api.yandex.net/v1/disk/resources?path={quote(folder_path)}'
    headers = {'Authorization': f'OAuth {YANDEX_TOKEN}', 'Content-Type': 'application/json'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            logger.info(f"Папка {folder_path} уже существует")
            return True
        elif response.status_code == 401:
            logger.error(f"Ошибка авторизации Яндекс.Диска: {response.text}")
            return False
        elif response.status_code == 404:
            response = requests.put(url, headers=headers)
            if response.status_code in (201, 409):
                logger.info(f"Папка {folder_path} создана")
                return True
            else:
                logger.error(f"Ошибка создания папки {folder_path}: {response.status_code} - {response.text}")
                return False
        else:
            logger.error(
                f"Неожиданный статус при проверке папки {folder_path}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при создании/проверке папки {folder_path}: {str(e)}")
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
        elif response.status_code == 401:
            logger.error(f"Ошибка авторизации Яндекс.Диска при получении списка: {response.text}")
        else:
            logger.error(f"Ошибка Яндекс.Диска при получении списка: {response.status_code} - {response.text}")
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
        elif response.status_code == 401:
            logger.error(f"Ошибка авторизации Яндекс.Диска для файла {file_path}: {response.text}")
        else:
            logger.error(f"Ошибка Яндекс.Диска для файла {file_path}: {response.status_code} - {response.text}")
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
KNOWLEDGE_BASE = load_knowledge_base()

# Обновленный системный промпт с примерами
system_prompt = """
Ты — полезный чат-бот ВСКС. Всегда отвечай на русском языке, кратко, по делу. Начинай ответ с "{user_name}, ".

ПРИОРИТЕТ: Используй факты из базы знаний как основной источник. Если релевантные факты предоставлены, объединяй их в coherent ответ, добавляя объяснения и предложения уточнить.

Примеры ответов:
- Запрос: "кто такой Андреев Алексей?"
  Ответ: "Кристина, Андреев Алексей Евгеньевич — заместитель руководителя Всероссийского студенческого корпуса спасателей (ВСКС) по развитию региональных отделений и взаимодействию с ними. Он отвечает за координацию работы с региональными структурами организации. Если есть конкретные вопросы, связанные с его деятельностью, могу помочь уточнить детали."

- Запрос: "Что такое ВСКС?"
  Ответ: "Кристина, ВСКС — это Всероссийский студенческий корпус спасателей. Организация основана 22 апреля 2001 года по инициативе Министра МЧС России Сергея Кужугетовича Шойгу. ВСКС объединяет более 8 000 добровольцев из 88 субъектов РФ. Основные задачи включают участие в ликвидации последствий чрезвычайных ситуаций (ЧС), проведение гуманитарных миссий, подготовку студентов-спасателей и организацию мероприятий, таких как форумы и слёты. Если есть вопросы о структуре, задачах или участии, готов рассказать подробнее!"

Если фактов нет, используй веб-поиск или свои знания, но всегда проверяй на актуальность.
"""

# Сохранение истории переписки
histories: Dict[int, Dict[str, Any]] = {}


# Функция для генерации AI-ответа
async def generate_ai_response(user_id: int, user_input: str, user_name: str, chat_id: int) -> str:
    global KNOWLEDGE_BASE
    if not KNOWLEDGE_BASE:
        KNOWLEDGE_BASE = load_knowledge_base()

    # Поиск релевантных фактов
    matching_facts = find_knowledge_facts(user_input, KNOWLEDGE_BASE)

    # Инициализация истории
    if chat_id not in histories:
        histories[chat_id] = {"name": user_name, "messages": [
            {"role": "system", "content": system_prompt.replace("{user_name}", user_name)}]}

    messages = histories[chat_id]["messages"]

    if matching_facts:
        # Если факты найдены: используем их как приоритет
        facts_text = "\n".join(matching_facts)
        fact_prompt = f"""
Используй ТОЛЬКО эти релевантные факты из базы знаний для ответа на вопрос '{user_input}'.
Факты: {facts_text}

Объедини факты в coherent, информативный ответ. Добавь объяснения, структуру и предложение уточнить. 
Не добавляй информацию извне.
        """
        messages.append({"role": "system", "content": fact_prompt})
        logger.info(f"Генерирую ответ на основе {len(matching_facts)} фактов для user_id {user_id}")
    else:
        # Если фактов нет, добавляем топ-10 общих фактов, если запрос о ВСКС
        if any(word in user_input.lower() for word in ["вскс", "спасатели", "корпус"]):
            top_facts = [fact['text'] for fact in KNOWLEDGE_BASE[:10]]
            facts_text = "; ".join(top_facts)
            messages.append({"role": "system", "content": f"База знаний (используй как приоритет): {facts_text}"})
        # Веб-поиск если нужно
        need_search = any(word in user_input.lower() for word in [
            "актуальная информация", "последние новости", "найди в интернете", "поиск",
            "что такое", "информация о", "расскажи о", "найди", "поиск по", "детали о"
        ])
        if need_search:
            search_results_json = web_search(user_input)
            try:
                results = json.loads(search_results_json)
                if isinstance(results, list):
                    extracted_text = "\n".join(
                        [f"Источник: {r.get('title', '')}\n{r.get('body', '')}" for r in results])
                messages.append({"role": "system", "content": f"Актуальные факты из поиска: {extracted_text}"})
            except json.JSONDecodeError:
                pass

    messages.append({"role": "user", "content": user_input})
    if len(messages) > 20:
        messages = messages[:1] + messages[-19:]

    # Запрос к API
    models_to_try = [XAI_MODEL, "grok", "grok-3", "grok-4"]
    ai_response = "Извините, не удалось получить ответ от API. Проверьте подписку на SuperGrok или X Premium+."

    for model in models_to_try:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                stream=False
            )
            ai_response = completion.choices[0].message.content.strip()
            logger.info(f"Ответ модели {model} для user_id {user_id}: {ai_response[:100]}...")
            break
        except Exception as e:
            logger.error(f"Ошибка для {model}: {str(e)}")
            continue

    histories[chat_id]["messages"].append({"role": "assistant", "content": ai_response})
    return ai_response


# Функция для получения user_name (исправленная)
def get_user_name(user_id: int) -> str:
    profile = USER_PROFILES.get(user_id)
    if profile:
        return profile.get("name") or "Пользователь"
    return "Пользователь"


# Обработчик команды /start
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text(f"{user_name}, ваш user_id: {user_id}\nИзвините, у вас нет доступа.",
                                        reply_markup=ReplyKeyboardRemove())
        return
    if user_id not in USER_PROFILES:
        context.user_data["awaiting_fio"] = True
        await update.message.reply_text("Пожалуйста, напишите своё ФИО.", reply_markup=ReplyKeyboardRemove())
        return
    profile = USER_PROFILES[user_id]
    if profile.get("name") is None:
        context.user_data["awaiting_name"] = True
        await update.message.reply_text("Как я могу к вам обращаться? Укажите краткое имя (например, Кристина).",
                                        reply_markup=ReplyKeyboardRemove())
    else:
        await show_main_menu(update, context)


# Команда /add_fact для добавления фактов (только для админов)
async def add_fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global KNOWLEDGE_BASE
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    if user_id not in ALLOWED_ADMINS:
        await update.message.reply_text(f"{user_name}, только администраторы могут добавлять факты.",
                                        reply_markup=ReplyKeyboardRemove())
        return
    args = context.args
    if not args:
        await update.message.reply_text(f"{user_name}, использование: /add_fact <факт>",
                                        reply_markup=ReplyKeyboardRemove())
        return
    fact = ' '.join(args).strip()
    if not any(f['text'] == fact for f in KNOWLEDGE_BASE):
        save_knowledge_fact(fact, user_id)
        KNOWLEDGE_BASE = load_knowledge_base()
        await update.message.reply_text(f"{user_name}, факт '{fact}' добавлен в базу знаний.",
                                        reply_markup=ReplyKeyboardRemove())
        logger.info(f"Факт '{fact}' добавлен администратором {user_id} в knowledge_base")
    else:
        await update.message.reply_text(f"{user_name}, факт '{fact}' уже существует в базе знаний.",
                                        reply_markup=ReplyKeyboardRemove())


# Команда /delete_fact для удаления фактов (только для админов)
async def delete_fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global KNOWLEDGE_BASE
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    if user_id not in ALLOWED_ADMINS:
        await update.message.reply_text(f"{user_name}, только администраторы могут удалять факты.",
                                        reply_markup=ReplyKeyboardRemove())
        return
    if not KNOWLEDGE_BASE:
        await update.message.reply_text(f"{user_name}, база знаний пуста.", reply_markup=ReplyKeyboardRemove())
        return
    facts_list = "\n".join([f"ID: {fact['id']} — {fact['text']}" for fact in KNOWLEDGE_BASE])
    context.user_data["awaiting_fact_id"] = True
    await update.message.reply_text(
        f"{user_name}, выберите ID факта для удаления:\n{facts_list}\n\nВведите ID:",
        reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True)
    )
    logger.info(f"Администратор {user_id} запросил удаление факта. Показаны факты:\n{facts_list}")


# Отображение главного меню
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
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
    context.user_data.pop('awaiting_user_id', None)
    context.user_data.pop('awaiting_admin_id', None)
    context.user_data.pop('awaiting_upload', None)
    context.user_data.pop('awaiting_fact_id', None)
    context.user_data.pop('awaiting_delete_user_id', None)
    await update.message.reply_text(f"{user_name}, выберите действие:", reply_markup=reply_markup)


# Отображение меню управления пользователями
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    keyboard = [
        ['Добавить пользователя', 'Добавить администратора'],
        ['Список пользователей', 'Список администраторов'],
        ['Удалить пользователя', 'Удалить файл'],
        ['Удалить факт', 'Назад']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(f"{user_name}, выберите действие:", reply_markup=reply_markup)


# Отображение содержимого папки в /documents/
async def show_current_docs(update: Update, context: ContextTypes.DEFAULT_TYPE, is_return: bool = False) -> None:
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    context.user_data.pop('file_list', None)
    current_path = context.user_data.get('current_path', '/documents/')
    folder_name = current_path.rstrip('/').split('/')[-1] or "Документы"
    if not create_yandex_folder(current_path):
        logger.warning(f"Не удалось создать папку {current_path}, возможно, она уже существует или проблема с токеном.")
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
        context.user_data['current_path'] = current_path
        file_keyboard = [[InlineKeyboardButton(item['name'], callback_data=f"doc_download:{idx}")] for idx, item in
                         enumerate(files)]
        file_reply_markup = InlineKeyboardMarkup(file_keyboard)
        await update.message.reply_text(f"{user_name}, файлы в папке {folder_name}:", reply_markup=file_reply_markup)
    elif dirs:
        if not is_return:
            message = "Документы для РО" if current_path == '/documents/' else f"Папки в {folder_name}:"
            await update.message.reply_text(f"{user_name}, {message}", reply_markup=reply_markup)
    else:
        await update.message.reply_text(f"{user_name}, папка {folder_name} пуста.", reply_markup=reply_markup)


# Обработка callback-запросов
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    default_reply_markup = context.user_data.get('default_reply_markup', ReplyKeyboardRemove())
    profile = USER_PROFILES.get(user_id)
    if not profile or "region" not in profile:
        await query.message.reply_text(f"{user_name}, ошибка: регион не определён.", reply_markup=default_reply_markup)
        return

    if query.data.startswith("doc_download:") or query.data.startswith("download:"):
        try:
            file_idx = int(query.data.split(":", 1)[1])
            if query.data.startswith("doc_download:"):
                current_path = context.user_data.get('current_path', '/documents/')
            else:
                current_path = f"/regions/{profile['region']}/"

            files = context.user_data.get('file_list', []) or list_yandex_disk_files(current_path)
            context.user_data['file_list'] = files
            context.user_data['current_path'] = current_path

            if file_idx >= len(files):
                await query.message.reply_text(f"{user_name}, ошибка: файл не найден.",
                                               reply_markup=default_reply_markup)
                logger.error(f"Файл с индексом {file_idx} не найден в папке {current_path} для user_id {user_id}")
                return

            file_name = files[file_idx]['name']
            file_path = f"{current_path.rstrip('/')}/{file_name}"
            logger.info(f"Попытка скачать файл {file_path} для user_id {user_id}")

            download_url = get_yandex_disk_file(file_path)
            if not download_url:
                await query.message.reply_text(
                    f"{user_name}, ошибка: не удалось получить ссылку на файл. Проверьте YANDEX_TOKEN.",
                    reply_markup=default_reply_markup)
                logger.error(f"Не удалось получить ссылку для файла {file_path}")
                return

            file_response = requests.get(download_url)
            if file_response.status_code == 200:
                file_size = len(file_response.content) / (1024 * 1024)
                if file_size > 20:
                    await query.message.reply_text(f"{user_name}, файл слишком большой (>20 МБ).",
                                                   reply_markup=default_reply_markup)
                    logger.warning(f"Файл {file_name} слишком большой: {file_size} МБ")
                    return
                await query.message.reply_document(document=InputFile(file_response.content, filename=file_name))
                logger.info(f"Файл {file_name} успешно отправлен пользователю {user_id} из {current_path}")
            else:
                await query.message.reply_text(
                    f"{user_name}, не удалось загрузить файл. Статус: {file_response.status_code}",
                    reply_markup=default_reply_markup)
                logger.error(f"Ошибка загрузки файла {file_path}: статус {file_response.status_code}")
        except Exception as e:
            await query.message.reply_text(f"{user_name}, ошибка при скачивании: {str(e)}. Проверьте YANDEX_TOKEN.",
                                           reply_markup=default_reply_markup)
            logger.error(f"Ошибка при отправке файла: {str(e)}")


# Функция для логирования запросов
def log_request(user_id: int, request: str, response: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO request_logs (user_id, request_text, response_text, timestamp) VALUES (%s, %s, %s, NOW())",
                (user_id, request, response)
            )
            conn.commit()
            logger.info(f"Запрос от {user_id} залогирован")
    except Exception as e:
        logger.error(f"Ошибка при логировании запроса: {str(e)}")
        conn.rollback()


# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global KNOWLEDGE_BASE, ALLOWED_USERS
    user_id: int = update.effective_user.id
    chat_id: int = update.effective_chat.id
    user_input: str = update.message.text.strip()
    user_name = get_user_name(user_id)
    logger.info(f"Получено сообщение от {chat_id} (user_id: {user_id}): {user_input}")
    log_request(user_id, user_input, "Обработка сообщения...")

    if user_id not in ALLOWED_USERS and user_id not in ALLOWED_ADMINS:
        await update.message.reply_text(f"{user_name}, извините, у вас нет доступа.",
                                        reply_markup=ReplyKeyboardRemove())
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

    # Обработка состояний (без изменений, кроме user_name)
    if context.user_data.get("awaiting_fact_id", False):
        if user_id not in ALLOWED_ADMINS:
            await update.message.reply_text(f"{user_name}, только администраторы могут удалять факты.",
                                            reply_markup=default_reply_markup)
            context.user_data.pop("awaiting_fact_id", None)
            return
        if user_input == "Назад":
            context.user_data.pop("awaiting_fact_id", None)
            await show_main_menu(update, context)
            return
        try:
            fact_id = int(user_input)
            if delete_knowledge_fact(fact_id, user_id):
                KNOWLEDGE_BASE = load_knowledge_base()
                await update.message.reply_text(f"{user_name}, факт с ID {fact_id} удалён.",
                                                reply_markup=default_reply_markup)
            else:
                await update.message.reply_text(f"{user_name}, факт с ID {fact_id} не найден.",
                                                reply_markup=default_reply_markup)
            context.user_data.pop("awaiting_fact_id", None)
        except ValueError:
            await update.message.reply_text(f"{user_name}, введите корректный ID факта (число).",
                                            reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True))
        return

    # ... (остальные состояния без изменений, заменяя user_name на get_user_name(user_id))

    if context.user_data.get("awaiting_user_id", False):
        try:
            new_user_id = int(user_input)
            if new_user_id in ALLOWED_USERS:
                await update.message.reply_text(f"{user_name}, пользователь с ID {new_user_id} уже существует.",
                                                reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True))
            else:
                ALLOWED_USERS.append(new_user_id)
                save_allowed_users(ALLOWED_USERS)
                await update.message.reply_text(f"{user_name}, пользователь с ID {new_user_id} успешно добавлен.",
                                                reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True))
                logger.info(f"Пользователь {new_user_id} добавлен администратором {user_id}")
            context.user_data.pop("awaiting_user_id", None)
            return
        except ValueError:
            await update.message.reply_text(f"{user_name}, пожалуйста, введите корректный user_id (число).",
                                            reply_markup=ReplyKeyboardMarkup([['Назад']], resize_keyboard=True))
            return

    # Аналогично для других состояний (awaiting_admin_id, awaiting_delete_user_id, awaiting_federal_district, awaiting_region, awaiting_name)
    # В awaiting_name:
    if context.user_data.get("awaiting_name", False):
        USER_PROFILES[user_id]["name"] = user_input.strip()
        save_user_profiles(USER_PROFILES)
        context.user_data["awaiting_name"] = False
        user_name = user_input.strip()  # Обновляем локально
        await show_main_menu(update, context)
        await update.message.reply_text(f"{user_name}, рад знакомству! Задавайте вопросы или используйте меню.",
                                        reply_markup=default_reply_markup)
        return

    # Обработка меню (без изменений)

    handled = False
    if user_input == "Документы для РО":
        # ... (без изменений)
        handled = True

    # ... (остальные if для меню)

    # AI-обработка если не handled
    if not handled:
        logger.info(f"Обрабатываю AI-запрос для user_id {user_id}: {user_input}")
        ai_response = await generate_ai_response(user_id, user_input, user_name, chat_id)
        final_response = f"{ai_response}"  # Уже начинается с имени из промпта
        await update.message.reply_text(final_response, reply_markup=default_reply_markup)
        log_request(user_id, user_input, final_response)


# Обработка загруженных документов (без изменений, кроме user_name)
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    # ... (остальной код без изменений)


# Отображение списка файлов (без изменений, кроме user_name)
async def show_file_list(update: Update, context: ContextTypes.DEFAULT_TYPE, for_deletion: bool = False) -> None:
    user_id: int = update.effective_user.id
    user_name = get_user_name(user_id)
    # ... (остальной код без изменений)


# Основная функция
def main():
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", send_welcome))
        app.add_handler(CommandHandler("add_fact", add_fact))
        app.add_handler(CommandHandler("delete_fact", delete_fact))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        app.add_handler(CallbackQueryHandler(handle_callback_query))
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
        raise


if __name__ == '__main__':
    main()