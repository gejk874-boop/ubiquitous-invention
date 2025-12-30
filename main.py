import asyncio
import sqlite3
import re
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from aiogram import Bot, Dispatcher, types, F, exceptions
from aiogram.filters import Command, CommandObject
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    FSInputFile
)
from functools import lru_cache

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8424514943:AAHdwbe3tf-YsaY4akF3iNhscXcb_493dgQ"
ADMIN_IDS = [6986121067]
BOT_USERNAME = None  # Будет установлено автоматически при запуске

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === КОНСТАНТЫ ===
MAX_REPORTS_PER_HOUR = 5
DB_PATH = 'reports.db'

# === БАЗА ДАННЫХ ===
def init_db():
    """Инициализация базы данных (создание таблиц если их нет)"""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        # Создаем таблицу пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Создаем таблицу жалоб
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                target_username TEXT NOT NULL,
                status TEXT NOT NULL,
                comment TEXT NOT NULL,
                proof_photo TEXT,
                is_approved BOOLEAN DEFAULT FALSE,
                is_rejected BOOLEAN DEFAULT FALSE,
                moderator_id INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Создаем таблицу заблокированных пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blocked_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                reason TEXT,
                blocked_by INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Создаем таблицу для групп
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                type TEXT,
                added_by INTEGER,
                added_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Создаем индексы для ускорения запросов
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reports_target_username ON reports(target_username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reports_reporter_id ON reports(reporter_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reports_timestamp ON reports(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocked_users_user_id ON blocked_users(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_bot_users_username ON bot_users(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_groups_chat_id ON chat_groups(chat_id)')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
        
    except sqlite3.Error as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# === КОНТЕКСТНЫЕ МЕНЕДЖЕРЫ ДЛЯ БД ===
class DatabaseConnection:
    """Контекстный менеджер для работы с базой данных"""
    
    @staticmethod
    def get_connection():
        """Получить соединение с БД"""
        return sqlite3.connect(DB_PATH, check_same_thread=False)
    
    @staticmethod
    def execute_query(query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False, return_lastrowid: bool = False):
        """Выполнить запрос с параметрами"""
        try:
            with DatabaseConnection.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                if fetch_one:
                    result = cursor.fetchone()
                elif fetch_all:
                    result = cursor.fetchall()
                elif return_lastrowid:
                    result = cursor.lastrowid
                    conn.commit()
                else:
                    result = cursor.rowcount
                    conn.commit()
                
                return result
        except sqlite3.Error as e:
            logger.error(f"❌ Ошибка выполнения запроса: {e}")
            raise

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def add_bot_user(user_id, username, first_name, last_name):
    """Добавление пользователя в базу"""
    try:
        query = '''
            INSERT OR REPLACE INTO bot_users (user_id, username, first_name, last_name, joined_date, last_activity)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        '''
        DatabaseConnection.execute_query(query, (user_id, username, first_name, last_name))
        logger.info(f"✅ Добавлен/обновлен пользователь: {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка добавления пользователя {user_id}: {e}")

def update_user_activity(user_id):
    """Обновление времени последней активности"""
    try:
        query = 'UPDATE bot_users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?'
        DatabaseConnection.execute_query(query, (user_id,))
    except Exception as e:
        logger.error(f"❌ Ошибка обновления активности пользователя {user_id}: {e}")

def add_chat_group(chat_id, title, chat_type, added_by):
    """Добавление группы в базу"""
    try:
        query = '''
            INSERT OR REPLACE INTO chat_groups (chat_id, title, type, added_by, added_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        '''
        DatabaseConnection.execute_query(query, (chat_id, title, chat_type, added_by))
        logger.info(f"✅ Добавлена/обновлена группа: {chat_id} ({title})")
    except Exception as e:
        logger.error(f"❌ Ошибка добавления группы {chat_id}: {e}")

def get_chat_group(chat_id):
    """Получить информацию о группе"""
    try:
        query = 'SELECT chat_id, title, type FROM chat_groups WHERE chat_id = ?'
        result = DatabaseConnection.execute_query(query, (chat_id,), fetch_one=True)
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка получения группы {chat_id}: {e}")
        return None

@lru_cache(maxsize=128)
def is_user_blocked(user_id: int) -> bool:
    """Кэшированная проверка блокировки пользователя"""
    try:
        query = 'SELECT id FROM blocked_users WHERE user_id = ?'
        result = DatabaseConnection.execute_query(query, (user_id,), fetch_one=True)
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка проверки блокировки: {e}")
        return False

def get_all_users_for_broadcast():
    """Получает всех пользователей для рассылки"""
    try:
        query = 'SELECT DISTINCT user_id FROM bot_users WHERE user_id IS NOT NULL'
        results = DatabaseConnection.execute_query(query, fetch_all=True)
        user_ids = [row[0] for row in results] if results else []
        
        logger.info(f"📊 Найдено {len(user_ids)} пользователей для рассылки")
        return user_ids
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователей: {e}")
        return []

def get_user_id_by_username(username: str) -> Optional[int]:
    """Получить ID пользователя по username"""
    try:
        query = 'SELECT user_id FROM bot_users WHERE username = ?'
        result = DatabaseConnection.execute_query(query, (username,), fetch_one=True)
        return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Ошибка получения ID по username: {e}")
        return None

def block_user(user_id: int, username: str, reason: str, blocked_by: int) -> Tuple[bool, str]:
    """Блокировка пользователя"""
    try:
        # Проверяем, не заблокирован ли уже
        if is_user_blocked(user_id):
            return False, "❌ Пользователь уже заблокирован"
        
        query = '''
            INSERT INTO blocked_users (user_id, username, reason, blocked_by)
            VALUES (?, ?, ?, ?)
        '''
        DatabaseConnection.execute_query(query, (user_id, username, reason, blocked_by))
        
        logger.info(f"✅ Пользователь @{username} заблокирован")
        return True, f"✅ Пользователь @{username} заблокирован"
    except Exception as e:
        logger.error(f"❌ Ошибка блокировки: {e}")
        return False, f"❌ Ошибка блокировки: {e}"

def unblock_user(user_id: int) -> Tuple[bool, str]:
    """Разблокировка пользователя"""
    try:
        query = 'DELETE FROM blocked_users WHERE user_id = ?'
        rows_affected = DatabaseConnection.execute_query(query, (user_id,))
        
        if rows_affected > 0:
            return True, "✅ Пользователь разблокирован"
        else:
            return False, "❌ Пользователь не найден в заблокированных"
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки: {e}")
        return False, f"❌ Ошибка разблокировки: {e}"

def delete_user_reports(target_username: str) -> Tuple[bool, str]:
    """Удаление всех жалоб на пользователя"""
    try:
        query = 'DELETE FROM reports WHERE target_username = ?'
        rows_deleted = DatabaseConnection.execute_query(query, (target_username.lower(),))
        return True, f"✅ Удалено {rows_deleted} жалоб на @{target_username}"
    except Exception as e:
        logger.error(f"❌ Ошибка удаления жалоб: {e}")
        return False, f"❌ Ошибка удаления: {e}"

def get_user_reports(target_username: str) -> List[Tuple]:
    """Получение всех одобренных жалоб на пользователя"""
    try:
        query = '''
            SELECT status, comment, timestamp FROM reports 
            WHERE target_username = ? AND is_approved = TRUE
            ORDER BY timestamp DESC
            LIMIT 10
        '''
        results = DatabaseConnection.execute_query(query, (target_username.lower(),), fetch_all=True)
        return results if results else []
    except Exception as e:
        logger.error(f"❌ Ошибка получения жалоб: {e}")
        return []

def get_recent_reports_count(reporter_id: int, hours: int = 1) -> int:
    """Подсчет жалоб за последние N часов"""
    try:
        time_threshold = datetime.now() - timedelta(hours=hours)
        query = 'SELECT COUNT(*) FROM reports WHERE reporter_id = ? AND timestamp > ?'
        result = DatabaseConnection.execute_query(query, (reporter_id, time_threshold), fetch_one=True)
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"❌ Ошибка подсчета жалоб: {e}")
        return 0

def add_report(reporter_id: int, target_username: str, status: str, comment: str, proof_photo: str = None) -> Optional[int]:
    """Добавление новой жалобы"""
    try:
        query = '''
            INSERT INTO reports (reporter_id, target_username, status, comment, proof_photo)
            VALUES (?, ?, ?, ?, ?)
        '''
        report_id = DatabaseConnection.execute_query(
            query, 
            (reporter_id, target_username.lower(), status, comment, proof_photo),
            return_lastrowid=True
        )
        
        if report_id:
            logger.info(f"🆕 Создана жалоба #{report_id} на @{target_username}")
        return report_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления жалобы: {e}")
        return None

def get_pending_reports() -> List[Tuple]:
    """Получение всех жалоб на модерации"""
    try:
        query = '''
            SELECT id, reporter_id, target_username, status, comment, proof_photo
            FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE
            ORDER BY timestamp ASC LIMIT 20
        '''
        results = DatabaseConnection.execute_query(query, fetch_all=True)
        logger.info(f"📋 Найдено жалоб на модерации: {len(results)}")
        return results
    except Exception as e:
        logger.error(f"❌ Ошибка получения жалоб: {e}")
        return []

def approve_report(report_id: int, moderator_id: int) -> Tuple[Optional[int], Optional[str]]:
    """Одобрение жалобы"""
    try:
        query = '''
            UPDATE reports SET is_approved = TRUE, moderator_id = ?
            WHERE id = ? AND is_approved = FALSE AND is_rejected = FALSE
        '''
        rows_affected = DatabaseConnection.execute_query(query, (moderator_id, report_id))
        
        if rows_affected > 0:
            result = DatabaseConnection.execute_query(
                'SELECT reporter_id, target_username FROM reports WHERE id = ?',
                (report_id,), fetch_one=True
            )
            if result:
                logger.info(f"✅ Жалоба #{report_id} одобрена модератором {moderator_id}")
                return result[0], result[1]
        return None, None
    except Exception as e:
        logger.error(f"❌ Ошибка одобрения: {e}")
        return None, None

def reject_report(report_id: int, moderator_id: int) -> Optional[int]:
    """Отклонение жалобы"""
    try:
        query = '''
            UPDATE reports SET is_rejected = TRUE, moderator_id = ?
            WHERE id = ? AND is_approved = FALSE AND is_rejected = FALSE
        '''
        rows_affected = DatabaseConnection.execute_query(query, (moderator_id, report_id))
        
        if rows_affected > 0:
            result = DatabaseConnection.execute_query(
                'SELECT reporter_id FROM reports WHERE id = ?',
                (report_id,), fetch_one=True
            )
            if result:
                logger.info(f"❌ Жалоба #{report_id} отклонена модератором {moderator_id}")
                return result[0]
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка отклонения: {e}")
        return None

def validate_username(username: str) -> Tuple[bool, str]:
    """Валидация username"""
    if not username or len(username) < 3:
        return False, "❌ Юзернейм слишком короткий (минимум 3 символа)"
    if len(username) > 32:
        return False, "❌ Юзернейм слишком длинный (максимум 32 символа)"
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "❌ Юзернейм может содержать только буквы, цифры и подчеркивания"
    return True, "✅ Юзернейм корректен"

# === ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЙ ===
async def send_update_notification():
    """Отправляет уведомление об обновлении всем пользователям"""
    all_user_ids = get_all_users_for_broadcast()
    
    if not all_user_ids:
        logger.warning("⚠️ Не найдено пользователей для рассылки")
        return 0, 0, 0
    
    success_count = 0
    failed_count = 0
    blocked_bot_count = 0
    
    update_message = (
        "🔄 <b>ОБНОВЛЕНИЕ БОТА ЗАВЕРШЕНО!</b>\n\n"
        "✅ Были добавлены новые функции и улучшена стабильность работы\n\n"
        "📲 <b>Пожалуйста, перезапустите бота командой</b> /start\n"
        "чтобы получить доступ ко всем новым возможностям!"
    )
    
    for index, user_id in enumerate(all_user_ids, 1):
        try:
            if not is_user_blocked(user_id):
                await bot.send_message(user_id, update_message, parse_mode="HTML")
                success_count += 1
                
                if index % 20 == 0:
                    logger.info(f"📤 Отправлено {index}/{len(all_user_ids)} пользователям")
                    await asyncio.sleep(1)
        except exceptions.TelegramForbiddenError:
            blocked_bot_count += 1
            failed_count += 1
        except exceptions.TelegramBadRequest as e:
            if "chat not found" in str(e).lower() or "user not found" in str(e).lower():
                blocked_bot_count += 1
                failed_count += 1
            else:
                logger.error(f"❌ Ошибка Telegram для пользователя {user_id}: {e}")
                failed_count += 1
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Таймаут при отправке пользователю {user_id}")
            failed_count += 1
        except Exception as e:
            logger.error(f"❌ Не удалось отправить уведомление пользователю {user_id}: {e}")
            failed_count += 1
        
        await asyncio.sleep(0.05)
    
    logger.info(f"📢 Уведомления обновления: ✅ {success_count}, ❌ {failed_count}, 🚫 {blocked_bot_count}")
    return success_count, failed_count, blocked_bot_count

# === КЛАВИАТУРЫ ===
def get_user_keyboard(user_id):
    keyboard = [
        [KeyboardButton(text="📝 Жалоба"), KeyboardButton(text="🔍 Проверить")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    
    # Добавляем кнопку "Добавить в чат"
    if BOT_USERNAME:
        add_to_group_text = f"https://t.me/{BOT_USERNAME}?startgroup=true"
        keyboard.append([KeyboardButton(text="➕ Добавить в чат", url=add_to_group_text)])
    
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton(text="🛠 Админ")])
        keyboard.append([KeyboardButton(text="📥 Скачать БД"), KeyboardButton(text="📊 Статистика")])
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

back_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

proof_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📎 Пропустить")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

status_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="тролль"), KeyboardButton(text="доксинг")],
        [KeyboardButton(text="скам"), KeyboardButton(text="другое")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

# === СОСТОЯНИЯ ===
class UserStates(StatesGroup):
    WAITING_FOR_USERNAME = State()
    WAITING_FOR_COMMENT = State()
    WAITING_FOR_PROOF = State()
    WAITING_FOR_STATUS = State()
    WAITING_FOR_CUSTOM_STATUS = State()
    WAITING_CHECK_USERNAME = State()

class AdminStates(StatesGroup):
    WAITING_BLOCK_USERNAME = State()
    WAITING_BLOCK_REASON = State()
    WAITING_UNBLOCK_USERNAME = State()
    WAITING_ANNOUNCEMENT = State()
    WAITING_DELETE_USER = State()

# === ОСНОВНЫЕ ОБРАБОТЧИКИ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    chat_type = message.chat.type
    
    # Обновляем активность пользователя
    update_user_activity(user_id)
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    # Добавляем пользователя в базу
    add_bot_user(
        user_id, 
        message.from_user.username, 
        message.from_user.first_name, 
        message.from_user.last_name
    )
    
    # Если бот добавлен в группу
    if chat_type in ["group", "supergroup"]:
        chat_id = message.chat.id
        chat_title = message.chat.title
        added_by = user_id
        
        # Добавляем группу в базу
        add_chat_group(chat_id, chat_title, chat_type, added_by)
        
        welcome_text = f"""
🤖 **Бот проверки пользователей добавлен в группу!**

📋 **Доступные команды в группе:**
/check @username - проверить пользователя
/info - информация о боте

📝 **Для подачи жалобы** - напишите боту в личные сообщения

⚠️ **Внимание:** 
- Бот работает только с одобренными жалобами
- Все жалобы проходят модерацию
        """
        
        await message.answer(welcome_text)
        return
    
    # Личные сообщения
    welcome_text = """
🎯 **Добро пожаловать в бот проверки пользователей!**

📝 **Жалоба** - сообщить о ненадежном пользователе
🔍 **Проверить** - узнайте информацию о пользователе  
ℹ️ **Помощь** - получите справку по работе бота
➕ **Добавить в чат** - добавить бота в группу или канал
    """
    
    try:
        image_paths = [
            "Lumii_20251122_105626106.jpg",
            "./Lumii_20251122_105626106.jpg",
            "ubiquitous-invention/Lumii_20251122_105626106.jpg",
            "./ubiquitous-invention/Lumii_20251122_105626106.jpg"
        ]
        
        photo = None
        for path in image_paths:
            if os.path.exists(path):
                photo = FSInputFile(path)
                logger.info(f"✅ Найдено изображение: {path}")
                break
        
        if photo:
            await message.answer_photo(
                photo=photo,
                caption=welcome_text,
                reply_markup=get_user_keyboard(user_id)
            )
        else:
            github_url = "https://raw.githubusercontent.com/gejk874-boop/ubiquitous-invention/main/Lumii_20251122_105626106.jpg"
            await message.answer_photo(
                photo=github_url,
                caption=welcome_text,
                reply_markup=get_user_keyboard(user_id)
            )
            logger.info("✅ Использовано изображение из GitHub")
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки фото: {e}")
        await message.answer(welcome_text, reply_markup=get_user_keyboard(user_id))

@dp.message(Command("check"))
async def cmd_check(message: types.Message, command: CommandObject):
    """Проверить пользователя в группе"""
    chat_type = message.chat.type
    user_id = message.from_user.id
    
    # Обновляем активность пользователя
    update_user_activity(user_id)
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    # Проверяем, есть ли аргумент
    if not command.args:
        if chat_type in ["group", "supergroup"]:
            await message.answer(
                " 📋 Использование команды в группе: 
                "/check username
            )
        else:
            await message.answer(
                "🔍 Проверить пользователя"
                "check username"
            )
        return
    
    # Обрабатываем username из аргумента
    username = command.args.strip()
    
    # Убираем @ если есть
    if username.startswith('@'):
        username = username[1:]
    
    # Проверяем валидность username
    is_valid, validation_msg = validate_username(username)
    if not is_valid:
        await message.answer(f"❌ {validation_msg}")
        return
    
    # Получаем информацию о пользователе
    reports = get_user_reports(username)
    
    if not reports:
        response = f"ℹ️ **Информация о @{username}**\n\n" \
                   f"✅ Пользователь чист\n" \
                   f"📊 Нарушений не найдено"
        
        if chat_type in ["group", "supergroup"]:
            await message.reply(response)
        else:
            await message.answer(response)
        return
    
    # Формируем ответ с информацией о нарушениях
    statuses = set()
    comments = []
    total_reports = len(reports)
    
    for status, comment, timestamp in reports:
        statuses.add(status)
        comments.append(f"• {comment} ({timestamp[:10]})")
    
    response_lines = [
        f"⚠️ **Информация о @{username}**\n",
        f"🚨 **Статусы нарушений:** {', '.join(sorted(statuses))}",
        f"📝 **Последние жалобы:**",
    ]
    
    # Добавляем последние 3 комментария
    for i, comment in enumerate(comments[:3], 1):
        response_lines.append(f"{i}. {comment}")
    
    response_lines.extend([
        f"",
        f"📊 **Всего одобренных жалоб:** {total_reports}",
        f"",
        f"⚠️ **Рекомендация:** Будьте осторожны при взаимодействии с этим пользователем."
    ])
    
    response = "\n".join(response_lines)
    
    if chat_type in ["group", "supergroup"]:
        await message.reply(response)
    else:
        await message.answer(response)

# Обработчик добавления бота в группу
@dp.message(F.chat.type.in_(["group", "supergroup"]) & F.new_chat_members)
async def on_bot_added_to_group(message: types.Message):
    """Обработчик добавления бота в группу"""
    bot_id = (await bot.get_me()).id
    
    # Проверяем, добавили ли нашего бота
    for new_member in message.new_chat_members:
        if new_member.id == bot_id:
            chat_id = message.chat.id
            chat_title = message.chat.title
            chat_type = message.chat.type
            added_by = message.from_user.id
            
            # Проверяем, есть ли уже группа в базе
            existing_group = get_chat_group(chat_id)
            if not existing_group:
                # Добавляем группу в базу
                add_chat_group(chat_id, chat_title, chat_type, added_by)
                
                # Отправляем приветственное сообщение
                welcome_text = f"""
🤖 **Бот проверки пользователей добавлен в группу!**

📋 **Доступные команды в группе:**
/check @username - проверить пользователя
/info - информация о боте

📝 **Для подачи жалобы** - напишите боту в личные сообщения

⚠️ **Внимание:** 
- Бот работает только с одобренными жалобами
- Все жалобы проходят модерацию
                """
                
                await message.answer(welcome_text)
                logger.info(f"✅ Бот добавлен в группу {chat_id} ({chat_title})")
            break

@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    """Информация о боте в группе"""
    chat_type = message.chat.type
    
    info_text = f"""
🤖 **Бот проверки пользователей**

📋 **Функции:**
• Проверка пользователей на наличие жалоб
• Подача жалоб на недобросовестных пользователей
• Модерация всех жалоб администраторами

🚀 **Команды в группе:**
/check @username - проверить пользователя
/info - информация о боте

📝 **Для подачи жалобы:**
Напишите боту в личные сообщения @{BOT_USERNAME}

🛡 **Все жалобы проходят модерацию перед публикацией**
    """
    
    if chat_type in ["group", "supergroup"]:
        await message.answer(info_text)
    else:
        await message.answer(info_text, reply_markup=get_user_keyboard(message.from_user.id))

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    """Показать статистику пользователей"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return
    
    try:
        query = '''
            SELECT COUNT(*) as total_users,
                   (SELECT COUNT(*) FROM blocked_users) as blocked_users,
                   (SELECT COUNT(*) FROM reports) as total_reports,
                   (SELECT COUNT(*) FROM reports WHERE is_approved = TRUE) as approved_reports,
                   (SELECT COUNT(*) FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE) as pending_reports,
                   (SELECT COUNT(*) FROM bot_users WHERE DATE(joined_date) = DATE(CURRENT_TIMESTAMP)) as today_users,
                   (SELECT COUNT(*) FROM chat_groups) as total_groups
            FROM bot_users
        '''
        result = DatabaseConnection.execute_query(query, fetch_one=True)
        
        if result:
            total_users, blocked_users, total_reports, approved_reports, pending_reports, today_users, total_groups = result
            
            response = [
                f"📊 <b>Статистика пользователей</b>\n",
                f"👥 Всего пользователей: <b>{total_users}</b>",
                f"🚫 Заблокировано: <b>{blocked_users}</b>",
                f"📨 Всего жалоб: <b>{total_reports}</b>",
                f"✅ Одобрено: <b>{approved_reports}</b>",
                f"⏳ На модерации: <b>{pending_reports}</b>",
                f"📈 Новых сегодня: <b>{today_users}</b>",
                f"👥 Групп с ботом: <b>{total_groups}</b>",
                f"",
                f"🆕 <b>Последние 10 пользователей:</b>"
            ]
            
            # Получаем последних пользователей
            recent_users = DatabaseConnection.execute_query(
                'SELECT user_id, username, joined_date FROM bot_users ORDER BY joined_date DESC LIMIT 10',
                fetch_all=True
            ) or []
            
            for user_id, username, joined_date in recent_users:
                username_display = f"@{username}" if username else f"ID:{user_id}"
                response.append(f"• {username_display} ({joined_date[:10]})")
            
            await message.answer("\n".join(response), parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

@dp.message(Command("get_db"))
async def cmd_get_db(message: types.Message):
    """Команда для скачивания базы данных"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return
    
    try:
        if not os.path.exists(DB_PATH):
            await message.answer("❌ Файл базы данных не найден")
            return
        
        await message.answer_document(
            types.FSInputFile(DB_PATH),
            caption="📁 База данных бота"
        )
        logger.info(f"✅ База данных отправлена пользователю {message.from_user.id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки базы: {e}")
        await message.answer("❌ Ошибка при отправке базы данных")

@dp.message(F.text == "📊 Статистика")
async def handle_stats_button(message: types.Message):
    """Обработчик кнопки статистики"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return
    
    try:
        query = '''
            SELECT COUNT(*) as total_users,
                   (SELECT COUNT(*) FROM blocked_users) as blocked_users,
                   (SELECT COUNT(*) FROM reports) as total_reports,
                   (SELECT COUNT(*) FROM reports WHERE is_approved = TRUE) as approved_reports,
                   (SELECT COUNT(*) FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE) as pending_reports,
                   (SELECT COUNT(*) FROM chat_groups) as total_groups
            FROM bot_users
        '''
        result = DatabaseConnection.execute_query(query, fetch_one=True)
        
        if result:
            total_users, blocked_users, total_reports, approved_reports, pending_reports, total_groups = result
            
            stats_text = f"""
📊 <b>Статистика системы</b>

👥 Пользователей: {total_users}
🚫 Заблокировано: {blocked_users}
👥 Групп с ботом: {total_groups}

📨 Жалоб всего: {total_reports}
✅ Одобрено: {approved_reports}
⏳ На модерации: {pending_reports}
"""
            
            await message.answer(stats_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

@dp.message(F.text == "📥 Скачать БД")
async def handle_download_db(message: types.Message):
    """Обработчик кнопки скачивания базы данных"""
    await cmd_get_db(message)

@dp.message(F.text == "🔙 Назад")
async def handle_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🎯 Выберите действие:", reply_markup=get_user_keyboard(message.from_user.id))

@dp.message(F.text == "📝 Жалоба")
async def handle_complaint(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    if get_recent_reports_count(user_id) >= 5:
        await message.answer("❌ Максимум 5 жалоб в час!")
        return
    
    await state.set_state(UserStates.WAITING_FOR_USERNAME)
    await message.answer("👤 **Введите юзернейм:**\n(например: username)", reply_markup=back_keyboard)

@dp.message(UserStates.WAITING_FOR_USERNAME)
async def process_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    is_valid, validation_msg = validate_username(username)
    if not is_valid:
        await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
        return
    
    if message.from_user.username and message.from_user.username.lower() == username.lower():
        await message.answer("❌ Нельзя подать жалобу на самого себя!", reply_markup=get_user_keyboard(message.from_user.id))
        await state.clear()
        return
    
    await state.update_data(target_username=username)
    await state.set_state(UserStates.WAITING_FOR_COMMENT)
    await message.answer("📝 **Введите комментарий:**\n(например: «не отправил товар»)", reply_markup=back_keyboard)

@dp.message(UserStates.WAITING_FOR_COMMENT)
async def process_comment(message: types.Message, state: FSMContext):
    comment = message.text.strip()
    
    if len(comment) < 5:
        await message.answer("❌ Комментарий слишком короткий (минимум 5 символов). Попробуйте снова:", reply_markup=back_keyboard)
        return
    
    if len(comment) > 500:
        await message.answer("❌ Комментарий слишком длинный (максимум 500 символов). Попробуйте снова:", reply_markup=back_keyboard)
        return
    
    await state.update_data(comment=comment)
    await state.set_state(UserStates.WAITING_FOR_PROOF)
    await message.answer("📎 **Пришлите скриншот или нажмите 'Пропустить':**", reply_markup=proof_keyboard)

@dp.message(UserStates.WAITING_FOR_PROOF)
async def process_proof(message: types.Message, state: FSMContext):
    if message.text == "📎 Пропустить":
        await state.update_data(proof_photo=None)
        await state.set_state(UserStates.WAITING_FOR_STATUS)
        await message.answer("Выберите статус:", reply_markup=status_keyboard)
        return
    
    if message.text == "🔙 Назад":
        await state.set_state(UserStates.WAITING_FOR_COMMENT)
        await message.answer("📝 **Введите комментарий:**\n(например: «не отправил товар»)", reply_markup=back_keyboard)
        return
    
    if message.photo:
        proof_photo = message.photo[-1].file_id
        await state.update_data(proof_photo=proof_photo)
        await state.set_state(UserStates.WAITING_FOR_STATUS)
        await message.answer("📸 Доказательство сохранено! Выберите статус:", reply_markup=status_keyboard)
    else:
        await message.answer("❌ Отправьте фото или нажмите 'Пропустить'", reply_markup=proof_keyboard)

@dp.message(UserStates.WAITING_FOR_STATUS)
async def process_status(message: types.Message, state: FSMContext):
    status = message.text
    
    if status == "🔙 Назад":
        await state.set_state(UserStates.WAITING_FOR_PROOF)
        await message.answer("📎 **Пришлите скриншот или нажмите 'Пропустить':**", reply_markup=proof_keyboard)
        return
    
    if status == "другое":
        await state.set_state(UserStates.WAITING_FOR_CUSTOM_STATUS)
        await message.answer("✏️ **Введите свой вариант статуса:**", reply_markup=back_keyboard)
        return
    
    await save_report(message, state, status)

@dp.message(UserStates.WAITING_FOR_CUSTOM_STATUS)
async def process_custom_status(message: types.Message, state: FSMContext):
    custom_status = message.text.strip()
    
    if custom_status == "🔙 Назад":
        await state.set_state(UserStates.WAITING_FOR_STATUS)
        await message.answer("Выберите статус:", reply_markup=status_keyboard)
        return
    
    if len(custom_status) < 2:
        await message.answer("❌ Статус слишком короткий. Введите еще раз:", reply_markup=back_keyboard)
        return
    
    await save_report(message, state, custom_status)

async def save_report(message: types.Message, state: FSMContext, status: str):
    data = await state.get_data()
    
    report_id = add_report(
        message.from_user.id, 
        data['target_username'], 
        status, 
        data['comment'], 
        data.get('proof_photo')
    )
    
    if report_id:
        reporter_username = f"@{message.from_user.username}" if message.from_user.username else f"Пользователь (ID: {message.from_user.id})"
        
        admin_text = (f"🆕 Новая жалоба #{report_id}\n\n"
                     f"👤 **От кого:** {reporter_username}\n"
                     f"🚨 **На кого:** @{data['target_username']}\n"
                     f"📝 **Комментарий:** {data['comment']}\n"
                     f"🏷 **Статус:** {status}")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{report_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{report_id}")
        ]])
        
        for admin_id in ADMIN_IDS:
            try:
                if data.get('proof_photo'):
                    await bot.send_photo(admin_id, data['proof_photo'], caption=admin_text, reply_markup=keyboard)
                else:
                    await bot.send_message(admin_id, admin_text + "\n\n📸 Без доказательств", reply_markup=keyboard)
                logger.info(f"📨 Уведомление отправлено админу {admin_id} о жалобе #{report_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
        
        await message.answer("✅ **Жалоба отправлена на модерацию!**", reply_markup=get_user_keyboard(message.from_user.id))
    else:
        await message.answer("❌ Ошибка сохранения жалобы", reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

@dp.message(F.text == "🔍 Проверить")
async def handle_check(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    await state.set_state(UserStates.WAITING_CHECK_USERNAME)
    await message.answer("🔍 **Введите юзернейм для проверки:**", reply_markup=back_keyboard)

@dp.message(UserStates.WAITING_CHECK_USERNAME)
async def process_check_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    is_valid, validation_msg = validate_username(username)
    if not is_valid:
        await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
        return
    
    reports = get_user_reports(username)
    
    if not reports:
        await message.answer(f"ℹ️ По пользователю @{username} информации нет", reply_markup=get_user_keyboard(message.from_user.id))
    else:
        statuses = set()
        comments = []
        
        for status, comment, timestamp in reports:
            statuses.add(status)
            comments.append(f"• {comment} ({timestamp[:10]})")
        
        response = [
            f"🔍 **Информация о @{username}:**",
            f"🏷 **Статусы:** {', '.join(sorted(statuses))}",
            f"📝 **Комментарии:**",
            *comments[:3],
            f"📊 **Всего жалоб:** {len(reports)}"
        ]
        
        await message.answer("\n".join(response), reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

@dp.message(F.text == "ℹ️ Помощь")
async def handle_help(message: types.Message):
    help_text = f"""
📋 **Как пользоваться ботом:**

📝 **Жалоба** - нажмите кнопку и следуйте инструкциям
🔍 **Проверить** - узнайте информацию о пользователе
➕ **Добавить в чат** - добавить бота в группу

📋 **Команды в группе:**
/check @username - проверить пользователя
/info - информация о боте

⚠️ **Внимание:** 
- Максимум 5 жалоб в час
- Жалобы проходят модерацию
- Бот в группе показывает только одобренные жалобы
    """
    await message.answer(help_text, reply_markup=get_user_keyboard(message.from_user.id))

# === АДМИН ПАНЕЛЬ ===
@dp.message(F.text == "🛠 Админ")
async def handle_admin(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Показать жалобы", callback_data="admin_show_reports")],
        [InlineKeyboardButton(text="🚫 Заблокировать по @username", callback_data="admin_block_username")],
        [InlineKeyboardButton(text="✅ Разблокировать по @username", callback_data="admin_unblock_username")],
        [InlineKeyboardButton(text="📢 Сделать объявление", callback_data="admin_announcement")],
        [InlineKeyboardButton(text="🔄 Уведомление об обновлении", callback_data="admin_update_notify")],
        [InlineKeyboardButton(text="🗑️ Удалить информацию о пользователе", callback_data="admin_delete_user")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.answer("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)

@dp.callback_query(F.data == "admin_update_notify")
async def handle_admin_update_notify(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    users_count = len(get_all_users_for_broadcast())
    
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_update_notify")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_update_notify")]
    ])
    
    await callback.message.answer(
        f"🔄 <b>Отправка уведомления об обновлении</b>\n\n"
        f"📊 Будет отправлено: <b>{users_count}</b> пользователям\n\n"
        f"Сообщение:\n"
        f"• Об завершении обновления\n" 
        f"• С просьбой перезапустить бота командой /start\n\n"
        f"<b>Продолжить?</b>",
        reply_markup=confirm_keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "confirm_update_notify")
async def handle_confirm_update_notify(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.answer("🔄 Начинаю рассылку уведомлений об обновлении...")
    
    success_count, failed_count, blocked_bot_count = await send_update_notification()
    
    result_message = (
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего пользователей: {len(get_all_users_for_broadcast())}\n"
        f"✅ Успешно отправлено: {success_count}\n"
        f"❌ С ошибками: {failed_count}\n"
        f"🚫 Заблокировали бота: {blocked_bot_count}"
    )
    
    await callback.message.answer(result_message, parse_mode="HTML", reply_markup=get_user_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "cancel_update_notify")
async def handle_cancel_update_notify(callback: types.CallbackQuery):
    await callback.message.answer("❌ Рассылка отменена", reply_markup=get_user_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "admin_show_reports")
async def handle_admin_show_reports(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    pending_reports = get_pending_reports()
    
    if not pending_reports:
        await callback.message.answer("📭 Нет жалоб на модерации", reply_markup=get_user_keyboard(callback.from_user.id))
        await callback.answer()
        return
    
    await callback.message.answer(f"📋 Найдено {len(pending_reports)} жалоб на модерации:", reply_markup=get_user_keyboard(callback.from_user.id))
    
    for report in pending_reports:
        report_id, reporter_id, target_username, status, comment, proof_photo = report
        
        report_text = (f"🆕 Жалоба #{report_id}\n\n"
                      f"👤 **От кого:** ID {reporter_id}\n"
                      f"🚨 **На кого:** @{target_username}\n"
                      f"📝 **Комментарий:** {comment}\n"
                      f"🏷 **Статус:** {status}")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{report_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{report_id}")
        ]])
        
        try:
            if proof_photo:
                await callback.message.answer_photo(proof_photo, caption=report_text, reply_markup=keyboard)
            else:
                await callback.message.answer(report_text + "\n\n📸 Без доказательств", reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Ошибка отправки жалобы #{report_id}: {e}")
            await callback.message.answer(report_text + "\n\n❌ Ошибка загрузки доказательств", reply_markup=keyboard)
    
    await callback.answer()

@dp.callback_query(F.data == "admin_block_username")
async def handle_admin_block_username(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🚫 **Введите @username для блокировки:**\n(например: username)", reply_markup=back_keyboard)
    await state.set_state(AdminStates.WAITING_BLOCK_USERNAME)
    await callback.answer()

@dp.message(AdminStates.WAITING_BLOCK_USERNAME)
async def process_admin_block_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    user_id = get_user_id_by_username(username)
    if not user_id:
        await message.answer("❌ Пользователь не найден в базе бота.", reply_markup=get_user_keyboard(message.from_user.id))
        await state.clear()
        return
    
    await state.update_data(target_user_id=user_id, target_username=username)
    await state.set_state(AdminStates.WAITING_BLOCK_REASON)
    await message.answer("📝 **Введите причину блокировки:**", reply_markup=back_keyboard)

@dp.message(AdminStates.WAITING_BLOCK_REASON)
async def process_admin_block_reason(message: types.Message, state: FSMContext):
    reason = message.text
    data = await state.get_data()
    
    success, result_msg = block_user(data['target_user_id'], data['target_username'], reason, message.from_user.id)
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    
    try:
        await bot.send_message(data['target_user_id'], f"🚫 **Вы заблокированы!**\nПричина: {reason}")
    except:
        pass
    
    await state.clear()

@dp.callback_query(F.data == "admin_unblock_username")
async def handle_admin_unblock_username(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✅ **Введите @username для разблокировки:**\n(например: username)", reply_markup=back_keyboard)
    await state.set_state(AdminStates.WAITING_UNBLOCK_USERNAME)
    await callback.answer()

@dp.message(AdminStates.WAITING_UNBLOCK_USERNAME)
async def process_admin_unblock_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    user_id = get_user_id_by_username(username)
    if not user_id:
        await message.answer("❌ Пользователь не найден в базе бота.", reply_markup=get_user_keyboard(message.from_user.id))
        await state.clear()
        return
    
    success, result_msg = unblock_user(user_id)
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    
    try:
        await bot.send_message(user_id, "✅ **Вы разблокированы!**")
    except:
        pass
    
    await state.clear()

@dp.callback_query(F.data == "admin_announcement")
async def handle_admin_announcement(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 **Введите текст объявления:**", reply_markup=back_keyboard)
    await state.set_state(AdminStates.WAITING_ANNOUNCEMENT)
    await callback.answer()

@dp.message(AdminStates.WAITING_ANNOUNCEMENT)
async def process_admin_announcement(message: types.Message, state: FSMContext):
    text = message.text
    users = get_all_users_for_broadcast()
    success_count = 0
    
    await message.answer(f"📢 Начинаю рассылку для {len(users)} пользователей...")
    
    for index, user_id in enumerate(users, 1):
        try:
            if not is_user_blocked(user_id):
                await bot.send_message(user_id, f"📢 **Объявление:**\n\n{text}")
                success_count += 1
                if index % 10 == 0:
                    logger.info(f"📤 Отправлено {index}/{len(users)} объявлений")
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Не удалось отправить пользователю {user_id}: {e}")
    
    await message.answer(f"📢 **Объявление отправлено {success_count} пользователям**", reply_markup=get_user_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "admin_delete_user")
async def handle_admin_delete_user(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🗑️ **Введите @username для удаления информации:**\n(например: username)", reply_markup=back_keyboard)
    await state.set_state(AdminStates.WAITING_DELETE_USER)
    await callback.answer()

@dp.message(AdminStates.WAITING_DELETE_USER)
async def process_admin_delete_user(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    success, result_msg = delete_user_reports(username)
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "admin_stats")
async def handle_admin_stats(callback: types.CallbackQuery):
    try:
        query = '''
            SELECT COUNT(*) as total_users,
                   (SELECT COUNT(*) FROM blocked_users) as blocked_users,
                   (SELECT COUNT(*) FROM reports) as total_reports,
                   (SELECT COUNT(*) FROM reports WHERE is_approved = TRUE) as approved_reports,
                   (SELECT COUNT(*) FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE) as pending_reports,
                   (SELECT COUNT(*) FROM chat_groups) as total_groups
            FROM bot_users
        '''
        result = DatabaseConnection.execute_query(query, fetch_one=True)
        
        if result:
            total_users, blocked_users, total_reports, approved_reports, pending_reports, total_groups = result
            
            stats_text = f"""
📊 **Статистика системы:**

👥 Пользователей: {total_users}
📨 Всего жалоб: {total_reports}
✅ Одобрено: {approved_reports}
⏳ На модерации: {pending_reports}
🚫 Заблокировано: {blocked_users}
👥 Групп с ботом: {total_groups}
            """
            
            await callback.message.answer(stats_text, reply_markup=get_user_keyboard(callback.from_user.id))
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await callback.message.answer("❌ Ошибка получения статистики", reply_markup=get_user_keyboard(callback.from_user.id))
    
    await callback.answer()

# === МОДЕРАЦИЯ ЖАЛОБ ===
@dp.callback_query(F.data.startswith("approve_"))
async def handle_approve_report(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    report_id = int(callback.data.split("_")[1])
    reporter_id, target_username = approve_report(report_id, callback.from_user.id)
    
    if reporter_id:
        try:
            await bot.send_message(reporter_id, f"✅ Ваша жалоба на @{target_username} одобрена!")
        except:
            pass
        
        try:
            await callback.message.edit_caption(
                f"✅ **Жалоба одобрена**\n\n"
                f"👤 Пользователь: @{target_username}\n"
                f"👁 Модератор: {callback.from_user.id}",
                reply_markup=None
            )
        except:
            try:
                await callback.message.edit_text(
                    f"✅ **Жалоба одобрена**\n\n"
                    f"👤 Пользователь: @{target_username}\n"
                    f"👁 Модератор: {callback.from_user.id}",
                    reply_markup=None
                )
            except:
                pass
    else:
        await callback.answer("❌ Жалоба уже обработана", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_"))
async def handle_reject_report(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    report_id = int(callback.data.split("_")[1])
    reporter_id = reject_report(report_id, callback.from_user.id)
    
    if reporter_id:
        try:
            await bot.send_message(reporter_id, "❌ Ваша жалоба отклонена.")
        except:
            pass
        
        try:
            await callback.message.edit_caption(
                f"❌ **Жалоба отклонена**\n\n"
                f"👁 Модератор: {callback.from_user.id}",
                reply_markup=None
            )
        except:
            try:
                await callback.message.edit_text(
                    f"❌ **Жалоба отклонена**\n\n"
                    f"👁 Модератор: {callback.from_user.id}",
                    reply_markup=None
                )
            except:
                pass
    else:
        await callback.answer("❌ Жалоба уже обработана", show_alert=True)
    
    await callback.answer()

# === ЗАПУСК БОТА ===
async def main():
    """Основная функция запуска бота"""
    # Инициализируем БД
    init_db()
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    global BOT_USERNAME
    BOT_USERNAME = bot_info.username
    logger.info(f"🤖 Бот: @{BOT_USERNAME}")
    
    logger.info("🤖 Бот запускается...")
    logger.info(f"👑 Администраторы: {ADMIN_IDS}")
    
    # Устанавливаем команды бота
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Запустить бота"),
        types.BotCommand(command="check", description="Проверить пользователя (@username)"),
        types.BotCommand(command="info", description="Информация о боте"),
        types.BotCommand(command="help", description="Помощь")
    ])
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Все предыдущие сессии завершены")
        
        await asyncio.sleep(2)
        
        logger.info("🔄 Запускаем поллинг...")
        await dp.start_polling(bot, skip_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        await asyncio.sleep(10)
        await main()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
