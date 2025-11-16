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
BOT_TOKEN = "8178105406:AAGm4yQ7ZY4BzkVfUcHautpa8r-7DwLZikg"
ADMIN_IDS = [6986121067]  # Ваш ID

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
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

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
        
        # Проверяем, не заблокирован ли уже
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
    # ОДНО сообщение вместо нескольких
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

@dp.message(F.text == "🔍 Проверить")
async def handle_check(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    await state.set_state(UserStates.WAITING_CHECK_USERNAME)
    await message.answer("🔍 **Введите юзернейм для проверки:**", reply_markup=back_keyboard)

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

@dp.message(F.text == "🛠 Админ")
async def handle_admin(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Заблокировать по @username", callback_data="admin_block_username")],
        [InlineKeyboardButton(text="✅ Разблокировать по @username", callback_data="admin_unblock_username")],
        [InlineKeyboardButton(text="📢 Сделать объявление", callback_data="admin_announcement")],
        [InlineKeyboardButton(text="🗑️ Удалить информацию о пользователе", callback_data="admin_delete_user")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.answer("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)

# === ОБРАБОТКА ЖАЛОБ ===
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
    await message.answer("📎 **Пришлите скриншот или напишите 'пропустить':**", reply_markup=back_keyboard)

@dp.message(UserStates.WAITING_FOR_PROOF)
async def process_proof(message: types.Message, state: FSMContext):
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
async def process_status(message: types.Message, state: FSMContext):
    status = message.text
    
    if status == "🔙 Назад":
        await state.set_state(UserStates.WAITING_FOR_PROOF)
        await message.answer("📎 **Пришлите скриншот или напишите 'пропустить':**", reply_markup=back_keyboard)
        return
    
    data = await state.get_data()
    
    # Сохраняем жалобу
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reports (reporter_id, target_username, status, comment, proof_photo, is_approved)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (message.from_user.id, data['target_username'].lower(), status, data['comment'], data.get('proof_photo'), True))
        conn.commit()
        conn.close()
        
        await message.answer("✅ **Жалоба отправлена!**", reply_markup=get_user_keyboard(message.from_user.id))
    except Exception as e:
        await message.answer("❌ Ошибка сохранения жалобы", reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

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

# === АДМИН ОБРАБОТЧИКИ ===
@dp.callback_query(F.data == "admin_block_username")
async def handle_admin_block_username(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🚫 **Введите @username для блокировки:**\n(например: username)")
    await state.set_state(AdminStates.WAITING_BLOCK_USERNAME)
    await callback.answer()

@dp.message(AdminStates.WAITING_BLOCK_USERNAME)
async def process_admin_block_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    user_id = get_user_id_by_username(username)
    if not user_id:
        await message.answer("❌ Пользователь не найден в базе бота.")
        await state.clear()
        return
    
    await state.update_data(target_user_id=user_id, target_username=username)
    await state.set_state(AdminStates.WAITING_BLOCK_REASON)
    await message.answer("📝 **Введите причину блокировки:**")

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
    await callback.message.answer("✅ **Введите @username для разблокировки:**\n(например: username)")
    await state.set_state(AdminStates.WAITING_UNBLOCK_USERNAME)
    await callback.answer()

@dp.message(AdminStates.WAITING_UNBLOCK_USERNAME)
async def process_admin_unblock_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    user_id = get_user_id_by_username(username)
    if not user_id:
        await message.answer("❌ Пользователь не найден в базе бота.")
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
    await callback.message.answer("📢 **Введите текст объявления:**")
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
                await asyncio.sleep(0.05)  # Задержка чтобы не превысить лимиты
        except Exception as e:
            logger.error(f"Не удалось отправить пользователю {user_id}: {e}")
    
    await message.answer(f"📢 **Объявление отправлено {success_count} пользователям**", reply_markup=get_user_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "admin_delete_user")
async def handle_admin_delete_user(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🗑️ **Введите @username для удаления информации:**\n(например: username)")
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
    
    cursor.execute('SELECT COUNT(*) FROM reports')
    total_reports = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM bot_users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM blocked_users')
    blocked_users = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = f"""
📊 **Статистика системы:**

👥 Пользователей: {total_users}
📨 Всего жалоб: {total_reports}
🚫 Заблокировано: {blocked_users}
    """
    
    await callback.message.answer(stats_text)
    await callback.answer()

# === ЗАПУСК ===
async def main():
    logger.info("🚀 Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
