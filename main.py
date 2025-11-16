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
BOT_TOKEN = "8468176061:AAEsk6fmhwAwKZLWYQpEqROj-_LTLHFKg5o"
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
    await state.set_state(UserStates.WAITING_FOR_STATUS)
    await message.answer("🚨 **Выберите статус нарушения:**", reply_markup=status_keyboard)

@dp.message(UserStates.WAITING_FOR_STATUS)
async def process_status(message: types.Message, state: FSMContext):
    status = message.text.strip().lower()
    
    valid_statuses = ["обманщик", "ненадёжный", "мошенник", "другое"]
    
    if status not in valid_statuses:
        await message.answer("❌ Пожалуйста, выберите статус из предложенных вариантов:", reply_markup=status_keyboard)
        return
    
    if status == "другое":
        await state.set_state(UserStates.WAITING_FOR_CUSTOM_STATUS)
        await message.answer("✏️ **Введите свой вариант статуса:**", reply_markup=back_keyboard)
        return
    
    await state.update_data(status=status)
    await state.set_state(UserStates.WAITING_FOR_PROOF)
    await message.answer("📎 **Отправьте фото доказательства:**\n(или нажмите 'Пропустить')", reply_markup=proof_keyboard)

@dp.message(UserStates.WAITING_FOR_CUSTOM_STATUS)
async def process_custom_status(message: types.Message, state: FSMContext):
    custom_status = message.text.strip()
    
    if len(custom_status) < 3:
        await message.answer("❌ Статус слишком короткий (минимум 3 символа). Попробуйте снова:", reply_markup=back_keyboard)
        return
    
    await state.update_data(status=custom_status)
    await state.set_state(UserStates.WAITING_FOR_PROOF)
    await message.answer("📎 **Отправьте фото доказательства:**\n(или нажмите 'Пропустить')", reply_markup=proof_keyboard)

@dp.message(UserStates.WAITING_FOR_PROOF)
async def process_proof(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    if message.text == "📎 Пропустить":
        proof_photo = None
    elif message.photo:
        proof_photo = message.photo[-1].file_id
    else:
        await message.answer("❌ Пожалуйста, отправьте фото или нажмите 'Пропустить':", reply_markup=proof_keyboard)
        return
    
    # Сохраняем жалобу
    report_id = add_report(
        reporter_id=message.from_user.id,
        target_username=data['target_username'],
        status=data['status'],
        comment=data['comment'],
        proof_photo=proof_photo
    )
    
    if report_id:
        await message.answer(
            f"✅ **Жалоба отправлена на модерацию!**\n\n"
            f"👤 Пользователь: @{data['target_username']}\n"
            f"🚨 Статус: {data['status']}\n"
            f"📝 Комментарий: {data['comment']}\n\n"
            f"⏳ Ожидайте проверки модератора.",
            reply_markup=get_user_keyboard(message.from_user.id)
        )
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆕 Новая жалоба #{report_id}\n"
                    f"👤 На: @{data['target_username']}\n"
                    f"🚨 Статус: {data['status']}\n"
                    f"📝 Комментарий: {data['comment']}"
                )
            except Exception as e:
                logger.error(f"❌ Ошибка уведомления админа {admin_id}: {e}")
    else:
        await message.answer("❌ Ошибка при отправке жалобы. Попробуйте позже.", 
                           reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

@dp.message(F.text == "🔍 Проверить")
async def handle_check(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.answer("❌ Вы заблокированы в системе.")
        return
    
    await state.set_state(UserStates.WAITING_CHECK_USERNAME)
    await message.answer("👤 **Введите юзернейм для проверки:**", reply_markup=back_keyboard)

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
        await message.answer(f"✅ Пользователь @{username} не найден в списке ненадежных.", 
                           reply_markup=get_user_keyboard(message.from_user.id))
    else:
        response = f"🚨 **На пользователя @{username} найдено {len(reports)} жалоб:**\n\n"
        
        for i, (status, comment, timestamp) in enumerate(reports, 1):
            date = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
            response += f"{i}. **{status}** - {comment}\n   📅 {date}\n\n"
        
        await message.answer(response, reply_markup=get_user_keyboard(message.from_user.id))
    
    await state.clear()

@dp.message(F.text == "ℹ️ Помощь")
async def handle_help(message: types.Message):
    help_text = """
📖 **Справка по боту:**

📝 **Подача жалобы:**
1. Нажмите "📝 Жалоба"
2. Введите юзернейм нарушителя (без @)
3. Опишите ситуацию
4. Выберите категорию нарушения
5. При необходимости прикрепите доказательства

🔍 **Проверка пользователя:**
• Введите юзернейм для проверки истории

⚡ **Важно:**
• Жалобы проходят модерацию
• Максимум 5 жалоб в час
• Ложные жалобы могут привести к блокировке
    """
    await message.answer(help_text, reply_markup=get_user_keyboard(message.from_user.id))

# === АДМИН ПАНЕЛЬ ===
@dp.message(F.text == "🛠 Админ")
async def handle_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен.")
        return
    
    admin_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="⏳ Модерация")],
            [KeyboardButton(text="🚫 Заблокировать"), KeyboardButton(text="✅ Разблокировать")],
            [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🗑 Удалить жалобы")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    
    await message.answer("🛠 **Панель администратора**", reply_markup=admin_keyboard)

@dp.message(F.text == "📊 Статистика")
async def handle_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        conn = sqlite3.connect('reports.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM bot_users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reports')
        total_reports = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reports WHERE is_approved = TRUE')
        approved_reports = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE')
        pending_reports = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM blocked_users')
        blocked_users = cursor.fetchone()[0]
        
        conn.close()
        
        stats_text = f"""
📊 **Статистика бота:**

👥 Пользователей: {total_users}
📨 Всего жалоб: {total_reports}
✅ Одобрено: {approved_reports}
⏳ На модерации: {pending_reports}
🚫 Заблокировано: {blocked_users}
        """
        await message.answer(stats_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

@dp.message(F.text == "⏳ Модерация")
async def handle_moderation(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    pending_reports = get_pending_reports()
    
    if not pending_reports:
        await message.answer("✅ Нет жалоб для модерации.")
        return
    
    for report in pending_reports[:5]:  # Показываем первые 5
        report_id, reporter_id, target_username, status, comment, proof_photo = report
        
        report_text = (
            f"🆕 **Жалоба #{report_id}**\n\n"
            f"👤 **Пользователь:** @{target_username}\n"
            f"🚨 **Статус:** {status}\n"
            f"📝 **Комментарий:** {comment}\n"
            f"👁 **От:** {reporter_id}"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{report_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{report_id}")]
        ])
        
        if proof_photo:
            await message.answer_photo(proof_photo, caption=report_text, reply_markup=keyboard)
        else:
            await message.answer(report_text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("approve_"))
async def approve_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.")
        return
    
    report_id = int(callback.data.split("_")[1])
    reporter_id, target_username = approve_report(report_id, callback.from_user.id)
    
    if reporter_id:
        await callback.message.edit_caption(
            f"✅ **Жалоба одобрена**\n\n"
            f"👤 Пользователь: @{target_username}\n"
            f"👁 Модератор: {callback.from_user.id}"
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                reporter_id,
                f"✅ Ваша жалоба на @{target_username} была одобрена модератором."
            )
        except Exception as e:
            logger.error(f"❌ Ошибка уведомления пользователя: {e}")
    else:
        await callback.message.edit_caption("❌ Ошибка одобрения жалобы.")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_"))
async def reject_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.")
        return
    
    report_id = int(callback.data.split("_")[1])
    reporter_id = reject_report(report_id, callback.from_user.id)
    
    if reporter_id:
        await callback.message.edit_caption(f"❌ **Жалоба отклонена**\n\nМодератор: {callback.from_user.id}")
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                reporter_id,
                "❌ Ваша жалоба была отклонена модератором."
            )
        except Exception as e:
            logger.error(f"❌ Ошибка уведомления пользователя: {e}")
    else:
        await callback.message.edit_caption("❌ Ошибка отклонения жалобы.")
    
    await callback.answer()

@dp.message(F.text == "🚫 Заблокировать")
async def handle_block(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.WAITING_BLOCK_USERNAME)
    await message.answer("👤 **Введите юзернейм для блокировки:**", reply_markup=back_keyboard)

@dp.message(AdminStates.WAITING_BLOCK_USERNAME)
async def process_block_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    user_id = get_user_id_by_username(username)
    if not user_id:
        await message.answer("❌ Пользователь не найден в базе бота.")
        await state.clear()
        return
    
    await state.update_data(block_username=username, block_user_id=user_id)
    await state.set_state(AdminStates.WAITING_BLOCK_REASON)
    await message.answer("📝 **Введите причину блокировки:**", reply_markup=back_keyboard)

@dp.message(AdminStates.WAITING_BLOCK_REASON)
async def process_block_reason(message: types.Message, state: FSMContext):
    reason = message.text.strip()
    data = await state.get_data()
    
    success, result_msg = block_user(
        data['block_user_id'],
        data['block_username'],
        reason,
        message.from_user.id
    )
    
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    await state.clear()

@dp.message(F.text == "✅ Разблокировать")
async def handle_unblock(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.WAITING_UNBLOCK_USERNAME)
    await message.answer("👤 **Введите юзернейм для разблокировки:**", reply_markup=back_keyboard)

@dp.message(AdminStates.WAITING_UNBLOCK_USERNAME)
async def process_unblock_username(message: types.Message, state: FSMContext):
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
    await state.clear()

@dp.message(F.text == "🗑 Удалить жалобы")
async def handle_delete_reports(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.WAITING_DELETE_USER)
    await message.answer("👤 **Введите юзернейм для удаления всех жалоб:**", reply_markup=back_keyboard)

@dp.message(AdminStates.WAITING_DELETE_USER)
async def process_delete_reports(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username.startswith('@'):
        username = username[1:]
    
    success, result_msg = delete_user_reports(username)
    await message.answer(result_msg, reply_markup=get_user_keyboard(message.from_user.id))
    await state.clear()

@dp.message(F.text == "📢 Рассылка")
async def handle_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.WAITING_ANNOUNCEMENT)
    await message.answer("📢 **Введите сообщение для рассылки:**", reply_markup=back_keyboard)

@dp.message(AdminStates.WAITING_ANNOUNCEMENT)
async def process_broadcast(message: types.Message, state: FSMContext):
    announcement = message.text
    users = get_all_bot_users()
    
    sent_count = 0
    failed_count = 0
    
    await message.answer(f"📨 Рассылка начата... Получателей: {len(users)}")
    
    for user_id, username in users:
        try:
            await bot.send_message(user_id, f"📢 **Объявление от администратора:**\n\n{announcement}")
            sent_count += 1
            await asyncio.sleep(0.1)  # Задержка чтобы не превысить лимиты
        except Exception as e:
            logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")
            failed_count += 1
    
    await message.answer(
        f"✅ **Рассылка завершена:**\n\n"
        f"📨 Отправлено: {sent_count}\n"
        f"❌ Не удалось: {failed_count}",
        reply_markup=get_user_keyboard(message.from_user.id)
    )
    
    await state.clear()

# === ЗАПУСК БОТА ДЛЯ BEEHOST ===
async def main():
    logger.info("✅ База данных инициализирована")
    logger.info("🤖 Бот запускается на Beehost...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
