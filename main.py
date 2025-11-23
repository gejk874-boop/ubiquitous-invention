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
BOT_TOKEN = "8424514943:AAHdwbe3tf-YsaY4akF3iNhscXcb_493dgQ"
ADMIN_IDS = [6986121067]

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
        
        # Логируем создание жалобы
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
        
        # Логируем количество найденных жалоб
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
        # Получаем информацию об отправителе
        reporter_username = f"@{message.from_user.username}" if message.from_user.username else f"Пользователь (ID: {message.from_user.id})"
        
        # Отправляем уведомление админам с inline-кнопками
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
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Показать жалобы", callback_data="admin_show_reports")],
        [InlineKeyboardButton(text="🚫 Заблокировать по @username", callback_data="admin_block_username")],
        [InlineKeyboardButton(text="✅ Разблокировать по @username", callback_data="admin_unblock_username")],
        [InlineKeyboardButton(text="📢 Сделать объявление", callback_data="admin_announcement")],
        [InlineKeyboardButton(text="🗑️ Удалить информацию о пользователе", callback_data="admin_delete_user")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.answer("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)

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
    
    # Отправляем каждую жалобу отдельно с кнопками модерации
    for report in pending_reports:
        report_id, reporter_id, target_username, status, comment, proof_photo = report
        
        # Получаем информацию об отправителе
        reporter_info = "Неизвестный отправитель"
        try:
            reporter_data = get_user_id_by_username(target_username)
            if reporter_data:
                reporter_info = f"@{target_username}"
        except:
            pass
        
        report_text = (f"🆕 Жалоба #{report_id}\n\n"
                      f"👤 **От кого:** {reporter_info}\n"
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
    
    cursor.execute('SELECT COUNT(*) FROM blocked_users')
    blocked_users = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = f"""
📊 **Статистика системы:**

👥 Пользователей: {total_users}
📨 Всего жалоб: {approved + pending}
✅ Одобрено: {approved}
⏳ На модерации: {pending}
🚫 Заблокировано: {blocked_users}
    """
    
    await callback.message.answer(stats_text, reply_markup=get_user_keyboard(callback.from_user.id))
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
        
        # Редактируем сообщение с жалобой
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
        
        # Редактируем сообщение с жалобой
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

# === ЗАПУСК ДЛЯ BEEHOST ===
async def main():
    logger.info("✅ База данных инициализирована")
    logger.info("🤖 Бот запускается на Beehost...")
    
    try:
        # Принудительно закрываем ВСЕ предыдущие сессии
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Все предыдущие сессии завершены")
        
        # Ждем немного чтобы убедиться что старые процессы завершились
        await asyncio.sleep(2)
        
        logger.info("🔄 Запускаем поллинг...")
        await dp.start_polling(bot, skip_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        # Перезапуск через 10 секунд
        await asyncio.sleep(10)
        await main()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
