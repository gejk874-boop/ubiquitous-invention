import asyncio
import sqlite3
import re
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8551536077:AAHFD0p7xBUkxod697ppIQLtPf6Q-q72BgU"
ADMIN_IDS = [6986121067]

# Глобальная переменная для статуса бота
BOT_ACTIVE = True

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('reports.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_date DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
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
    
    # Таблица для статуса бота
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            is_active BOOLEAN DEFAULT TRUE,
            maintenance_message TEXT DEFAULT 'Бот временно отключен для технических работ',
            updated_by INTEGER,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Инициализируем настройки
    cursor.execute('INSERT OR IGNORE INTO bot_settings (id, is_active) VALUES (1, TRUE)')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# === ФУНКЦИИ ДЛЯ УПРАВЛЕНИЯ СТАТУСОМ БОТА ===
def get_bot_status():
    """Получить статус бота из базы данных"""
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('SELECT is_active, maintenance_message FROM bot_settings WHERE id = 1')
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result[0], result[1]
        return True, "Бот временно отключен для технических работ"
    except Exception as e:
        logger.error(f"❌ Ошибка получения статуса бота: {e}")
        return True, "Бот временно отключен для технических работ"

def set_bot_status(is_active, admin_id, message="Бот временно отключен для технических работ"):
    """Установить статус бота"""
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE bot_settings 
            SET is_active = ?, maintenance_message = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (is_active, message, admin_id))
        conn.commit()
        conn.close()
        
        global BOT_ACTIVE
        BOT_ACTIVE = is_active
        
        status_text = "включен" if is_active else "отключен"
        logger.info(f"🔧 Бот {status_text} администратором {admin_id}")
        return True, f"✅ Бот успешно {status_text}"
    except Exception as e:
        logger.error(f"❌ Ошибка изменения статуса бота: {e}")
        return False, f"❌ Ошибка: {e}"

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def add_bot_user(user_id, username, first_name, last_name):
    try:
        conn = sqlite3.connect('reports.db')
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
        conn = sqlite3.connect('reports.db')
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
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM bot_users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Ошибка получения ID по username: {e}")
        return None

def is_user_blocked(user_id):
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM blocked_users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка проверки блокировки: {e}")
        return False

def block_user(user_id, username, reason, blocked_by):
    try:
        conn = sqlite3.connect('reports.db')
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
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM blocked_users WHERE user_id = ?', (user_id,))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected > 0:
            return True, "✅ Пользователь разблокирован"
        else:
            return False, "❌ Пользователь не найден в заблокированных"
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки: {e}")
        return False, f"❌ Ошибка разблокировки: {e}"

def delete_user_reports(target_username):
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM reports WHERE target_username = ?', (target_username.lower(),))
        rows_deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return True, f"✅ Удалено {rows_deleted} жалоб на @{target_username}"
    except Exception as e:
        logger.error(f"❌ Ошибка удаления жалоб: {e}")
        return False, f"❌ Ошибка удаления: {e}"

def get_user_reports(target_username):
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT status, comment, timestamp FROM reports 
            WHERE target_username = ? AND is_approved = TRUE
        ''', (target_username.lower(),))
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        logger.error(f"❌ Ошибка получения жалоб: {e}")
        return []

def get_recent_reports_count(reporter_id, hours=1):
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        time_threshold = datetime.now() - timedelta(hours=hours)
        cursor.execute('SELECT COUNT(*) FROM reports WHERE reporter_id = ? AND timestamp > ?', 
                      (reporter_id, time_threshold))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"❌ Ошибка подсчета жалоб: {e}")
        return 0

def add_report(reporter_id, target_username, status, comment, proof_photo=None):
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reports (reporter_id, target_username, status, comment, proof_photo)
            VALUES (?, ?, ?, ?, ?)
        ''', (reporter_id, target_username.lower(), status, comment, proof_photo))
        report_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"🆕 Создана жалоба #{report_id} на @{target_username}")
        return report_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления жалобы: {e}")
        return None

def get_pending_reports():
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, reporter_id, target_username, status, comment, proof_photo
            FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE
        ''')
        results = cursor.fetchall()
        conn.close()
        
        logger.info(f"📋 Найдено жалоб на модерации: {len(results)}")
        return results
    except Exception as e:
        logger.error(f"❌ Ошибка получения жалоб: {e}")
        return []

def approve_report(report_id, moderator_id):
    try:
        conn = sqlite3.connect('reports.db')
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
            logger.info(f"✅ Жалоба #{report_id} одобрена модератором {moderator_id}")
            return result[0], result[1]
        return None, None
    except Exception as e:
        logger.error(f"❌ Ошибка одобрения: {e}")
        return None, None

def reject_report(report_id, moderator_id):
    try:
        conn = sqlite3.connect('reports.db')
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
            logger.info(f"❌ Жалоба #{report_id} отклонена модератором {moderator_id}")
            return result[0]
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка отклонения: {e}")
        return None

def validate_username(username):
    if not username or len(username) < 3:
        return False, "❌ Юзернейм слишком короткий"
    if len(username) > 32:
        return False, "❌ Юзернейм слишком длинный"
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "❌ Юзернейм может содержать только буквы, цифры и подчеркивания"
    return True, "✅ Юзернейм корректен"

# === КЛАВИАТУРЫ ===
def get_user_keyboard(user_id):
    keyboard = [
        [KeyboardButton(text="📝 Жалоба"), KeyboardButton(text="🔍 Проверить")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton(text="🛠 Админ")])
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
        [KeyboardButton(text="обманщик"), KeyboardButton(text="ненадёжный")],
        [KeyboardButton(text="мошенник"), KeyboardButton(text="другое")],
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
    WAITING_MAINTENANCE_MESSAGE = State()

# === ПРОВЕРКА СТАТУСА БОТА ПЕРЕД КАЖДЫМ СООБЩЕНИЕМ ===
@dp.message.middleware()
async def check_bot_status(handler, event, data):
    # Проверяем статус бота для всех сообщений кроме админских команд
    if isinstance(event, types.Message):
        is_active, maintenance_message = get_bot_status()
        
        # Если бот отключен и это не админ
        if not is_active and event.from_user.id not in ADMIN_IDS:
            await event.answer(f"🔧 {maintenance_message}")
            return
    
    # Продолжаем обработку если бот активен или это админ
    return await handler(event, data)

# === ОСНОВНЫЕ ОБРАБОТЧИКИ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
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
    elif message.photo:
        proof_photo = message.photo[-1].file_id
        await state.update_data(proof_photo=proof_photo)
        await state.set_state(UserStates.WAITING_FOR_STATUS)
        await message.answer("📸 Доказательство сохранено! Выберите статус:", reply_markup=status_keyboard)
    else:
        await message.answer("❌ Отправьте фото или нажмите '📎 Пропустить'", reply_markup=proof_keyboard)

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
        # Отправляем уведомление админам с inline-кнопками
        admin_text = f"🆕 Жалоба #{report_id}\n👤 На: @{data['target_username']}\n📝 {data['comment']}\n🏷 {status}"
        
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
    help_text = """
📋 **Как пользоваться ботом:**

📝 **Жалоба** - нажмите кнопку и следуйте инструкциям
🔍 **Проверить** - узнайте информацию о пользователе

⚠️ **Внимание:** 
- Максимум 5 жалоб в час
- Жалобы проходят модерацию
    """
    await message.answer(help_text, reply_markup=get_user_keyboard(message.from_user.id))

# === АДМИН ПАНЕЛЬ ===
@dp.message(F.text == "🛠 Админ")
async def handle_admin(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    
    # Получаем текущий статус бота
    is_active, maintenance_message = get_bot_status()
    bot_status = "🟢 Включен" if is_active else "🔴 Выключен"
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Показать жалобы", callback_data="admin_show_reports")],
        [InlineKeyboardButton(text="🚫 Заблокировать по @username", callback_data="admin_block_username")],
        [InlineKeyboardButton(text="✅ Разблокировать по @username", callback_data="admin_unblock_username")],
        [InlineKeyboardButton(text="📢 Сделать объявление", callback_data="admin_announcement")],
        [InlineKeyboardButton(text="🗑️ Удалить информацию о пользователе", callback_data="admin_delete_user")],
        [InlineKeyboardButton(text=f"{'🔴 Выключить бота' if is_active else '🟢 Включить бота'}", callback_data="admin_toggle_bot")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.answer(f"🛠 **Панель администратора**\n\nСтатус бота: {bot_status}", reply_markup=keyboard)

@dp.callback_query(F.data == "admin_toggle_bot")
async def handle_admin_toggle_bot(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    # Получаем текущий статус
    is_active, _ = get_bot_status()
    
    if is_active:
        # Если бот активен - запрашиваем сообщение для отключения
        await callback.message.answer("✏️ **Введите сообщение для пользователей при отключении бота:**\n(например: 'Ведутся технические работы')", reply_markup=back_keyboard)
        await state.set_state(AdminStates.WAITING_MAINTENANCE_MESSAGE)
        await state.update_data(action="disable")
    else:
        # Если бот отключен - включаем его
        success, result_msg = set_bot_status(True, callback.from_user.id)
        await callback.message.answer(result_msg, reply_markup=get_user_keyboard(callback.from_user.id))
    
    await callback.answer()

@dp.message(AdminStates.WAITING_MAINTENANCE_MESSAGE)
async def process_maintenance_message(message: types.Message, state: FSMContext):
    maintenance_message = message.text
    data = await state.get_data()
    
    if data.get('action') == "disable":
        success, result_msg = set_bot_status(False, message.from_user.id, maintenance_message)
        await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

@dp.callback_query(F.data == "admin_show_reports")
async def handle_admin_show_reports(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    reports = get_pending_reports()
    if not reports:
        await callback.message.answer("📭 Нет жалоб на модерации", reply_markup=get_user_keyboard(callback.from_user.id))
    else:
        text = f"📋 Жалобы на модерации ({len(reports)}):\n\n"
        for report in reports[:5]:
            text += f"#{report[0]} @{report[2]}\n{report[3]}: {report[4][:50]}...\n\n"
        text += "ℹ️ Для модерации используйте кнопки под каждой жалобой"
        await callback.message.answer(text, reply_markup=get_user_keyboard(callback.from_user.id))
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
    
    # Уведомляем пользователя
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
    
    # Уведомляем пользователя
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
    users = get_all_bot_users()
    success_count = 0
    
    for user_id, username in users:
        try:
            if not is_user_blocked(user_id):
                await bot.send_message(user_id, f"📢 **Объявление:**\n\n{text}")
                success_count += 1
                await asyncio.sleep(0.05)
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
    conn = sqlite3.connect('reports.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM reports WHERE is_approved = TRUE')
    approved = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE')
    pending = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM bot_users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM
