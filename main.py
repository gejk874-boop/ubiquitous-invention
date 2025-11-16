import asyncio
import sqlite3
import logging
import sys
import re
import os
import gc
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ===== НАСТРОЙКА =====
BOT_TOKEN = "8223288154:AAEGGJGOXzIAUNRocxzKL7x-IAUhVfEb-xw"
ADMIN_IDS = [6986121067]

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ===== СОСТОЯНИЯ =====
class UserStates(StatesGroup):
    WAITING_FOR_USERNAME = State()
    WAITING_FOR_COMMENT = State()
    WAITING_FOR_PROOF = State()
    WAITING_FOR_STATUS = State()
    WAITING_FOR_CUSTOM_STATUS = State()
    WAITING_CHECK_USERNAME = State()

class AdminStates(StatesGroup):
    WAITING_BLOCK_USER = State()
    WAITING_BLOCK_REASON = State()
    WAITING_UNBLOCK_USER = State()
    WAITING_DELETE_USER = State()
    WAITING_ANNOUNCEMENT = State()
    WAITING_BLOCK_BY_USERNAME = State()
    WAITING_UNBLOCK_BY_USERNAME = State()

# ===== БАЗА ДАННЫХ =====
def init_db():
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        
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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_username ON reports(target_username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_approved ON reports(is_approved)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocked_user ON blocked_users(user_id)')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка БД: {e}")

def add_bot_user(user_id, username, first_name, last_name):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO bot_users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка добавления пользователя: {e}")

def get_all_bot_users():
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username FROM bot_users')
        users = cursor.fetchall()
        conn.close()
        return users
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователей: {e}")
        return []

def get_user_id_by_username(username):
    """Получить ID пользователя по username"""
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM bot_users WHERE username = ?', (username.lower(),))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Ошибка получения ID по username: {e}")
        return None

def add_report(reporter_id, target_username, status, comment, proof_photo=None):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reports (reporter_id, target_username, status, comment, proof_photo)
            VALUES (?, ?, ?, ?, ?)
        ''', (reporter_id, target_username.lower(), status, comment, proof_photo))
        report_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"✅ Добавлена жалоба #{report_id} от {reporter_id} на {target_username}")
        return report_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления: {e}")
        return None

def approve_report(report_id, moderator_id):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('SELECT is_approved, is_rejected FROM reports WHERE id = ?', (report_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return None, None
            
        if result[0] or result[1]:
            conn.close()
            return None, None
        
        cursor.execute('''
            UPDATE reports 
            SET is_approved = TRUE, moderator_id = ?
            WHERE id = ?
        ''', (moderator_id, report_id))
        conn.commit()
        
        cursor.execute('SELECT reporter_id, target_username FROM reports WHERE id = ?', (report_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result[0], result[1]
        return None, None
    except Exception as e:
        logger.error(f"❌ Ошибка одобрения: {e}")
        return None, None

def reject_report(report_id, moderator_id):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('SELECT is_approved, is_rejected FROM reports WHERE id = ?', (report_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return None
            
        if result[0] or result[1]:
            conn.close()
            return None
        
        cursor.execute('''
            UPDATE reports 
            SET is_rejected = TRUE, moderator_id = ?
            WHERE id = ?
        ''', (moderator_id, report_id))
        conn.commit()
        
        cursor.execute('SELECT reporter_id FROM reports WHERE id = ?', (report_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result[0]
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка отклонения: {e}")
        return None

def get_pending_reports():
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, reporter_id, target_username, status, comment, proof_photo
            FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE
            ORDER BY timestamp DESC
        ''')
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        logger.error(f"❌ Ошибка получения: {e}")
        return []

def get_user_reports(target_username):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT status, comment, timestamp FROM reports 
            WHERE target_username = ? AND is_approved = TRUE
            ORDER BY timestamp DESC
        ''', (target_username.lower(),))
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        logger.error(f"❌ Ошибка получения: {e}")
        return []

def block_user(user_id, username, reason, blocked_by):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM blocked_users WHERE user_id = ?', (user_id,))
        if cursor.fetchone():
            conn.close()
            return False, "❌ Пользователь уже заблокирован"
            
        cursor.execute('''
            INSERT INTO blocked_users (user_id, username, reason, blocked_by)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, reason, blocked_by))
        conn.commit()
        conn.close()
        logger.info(f"✅ Пользователь {user_id} (@{username}) заблокирован. Причина: {reason}")
        return True, f"✅ Пользователь @{username} успешно заблокирован"
    except Exception as e:
        logger.error(f"❌ Ошибка блокировки: {e}")
        return False, f"❌ Ошибка блокировки: {e}"

def unblock_user(user_id):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM blocked_users WHERE user_id = ?', (user_id,))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected > 0:
            logger.info(f"✅ Пользователь {user_id} разблокирован")
            return True, f"✅ Пользователь успешно разблокирован"
        else:
            return False, "❌ Пользователь не найден в списке заблокированных"
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки: {e}")
        return False, f"❌ Ошибка разблокировки: {e}"

def unblock_user_by_username(username):
    """Разблокировать пользователя по username"""
    try:
        user_id = get_user_id_by_username(username)
        if not user_id:
            return False, "❌ Пользователь с таким username не найден"
        
        return unblock_user(user_id)
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки по username: {e}")
        return False, f"❌ Ошибка разблокировки: {e}"

def is_user_blocked(user_id):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, reason FROM blocked_users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            logger.info(f"🔒 Пользователь {user_id} заблокирован. Причина: {result[2]}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки блокировки: {e}")
        return False

def get_recent_reports_count(reporter_id, hours=1):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        time_threshold = datetime.now() - timedelta(hours=hours)
        cursor.execute('''
            SELECT COUNT(*) FROM reports 
            WHERE reporter_id = ? AND timestamp > ?
        ''', (reporter_id, time_threshold))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"❌ Ошибка подсчета: {e}")
        return 0

def delete_user_reports(target_username):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM reports WHERE target_username = ?', (target_username.lower(),))
        rows_deleted = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"🗑️ Удалено {rows_deleted} жалоб на @{target_username}")
        return True, f"✅ Удалено {rows_deleted} жалоб на @{target_username}"
    except Exception as e:
        logger.error(f"❌ Ошибка удаления жалоб: {e}")
        return False, f"❌ Ошибка удаления: {e}"

# ===== КЛАВИАТУРЫ =====
def get_user_keyboard(user_id):
    keyboard = [
        [KeyboardButton(text="📝 Жалоба"), KeyboardButton(text="🔍 Проверить")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton(text="🛠 Админ")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

status_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="обманщик"), KeyboardButton(text="ненадёжный")],
        [KeyboardButton(text="мошенник"), KeyboardButton(text="другое")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

back_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

# ===== ВАЛИДАЦИЯ =====
def validate_username(username):
    if not username or len(username) < 3:
        return False, "❌ Юзернейм слишком короткий (минимум 3 символа)"
    
    if len(username) > 32:
        return False, "❌ Юзернейм слишком длинный (максимум 32 символа)"
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "❌ Юзернейм может содержать только буквы, цифры и подчеркивания"
    
    return True, "✅ Юзернейм корректен"

# ===== ПРОВЕРКА БЛОКИРОВКИ =====
async def check_user_blocked(user_id: int, message: Message = None, callback: CallbackQuery = None) -> bool:
    """Проверка блокировки пользователя"""
    if is_user_blocked(user_id):
        if message:
            await message.answer("❌ Вы заблокированы в системе.")
        if callback:
            await callback.answer("❌ Вы заблокированы в системе.", show_alert=True)
        return True
    return False

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def cmd_start(message: Message):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            return
        
        add_bot_user(
            user_id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name
        )
        
        welcome_text = """
🎯 **Добро пожаловать в бот проверки пользователей!**

Выберите действие с помощью кнопок ниже:

📝 **Жалоба** - сообщить о ненадежном пользователе
🔍 **Проверить** - узнайте информацию о пользователе  
ℹ️ **Помощь** - получите справку по работе бота
        """
        await message.answer(welcome_text, reply_markup=get_user_keyboard(user_id))
        logger.info(f"👤 Пользователь {user_id} запустил бота")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в cmd_start: {e}")
        await message.answer("❌ Произошла ошибка при запуске бота")

@dp.message(F.text == "🔙 Назад")
async def handle_back(message: Message, state: FSMContext):
    user_id = message.from_user.id
    current_state = await state.get_state()
    
    if await check_user_blocked(user_id, message=message):
        return
    
    # Если админ в админ-состоянии - возврат в админ-панель
    if user_id in ADMIN_IDS and current_state and "AdminStates" in current_state:
        await handle_admin_button(message)
    else:
        # Обычный пользователь - в главное меню
        await message.answer(
            "🎯 Выберите действие с помощью кнопок ниже:",
            reply_markup=get_user_keyboard(user_id)
        )
    
    await state.clear()

@dp.message(F.text == "📝 Жалоба")
async def handle_complaint_button(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            return
        
        recent_count = get_recent_reports_count(user_id)
        if recent_count >= 5:
            await message.answer(
                "❌ **Превышен лимит!**\n"
                "Максимум 5 жалоб в час!\n"
                "Жалобы проходят модерацию перед публикацией."
            )
            return
        
        await state.set_state(UserStates.WAITING_FOR_USERNAME)
        await state.update_data(user_data={})
        
        await message.answer(
            "👤 **Введите юзернейм человека, о котором хотите сообщить:**\n"
            "(например: @username или просто username)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад'",
            reply_markup=back_keyboard
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_complaint_button: {e}")
        await message.answer("❌ Произошла ошибка при создании жалобы")

@dp.message(F.text == "🔍 Проверить")
async def handle_check_button(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            return
        
        await state.set_state(UserStates.WAITING_CHECK_USERNAME)
        
        await message.answer(
            "🔍 **Введите юзернейм для проверки:**\n"
            "(например: @username или просто username)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад'",
            reply_markup=back_keyboard
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_check_button: {e}")
        await message.answer("❌ Произошла ошибка при проверке")

@dp.message(F.text == "ℹ️ Помощь")
async def handle_help_button(message: Message):
    try:
        if await check_user_blocked(message.from_user.id, message=message):
            return
            
        help_text = """
📋 **Как пользоваться ботом:**

📝 **Жалоба** - нажмите кнопку и следуйте инструкциям:
1. Введите юзернейм (@username)
2. Напишите комментарий
3. Пришлите скриншот (по желанию)
4. Выберите статус

🔍 **Проверить** - узнайте информацию о пользователе

⚠️ **Внимание:** 
- Максимум 5 жалоб в час
- Жалобы проходят модерацию
- Ложные жалобы могут привести к блокировке
        """
        await message.answer(help_text, reply_markup=get_user_keyboard(message.from_user.id))
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_help_button: {e}")
        await message.answer("❌ Произошла ошибка при показе справки")

@dp.message(F.text == "🛠 Админ")
async def handle_admin_button(message: Message):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            return
            
        if user_id not in ADMIN_IDS:
            await message.answer("❌ У вас нет доступа к админ-панели.")
            return
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Показать жалобы", callback_data="admin_show_reports")],
            [InlineKeyboardButton(text="🗑️ Удалить жалобы на пользователя", callback_data="admin_delete_user")],
            [InlineKeyboardButton(text="📢 Сделать объявление", callback_data="admin_announcement")],
            [InlineKeyboardButton(text="🚫 Заблокировать по ID", callback_data="admin_block")],
            [InlineKeyboardButton(text="🚫 Заблокировать по @username", callback_data="admin_block_username")],
            [InlineKeyboardButton(text="✅ Разблокировать по ID", callback_data="admin_unblock")],
            [InlineKeyboardButton(text="✅ Разблокировать по @username", callback_data="admin_unblock_username")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="admin_back_to_main")]
        ])
        
        await message.answer("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_admin_button: {e}")
        await message.answer("❌ Произошла ошибка при открытии админ-панели")

# ===== ОБРАБОТКА СОСТОЯНИЙ ПОЛЬЗОВАТЕЛЯ =====
@dp.message(UserStates.WAITING_CHECK_USERNAME)
async def process_check_username(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if text.startswith('@'):
            text = text[1:]
        
        is_valid, validation_msg = validate_username(text)
        if not is_valid:
            await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
            return
        
        reports = get_user_reports(text)
        
        if not reports:
            await message.answer(f"ℹ️ По пользователю @{text} информации нет", reply_markup=get_user_keyboard(user_id))
        else:
            statuses = set()
            comments = []
            
            for status, comment, timestamp in reports:
                statuses.add(status)
                comments.append(f"• {comment} ({timestamp[:10]})")
            
            response = [
                f"🔍 **Информация о пользователе:**",
                f"👤 **Юзернейм:** @{text}",
                f"🏷 **Статусы:** {', '.join(sorted(statuses))}",
                f"📝 **Комментарии ({len(comments)}):**",
                *comments[:5],
                f"📊 **Всего подтвержденных заявок:** {len(reports)}"
            ]
            
            await message.answer("\n".join(response), reply_markup=get_user_keyboard(user_id))
            logger.info(f"🔍 Проверка пользователя @{text}: найдено {len(reports)} жалоб")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"❌ Ошибка в process_check_username: {e}")
        await message.answer("❌ Произошла ошибка при проверке")

@dp.message(UserStates.WAITING_FOR_USERNAME)
async def process_complaint_username(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if text.startswith('@'):
            text = text[1:]
        
        is_valid, validation_msg = validate_username(text)
        if not is_valid:
            await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
            return
        
        user_username = message.from_user.username
        if user_username and user_username.lower() == text.lower():
            await message.answer(
                "❌ Нельзя подать жалобу на самого себя!",
                reply_markup=get_user_keyboard(user_id)
            )
            await state.clear()
            return
        
        await state.update_data(target_username=text)
        await state.set_state(UserStates.WAITING_FOR_COMMENT)
        
        await message.answer(
            "📝 **Введите комментарий:**\n(например: «не отправил товар»)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад'",
            reply_markup=back_keyboard
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка в process_complaint_username: {e}")
        await message.answer("❌ Произошла ошибка при обработке юзернейма")

@dp.message(UserStates.WAITING_FOR_COMMENT)
async def process_complaint_comment(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if not text or len(text) < 5:
            await message.answer("❌ Комментарий слишком короткий (минимум 5 символов). Попробуйте снова:", reply_markup=back_keyboard)
            return
        
        if len(text) > 500:
            await message.answer("❌ Комментарий слишком длинный (максимум 500 символов). Попробуйте снова:", reply_markup=back_keyboard)
            return
        
        await state.update_data(comment=text)
        await state.set_state(UserStates.WAITING_FOR_PROOF)
        
        await message.answer(
            "📎 **Пришлите скриншот или фото как доказательство.**\n"
            "Если доказательств нет, отправьте текст 'пропустить'\n\n"
            "Для отмены нажмите кнопку '🔙 Назад'",
            reply_markup=back_keyboard
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка в process_complaint_comment: {e}")
        await message.answer("❌ Произошла ошибка при обработке комментария")

@dp.message(UserStates.WAITING_FOR_PROOF)
async def process_complaint_proof(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        if message.text and message.text.lower() == 'пропустить':
            await state.update_data(proof_photo=None)
            await state.set_state(UserStates.WAITING_FOR_STATUS)
            await message.answer(
                "Вы пропустили добавление доказательства. Теперь выберите статус:",
                reply_markup=status_keyboard
            )
        elif message.photo:
            proof_photo = message.photo[-1].file_id
            await state.update_data(proof_photo=proof_photo)
            await state.set_state(UserStates.WAITING_FOR_STATUS)
            await message.answer(
                "📸 Доказательство сохранено! Теперь выберите статус:",
                reply_markup=status_keyboard
            )
        else:
            await message.answer("❌ Отправьте фото как доказательство или напишите 'пропустить'", reply_markup=back_keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в process_complaint_proof: {e}")
        await message.answer("❌ Произошла ошибка при обработке доказательства")

@dp.message(UserStates.WAITING_FOR_STATUS)
async def process_complaint_status(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if text == "другое":
            await state.set_state(UserStates.WAITING_FOR_CUSTOM_STATUS)
            await message.answer(
                "Введите свой вариант статуса:\n\n"
                "Для отмены нажмите кнопку '🔙 Назад'",
                reply_markup=back_keyboard
            )
        elif text == "🔙 Назад":
            await state.set_state(UserStates.WAITING_FOR_PROOF)
            await message.answer(
                "📎 **Пришлите скриншот или фото как доказательство.**\n"
                "Если доказательств нет, отправьте текст 'пропустить'",
                reply_markup=back_keyboard
            )
        else:
            await save_report(message, state, text)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в process_complaint_status: {e}")
        await message.answer("❌ Произошла ошибка при выборе статуса")

@dp.message(UserStates.WAITING_FOR_CUSTOM_STATUS)
async def process_complaint_custom_status(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if text == "🔙 Назад":
            await state.set_state(UserStates.WAITING_FOR_STATUS)
            await message.answer(
                "Выберите статус:",
                reply_markup=status_keyboard
            )
        else:
            await save_report(message, state, text)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в process_complaint_custom_status: {e}")
        await message.answer("❌ Произошла ошибка при обработке статуса")

async def save_report(message: Message, state: FSMContext, status: str):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        data = await state.get_data()
        
        target_username = data['target_username']
        comment = data['comment']
        proof_photo = data.get('proof_photo')
        
        report_id = add_report(user_id, target_username, status, comment, proof_photo)
        
        if report_id:
            admin_text = (
                f"🆕 Новая жалоба #{report_id}\n"
                f"👤 На: @{target_username}\n"
                f"📝 Комментарий: {comment}\n"
                f"🏷 Статус: {status}\n"
                f"👥 От: {user_id}"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{report_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{report_id}")
            ]])
            
            if proof_photo:
                await bot.send_photo(
                    ADMIN_IDS[0],
                    proof_photo,
                    caption=admin_text,
                    reply_markup=keyboard
                )
            else:
                await bot.send_message(
                    ADMIN_IDS[0],
                    admin_text + "\n\n📸 Без доказательств",
                    reply_markup=keyboard
                )
            
            await message.answer(
                "✅ **Жалоба отправлена на модерацию!**\n"
                "Вы получите уведомление когда её проверят.",
                reply_markup=get_user_keyboard(user_id)
            )
        else:
            await message.answer("❌ Ошибка сохранения заявки", reply_markup=get_user_keyboard(user_id))
        
        await state.clear()
        logger.info(f"📨 Отправлена на модерацию жалоба от {user_id} на {target_username}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении жалобы: {e}")
        await message.answer("❌ Ошибка при сохранении заявки", reply_markup=get_user_keyboard(message.from_user.id))

# ===== ОБРАБОТКА CALLBACK QUERIES =====
@dp.callback_query(F.data.startswith("approve_"))
async def handle_approve_callback(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        report_id = int(callback.data.split("_")[1])
        reporter_id, target_username = approve_report(report_id, user_id)
        
        if reporter_id:
            try:
                await bot.send_message(
                    reporter_id,
                    f"✅ Ваша жалоба на @{target_username} была одобрена модератором и добавлена в базу."
                )
            except Exception as e:
                logger.error(f"❌ Ошибка уведомления пользователя {reporter_id}: {e}")
            
            await callback.message.edit_text(
                f"✅ Жалоба #{report_id} одобрена\n"
                f"Пользователь @{target_username} уведомлен"
            )
            await callback.answer("Жалоба одобрена")
        else:
            await callback.answer("❌ Ошибка одобрения или жалоба уже обработана", show_alert=True)
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки approve callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("reject_"))
async def handle_reject_callback(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        report_id = int(callback.data.split("_")[1])
        reporter_id = reject_report(report_id, user_id)
        
        if reporter_id:
            try:
                await bot.send_message(
                    reporter_id,
                    "❌ Ваша жалоба была отклонена модератором из-за недостаточных доказательств."
                )
            except Exception as e:
                logger.error(f"❌ Ошибка уведомления пользователя {reporter_id}: {e}")
            
            await callback.message.edit_text(f"❌ Жалоба #{report_id} отклонена")
            await callback.answer("Жалоба отклонена")
        else:
            await callback.answer("❌ Ошибка отклонения или жалоба уже обработана", show_alert=True)
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки reject callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_show_reports")
async def handle_admin_show_reports(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        reports = get_pending_reports()
        if not reports:
            await callback.message.edit_text("📭 Нет жалоб ожидающих модерации")
        else:
            text = f"📋 Жалобы на модерации ({len(reports)}):\n\n"
            for report in reports[:10]:
                report_id, reporter_id, target_username, status, comment, proof_photo = report
                proof_text = "📸" if proof_photo else "📝"
                text += f"#{report_id} {proof_text} @{target_username}\n{status}: {comment[:100]}...\n\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="admin_back")
            ]])
            await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_show_reports: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_delete_user")
async def handle_admin_delete_user(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        await state.set_state(AdminStates.WAITING_DELETE_USER)
        await callback.message.edit_text(
            "👤 **Введите юзернейм пользователя для удаления ВСЕХ жалоб:**\n"
            "(например: @username или просто username)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад' в основном чате"
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_delete_user: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_announcement")
async def handle_admin_announcement(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        await state.set_state(AdminStates.WAITING_ANNOUNCEMENT)
        await callback.message.edit_text(
            "📢 **Введите текст объявления для всех пользователей:**\n\n"
            "Для отмены нажмите кнопку '🔙 Назад' в основном чате"
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_announcement: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_block")
async def handle_admin_block(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        await state.set_state(AdminStates.WAITING_BLOCK_USER)
        await callback.message.edit_text(
            "🚫 **Введите ID пользователя для блокировки:**\n(только число)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад' в основном чате"
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_block: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_block_username")
async def handle_admin_block_username(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        await state.set_state(AdminStates.WAITING_BLOCK_BY_USERNAME)
        await callback.message.edit_text(
            "🚫 **Введите @username пользователя для блокировки:**\n"
            "(например: @username или просто username)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад' в основном чате"
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_block_username: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_unblock")
async def handle_admin_unblock(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        await state.set_state(AdminStates.WAITING_UNBLOCK_USER)
        await callback.message.edit_text(
            "✅ **Введите ID пользователя для разблокировки:**\n(только число)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад' в основном чате"
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_unblock: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_unblock_username")
async def handle_admin_unblock_username(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        await state.set_state(AdminStates.WAITING_UNBLOCK_BY_USERNAME)
        await callback.message.edit_text(
            "✅ **Введите @username пользователя для разблокировки:**\n"
            "(например: @username или просто username)\n\n"
            "Для отмены нажмите кнопку '🔙 Назад' в основном чате"
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_unblock_username: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_stats")
async def handle_admin_stats(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM reports WHERE is_approved = TRUE')
        approved = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE')
        pending = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM blocked_users')
        blocked = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT target_username) FROM reports WHERE is_approved = TRUE')
        unique_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reports')
        total_reports = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM bot_users')
        total_bot_users = cursor.fetchone()[0]
        
        conn.close()
        
        stats_text = (
            f"📊 **Статистика системы:**\n\n"
            f"📨 Всего жалоб: {total_reports}\n"
            f"✅ Одобренных жалоб: {approved}\n"
            f"⏳ Ожидают модерации: {pending}\n"
            f"👤 Уникальных пользователей в базе: {unique_users}\n"
            f"👥 Пользователей бота: {total_bot_users}\n"
            f"🚫 Заблокировано пользователей: {blocked}"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="admin_back")
        ]])
        await callback.message.edit_text(stats_text, reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_stats: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_back")
async def handle_admin_back(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Показать жалобы", callback_data="admin_show_reports")],
            [InlineKeyboardButton(text="🗑️ Удалить жалобы на пользователя", callback_data="admin_delete_user")],
            [InlineKeyboardButton(text="📢 Сделать объявление", callback_data="admin_announcement")],
            [InlineKeyboardButton(text="🚫 Заблокировать по ID", callback_data="admin_block")],
            [InlineKeyboardButton(text="🚫 Заблокировать по @username", callback_data="admin_block_username")],
            [InlineKeyboardButton(text="✅ Разблокировать по ID", callback_data="admin_unblock")],
            [InlineKeyboardButton(text="✅ Разблокировать по @username", callback_data="admin_unblock_username")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="admin_back_to_main")]
        ])
        
        await callback.message.edit_text("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_back: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_back_to_main")
async def handle_admin_back_to_main(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        
        if await check_user_blocked(user_id, callback=callback):
            return
            
        if user_id not in ADMIN_IDS:
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        await callback.message.edit_text("Возвращаюсь в главное меню...")
        await bot.send_message(
            user_id,
            "🎯 Выберите действие с помощью кнопок ниже:",
            reply_markup=get_user_keyboard(user_id)
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки admin_back_to_main: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

# ===== ОБРАБОТКА АДМИНСКИХ СОСТОЯНИЙ =====
@dp.message(AdminStates.WAITING_DELETE_USER)
async def process_admin_delete_user(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if text.startswith('@'):
            text = text[1:]
        
        is_valid, validation_msg = validate_username(text)
        if not is_valid:
            await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
            return
        
        success, result_msg = delete_user_reports(text)
        await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
        await state.clear()
    
    except Exception as e:
        logger.error(f"❌ Ошибка в process_admin_delete_user: {e}")
        await message.answer("❌ Произошла ошибка при удалении жалоб")

@dp.message(AdminStates.WAITING_ANNOUNCEMENT)
async def process_admin_announcement(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        users = get_all_bot_users()
        success_count = 0
        fail_count = 0
        
        announcement_text = f"📢 **Объявление от администратора:**\n\n{text}"
        
        for user_id, username in users:
            try:
                # Пропускаем заблокированных пользователей
                if is_user_blocked(user_id):
                    continue
                    
                await bot.send_message(user_id, announcement_text)
                success_count += 1
                # Небольшая задержка чтобы не превысить лимиты
                await asyncio.sleep(0.1)
            except Exception as e:
                fail_count += 1
                logger.error(f"❌ Ошибка отправки объявления пользователю {user_id} (@{username}): {e}")
        
        await message.answer(
            f"📢 **Объявление отправлено!**\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Не удалось: {fail_count}",
            reply_markup=get_user_keyboard(message.from_user.id)
        )
        await state.clear()
    
    except Exception as e:
        logger.error(f"❌ Ошибка в process_admin_announcement: {e}")
        await message.answer("❌ Произошла ошибка при рассылке объявления")

@dp.message(AdminStates.WAITING_BLOCK_USER)
async def process_admin_block_user(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        try:
            target_id = int(text)
            await state.update_data(block_target_id=target_id)
            await state.set_state(AdminStates.WAITING_BLOCK_REASON)
            
            await message.answer(
                "Введите причину блокировки:\n\n"
                "Для отмены нажмите кнопку '🔙 Назад'",
                reply_markup=back_keyboard
            )
        except ValueError:
            await message.answer("❌ Введите числовой ID пользователя:", reply_markup=back_keyboard)
    
    except Exception as e:
        logger.error(f"❌ Ошибка в process_admin_block_user: {e}")
        await message.answer("❌ Произошла ошибка при блокировке")

@dp.message(AdminStates.WAITING_BLOCK_REASON)
async def process_admin_block_reason(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        data = await state.get_data()
        target_id = data['block_target_id']
        
        # Получаем информацию о пользователе
        try:
            target_user = await bot.get_chat(target_id)
            username = target_user.username or f"user_{target_id}"
        except:
            username = f"user_{target_id}"
        
        success, result_msg = block_user(target_id, username, text, message.from_user.id)
        await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
        
        # Уведомление заблокированному пользователю
        try:
            await bot.send_message(
                target_id,
                f"🚫 **Вы были заблокированы в системе!**\n\n"
                f"Причина: {text}\n"
                f"По всем вопросам обращайтесь к администратору."
            )
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить пользователя {target_id} о блокировке: {e}")
        
        await state.clear()
    
    except Exception as e:
        logger.error(f"❌ Ошибка в process_admin_block_reason: {e}")
        await message.answer("❌ Произошла ошибка при блокировке")

@dp.message(AdminStates.WAITING_BLOCK_BY_USERNAME)
async def process_admin_block_by_username(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if text.startswith('@'):
            text = text[1:]
        
        is_valid, validation_msg = validate_username(text)
        if not is_valid:
            await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
            return
        
        # Получаем ID пользователя по username
        target_id = get_user_id_by_username(text)
        if not target_id:
            await message.answer("❌ Пользователь с таким username не найден в базе бота.", reply_markup=back_keyboard)
            return
        
        await state.update_data(block_target_id=target_id, block_target_username=text)
        await state.set_state(AdminStates.WAITING_BLOCK_REASON)
        
        await message.answer(
            f"👤 Найден пользователь: @{text} (ID: {target_id})\n\n"
            "Введите причину блокировки:\n\n"
            "Для отмены нажмите кнопку '🔙 Назад'",
            reply_markup=back_keyboard
        )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в process_admin_block_by_username: {e}")
        await message.answer("❌ Произошла ошибка при блокировке")

@dp.message(AdminStates.WAITING_UNBLOCK_USER)
async def process_admin_unblock_user(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        try:
            target_id = int(text)
            success, result_msg = unblock_user(target_id)
            await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
            
            # Уведомление разблокированному пользователю
            try:
                await bot.send_message(
                    target_id,
                    "✅ **Ваша блокировка снята!**\n\n"
                    "Теперь вы снова можете пользоваться ботом."
                )
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя {target_id} о разблокировке: {e}")
                
        except ValueError:
            await message.answer("❌ Введите числовой ID пользователя", reply_markup=get_user_keyboard(message.from_user.id))
        
        await state.clear()
    
    except Exception as e:
        logger.error(f"❌ Ошибка в process_admin_unblock_user: {e}")
        await message.answer("❌ Произошла ошибка при разблокировке")

@dp.message(AdminStates.WAITING_UNBLOCK_BY_USERNAME)
async def process_admin_unblock_by_username(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if await check_user_blocked(user_id, message=message):
            await state.clear()
            return
            
        text = message.text.strip()
        
        if text.startswith('@'):
            text = text[1:]
        
        is_valid, validation_msg = validate_username(text)
        if not is_valid:
            await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
            return
        
        success, result_msg = unblock_user_by_username(text)
        await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
        
        # Уведомление разблокированному пользователю
        try:
            target_id = get_user_id_by_username(text)
            if target_id:
                await bot.send_message(
                    target_id,
                    "✅ **Ваша блокировка снята!**\n\n"
                    "Теперь вы снова можете пользоваться ботом."
                )
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить пользователя о разблокировке: {e}")
        
        await state.clear()
    
    except Exception as e:
        logger.error(f"❌ Ошибка в process_admin_unblock_by_username: {e}")
        await message.answer("❌ Произошла ошибка при разблокировке")

# ===== ЗАПУСК =====
async def main():
    print("🚀 Starting bot...")
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
