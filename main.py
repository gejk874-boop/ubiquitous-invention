import asyncio
import sqlite3
import logging
import sys
import re
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ===== НАСТРОЙКА =====
BOT_TOKEN = "8223288154:AAEGGJGOXzIAUNRocxzKL7x-IAUhVfEb-xw"
ADMIN_IDS = [6986121067]

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
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
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM bot_users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Ошибка получения ID по username: {e}")
        return None

def get_user_by_username(username):
    """Получить информацию о пользователе по username"""
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username FROM bot_users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка поиска пользователя: {e}")
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
        return report_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления: {e}")
        return None

def approve_report(report_id, moderator_id):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE reports SET is_approved = TRUE, moderator_id = ?
            WHERE id = ? AND is_approved = FALSE AND is_rejected = FALSE
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
        cursor.execute('''
            UPDATE reports SET is_rejected = TRUE, moderator_id = ?
            WHERE id = ? AND is_approved = FALSE AND is_rejected = FALSE
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
        return True, f"✅ Пользователь @{username} заблокирован"
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
            return True, f"✅ Пользователь разблокирован"
        else:
            return False, "❌ Пользователь не найден"
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки: {e}")
        return False, f"❌ Ошибка разблокировки: {e}"

def unblock_user_by_username(username):
    """Разблокировка пользователя по username"""
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        
        # Ищем пользователя в таблице blocked_users
        cursor.execute('SELECT user_id FROM blocked_users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return unblock_user(result[0])
        else:
            # Если не нашли по username, пробуем найти в bot_users и затем в blocked_users
            user_id = get_user_id_by_username(username)
            if user_id:
                return unblock_user(user_id)
            else:
                return False, "❌ Пользователь не найден в заблокированных"
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки по username: {e}")
        return False, f"❌ Ошибка разблокировки: {e}"

def is_user_blocked(user_id):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM blocked_users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка проверки блокировки: {e}")
        return False

def get_recent_reports_count(reporter_id, hours=1):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        time_threshold = datetime.now() - timedelta(hours=hours)
        cursor.execute('SELECT COUNT(*) FROM reports WHERE reporter_id = ? AND timestamp > ?', (reporter_id, time_threshold))
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

def validate_username(username):
    if not username or len(username) < 3:
        return False, "❌ Юзернейм слишком короткий"
    if len(username) > 32:
        return False, "❌ Юзернейм слишком длинный"
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "❌ Юзернейм может содержать только буквы, цифры и подчеркивания"
    return True, "✅ Юзернейм корректен"

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    add_bot_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    
    welcome_text = """
🎯 **Добро пожаловать в бот проверки пользователей!**

📝 **Жалоба** - сообщить о ненадежном пользователе
🔍 **Проверить** - узнайте информацию о пользователе  
ℹ️ **Помощь** - получите справку по работе бота
    """
    await message.answer(welcome_text, reply_markup=get_user_keyboard(user_id))

@dp.message(F.text == "Scam base:")
async def handle_scam_base(message: Message):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
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
    await message.answer(help_text, reply_markup=get_user_keyboard(user_id))

@dp.message(F.text == "🔙 Назад")
async def handle_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🎯 Выберите действие:", reply_markup=get_user_keyboard(message.from_user.id))

@dp.message(F.text == "📝 Жалоба")
async def handle_complaint_button(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    if get_recent_reports_count(user_id) >= 5:
        await message.answer("❌ Максимум 5 жалоб в час!")
        return
    
    await state.set_state(UserStates.WAITING_FOR_USERNAME)
    await message.answer("👤 **Введите юзернейм:**\n(например: username)", reply_markup=back_keyboard)

@dp.message(F.text == "🔍 Проверить")
async def handle_check_button(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    await state.set_state(UserStates.WAITING_CHECK_USERNAME)
    await message.answer("🔍 **Введите юзернейм для проверки:**", reply_markup=back_keyboard)

@dp.message(F.text == "ℹ️ Помощь")
async def handle_help_button(message: Message):
    help_text = """
📋 **Как пользоваться ботом:**

📝 **Жалоба** - нажмите кнопку и следуйте инструкциям
🔍 **Проверить** - узнайте информацию о пользователе

⚠️ **Внимание:** 
- Максимум 5 жалоб в час
- Жалобы проходят модерацию
    """
    await message.answer(help_text, reply_markup=get_user_keyboard(message.from_user.id))

@dp.message(F.text == "🛠 Админ")
async def handle_admin_button(message: Message):
    user_id = message.from_user.id
    
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
    ])
    
    await message.answer("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    user_id = message.from_user.id
    
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
    ])
    
    await message.answer("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)

# ===== ОБРАБОТКА СОСТОЯНИЙ =====
@dp.message(UserStates.WAITING_CHECK_USERNAME)
async def process_check_username(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith('@'):
        text = text[1:]
    
    is_valid, validation_msg = validate_username(text)
    if not is_valid:
        await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
        return
    
    reports = get_user_reports(text)
    
    if not reports:
        await message.answer(f"ℹ️ По пользователю @{text} информации нет", reply_markup=get_user_keyboard(message.from_user.id))
    else:
        statuses = set()
        comments = []
        
        for status, comment, timestamp in reports:
            statuses.add(status)
            comments.append(f"• {comment} ({timestamp[:10]})")
        
        response = [
            f"🔍 **Информация о @{text}:**",
            f"🏷 **Статусы:** {', '.join(sorted(statuses))}",
            f"📝 **Комментарии:**",
            *comments[:3],
            f"📊 **Всего жалоб:** {len(reports)}"
        ]
        
        await message.answer("\n".join(response), reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

@dp.message(UserStates.WAITING_FOR_USERNAME)
async def process_complaint_username(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith('@'):
        text = text[1:]
    
    is_valid, validation_msg = validate_username(text)
    if not is_valid:
        await message.answer(f"{validation_msg}\nПопробуйте снова:", reply_markup=back_keyboard)
        return
    
    if message.from_user.username and message.from_user.username.lower() == text.lower():
        await message.answer("❌ Нельзя подать жалобу на самого себя!", reply_markup=get_user_keyboard(message.from_user.id))
        await state.clear()
        return
    
    await state.update_data(target_username=text)
    await state.set_state(UserStates.WAITING_FOR_COMMENT)
    await message.answer("📝 **Введите комментарий:**\n(например: «не отправил товар»)", reply_markup=back_keyboard)

@dp.message(UserStates.WAITING_FOR_COMMENT)
async def process_complaint_comment(message: Message, state: FSMContext):
    text = message.text.strip()
    
    if not text or len(text) < 5:
        await message.answer("❌ Комментарий слишком короткий (минимум 5 символов). Попробуйте снова:", reply_markup=back_keyboard)
        return
    
    if len(text) > 500:
        await message.answer("❌ Комментарий слишком длинный (максимум 500 символов). Попробуйте снова:", reply_markup=back_keyboard)
        return
    
    await state.update_data(comment=text)
    await state.set_state(UserStates.WAITING_FOR_PROOF)
    await message.answer("📎 **Пришлите скриншот или напишите 'пропустить':**", reply_markup=back_keyboard)

@dp.message(UserStates.WAITING_FOR_PROOF)
async def process_complaint_proof(message: Message, state: FSMContext):
    if message.text and message.text.lower() == 'пропустить':
        await state.update_data(proof_photo=None)
        await state.set_state(UserStates.WAITING_FOR_STATUS)
        await message.answer("Выберите статус:", reply_markup=status_keyboard)
    elif message.photo:
        proof_photo = message.photo[-1].file_id
        await state.update_data(proof_photo=proof_photo)
        await state.set_state(UserStates.WAITING_FOR_STATUS)
        await message.answer("📸 Доказательство сохранено! Выберите статус:", reply_markup=status_keyboard)
    else:
        await message.answer("❌ Отправьте фото или напишите 'пропустить'", reply_markup=back_keyboard)

@dp.message(UserStates.WAITING_FOR_STATUS)
async def process_complaint_status(message: Message, state: FSMContext):
    text = message.text.strip()
    
    if text == "другое":
        await state.set_state(UserStates.WAITING_FOR_CUSTOM_STATUS)
        await message.answer("Введите свой вариант статуса:", reply_markup=back_keyboard)
    elif text == "🔙 Назад":
        await state.set_state(UserStates.WAITING_FOR_PROOF)
        await message.answer("📎 **Пришлите скриншот или напишите 'пропустить':**", reply_markup=back_keyboard)
    else:
        await save_report(message, state, text)

@dp.message(UserStates.WAITING_FOR_CUSTOM_STATUS)
async def process_complaint_custom_status(message: Message, state: FSMContext):
    text = message.text.strip()
    
    if text == "🔙 Назад":
        await state.set_state(UserStates.WAITING_FOR_STATUS)
        await message.answer("Выберите статус:", reply_markup=status_keyboard)
    else:
        await save_report(message, state, text)

async def save_report(message: Message, state: FSMContext, status: str):
    data = await state.get_data()
    target_username = data['target_username']
    comment = data['comment']
    proof_photo = data.get('proof_photo')
    
    report_id = add_report(message.from_user.id, target_username, status, comment, proof_photo)
    
    if report_id:
        admin_text = f"🆕 Жалоба #{report_id}\n👤 На: @{target_username}\n📝 {comment}\n🏷 {status}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{report_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{report_id}")
        ]])
        
        if proof_photo:
            await bot.send_photo(ADMIN_IDS[0], proof_photo, caption=admin_text, reply_markup=keyboard)
        else:
            await bot.send_message(ADMIN_IDS[0], admin_text + "\n\n📸 Без доказательств", reply_markup=keyboard)
        
        await message.answer("✅ **Жалоба отправлена на модерацию!**", reply_markup=get_user_keyboard(message.from_user.id))
    else:
        await message.answer("❌ Ошибка сохранения заявки", reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

# ===== АДМИН CALLBACKS =====
@dp.callback_query(F.data.startswith("approve_"))
async def handle_approve_callback(callback: CallbackQuery):
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
        await callback.message.edit_text(f"✅ Жалоба #{report_id} одобрена")
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_"))
async def handle_reject_callback(callback: CallbackQuery):
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
        await callback.message.edit_text(f"❌ Жалоба #{report_id} отклонена")
    await callback.answer()

@dp.callback_query(F.data == "admin_show_reports")
async def handle_admin_show_reports(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    reports = get_pending_reports()
    if not reports:
        await callback.message.edit_text("📭 Нет жалоб на модерации")
    else:
        text = f"📋 Жалобы ({len(reports)}):\n\n"
        for report in reports[:5]:
            text += f"#{report[0]} @{report[2]}\n{report[3]}: {report[4][:50]}...\n\n"
        await callback.message.edit_text(text)
    await callback.answer()

@dp.callback_query(F.data == "admin_delete_user")
async def handle_admin_delete_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.WAITING_DELETE_USER)
    await callback.message.edit_text("👤 **Введите юзернейм для удаления жалоб:**\n(например: username)")
    await callback.answer()

@dp.callback_query(F.data == "admin_announcement")
async def handle_admin_announcement(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.WAITING_ANNOUNCEMENT)
    await callback.message.edit_text("📢 **Введите текст объявления:**")
    await callback.answer()

@dp.callback_query(F.data == "admin_block")
async def handle_admin_block(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.WAITING_BLOCK_USER)
    await callback.message.edit_text("🚫 **Введите ID пользователя:**\n(только число)")
    await callback.answer()

@dp.callback_query(F.data == "admin_block_username")
async def handle_admin_block_username(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.WAITING_BLOCK_BY_USERNAME)
    await callback.message.edit_text("🚫 **Введите @username:**\n(например: username)")
    await callback.answer()

@dp.callback_query(F.data == "admin_unblock")
async def handle_admin_unblock(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.WAITING_UNBLOCK_USER)
    await callback.message.edit_text("✅ **Введите ID пользователя:**\n(только число)")
    await callback.answer()

@dp.callback_query(F.data == "admin_unblock_username")
async def handle_admin_unblock_username(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.WAITING_UNBLOCK_BY_USERNAME)
    await callback.message.edit_text("✅ **Введите @username:**\n(например: username)")
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def handle_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
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
    
    cursor.execute('SELECT COUNT(*) FROM bot_users')
    users = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = f"📊 **Статистика:**\n\n📨 Жалоб: {approved + pending}\n✅ Одобрено: {approved}\n⏳ На модерации: {pending}\n👥 Пользователей: {users}\n🚫 Заблокировано: {blocked}"
    await callback.message.edit_text(stats_text)
    await callback.answer()

# ===== АДМИН СОСТОЯНИЯ =====
@dp.message(AdminStates.WAITING_DELETE_USER)
async def process_admin_delete_user(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith('@'):
        text = text[1:]
    
    success, result_msg = delete_user_reports(text)
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    await state.clear()

@dp.message(AdminStates.WAITING_ANNOUNCEMENT)
async def process_admin_announcement(message: Message, state: FSMContext):
    text = message.text.strip()
    users = get_all_bot_users()
    success = 0
    failed = 0
    
    logger.info(f"Starting announcement to {len(users)} users: {text}")
    
    for user_id, username in users:
        try:
            if not is_user_blocked(user_id):
                await bot.send_message(user_id, f"📢 **Объявление:**\n\n{text}")
                success += 1
                await asyncio.sleep(0.05)  # Небольшая задержка чтобы не превысить лимиты
            else:
                logger.info(f"Skipping blocked user: {user_id}")
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send to {user_id}: {e}")
    
    logger.info(f"Announcement completed: {success} successful, {failed} failed")
    await message.answer(f"📢 **Результат рассылки:**\n✅ Отправлено: {success} пользователям\n❌ Не отправлено: {failed}", reply_markup=get_user_keyboard(message.from_user.id))
    await state.clear()

@dp.message(AdminStates.WAITING_BLOCK_USER)
async def process_admin_block_user(message: Message, state: FSMContext):
    try:
        target_id = int(message.text.strip())
        await state.update_data(block_target_id=target_id)
        await state.set_state(AdminStates.WAITING_BLOCK_REASON)
        await message.answer("Введите причину блокировки:")
    except:
        await message.answer("❌ Введите числовой ID:")

@dp.message(AdminStates.WAITING_BLOCK_REASON)
async def process_admin_block_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['block_target_id']
    reason = message.text.strip()
    
    try:
        # Пробуем получить информацию о пользователе
        target_user = await bot.get_chat(target_id)
        username = target_user.username or f"user_{target_id}"
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        username = f"user_{target_id}"
    
    success, result_msg = block_user(target_id, username, reason, message.from_user.id)
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    
    try:
        await bot.send_message(target_id, f"🚫 **Вы заблокированы!**\nПричина: {reason}")
    except Exception as e:
        logger.error(f"Could not notify user {target_id}: {e}")
    
    await state.clear()

@dp.message(AdminStates.WAITING_BLOCK_BY_USERNAME)
async def process_admin_block_by_username(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith('@'):
        text = text[1:]
    
    # Ищем пользователя в нашей базе
    user_info = get_user_by_username(text)
    if not user_info:
        await message.answer("❌ Пользователь не найден в базе бота.")
        await state.clear()
        return
    
    target_id, stored_username = user_info
    
    await state.update_data(block_target_id=target_id)
    await state.set_state(AdminStates.WAITING_BLOCK_REASON)
    await message.answer(f"👤 Найден: @{stored_username} (ID: {target_id})\nВведите причину блокировки:")

@dp.message(AdminStates.WAITING_UNBLOCK_USER)
async def process_admin_unblock_user(message: Message, state: FSMContext):
    try:
        target_id = int(message.text.strip())
        success, result_msg = unblock_user(target_id)
        await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
        
        try:
            await bot.send_message(target_id, "✅ **Вы разблокированы!**")
        except Exception as e:
            logger.error(f"Could not notify user {target_id}: {e}")
    except:
        await message.answer("❌ Введите числовой ID:")
    
    await state.clear()

@dp.message(AdminStates.WAITING_UNBLOCK_BY_USERNAME)
async def process_admin_unblock_by_username(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith('@'):
        text = text[1:]
    
    success, result_msg = unblock_user_by_username(text)
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    
    # Пытаемся уведомить пользователя
    try:
        user_info = get_user_by_username(text)
        if user_info:
            target_id, stored_username = user_info
            await bot.send_message(target_id, "✅ **Вы разблокированы!**")
    except Exception as e:
        logger.error(f"Could not notify user: {e}")
    
    await state.clear()

# ===== ЗАПУСК =====
async def main():
    print("🚀 Starting bot...")
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
