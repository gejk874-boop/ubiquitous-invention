import asyncio
import sqlite3
import logging
import sys
import re
import os
import gc
from datetime import datetime, timedelta
from hydrogram import Client, filters
from hydrogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ===== ОПТИМИЗАЦИЯ ДЛЯ БЕСПЛАТНОГО ХОСТИНГА =====
gc.set_threshold(700, 10, 5)
os.environ['SQLITE_TMPDIR'] = '/tmp'

# ===== НАСТРОЙКА =====
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
BOT_TOKEN = "8223288154:AAEGGJGOXzIAUNRocxzKL7x-IAUhVfEb-xw"
ADMIN_IDS = [6986121067]

# Создаем клиента
app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=1,
    sleep_threshold=60
)

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

user_states = {}
user_data = {}
spam_protection = {}
muted_users = {}

# Клавиатуры
status_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("обманщик"), KeyboardButton("ненадёжный")],
        [KeyboardButton("мошенник"), KeyboardButton("другое")]
    ],
    resize_keyboard=True
)

user_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📝 Жалоба"), KeyboardButton("🔍 Проверить")],
        [KeyboardButton("ℹ️ Помощь")]
    ],
    resize_keyboard=True
)

# ===== АНТИСПАМ =====
def check_spam(user_id):
    """Проверка на спам"""
    current_time = datetime.now()
    
    if user_id in muted_users:
        mute_end = muted_users[user_id]
        if current_time < mute_end:
            remaining = (mute_end - current_time).seconds // 60
            return True, f"❌ Вы в муте! Осталось {remaining} минут"
        else:
            del muted_users[user_id]
    
    if user_id not in spam_protection:
        spam_protection[user_id] = []
    
    spam_protection[user_id] = [
        time for time in spam_protection[user_id] 
        if current_time - time < timedelta(minutes=1)
    ]
    
    if len(spam_protection[user_id]) >= 10:
        muted_users[user_id] = current_time + timedelta(minutes=5)
        del spam_protection[user_id]
        return True, "❌ Слишком много сообщений! Мут на 5 минут"
    
    spam_protection[user_id].append(current_time)
    return False, ""

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
        cursor.execute('SELECT user_id FROM bot_users')
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователей: {e}")
        return []

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
            return False, "Пользователь уже заблокирован"
            
        cursor.execute('''
            INSERT INTO blocked_users (user_id, username, reason, blocked_by)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, reason, blocked_by))
        conn.commit()
        conn.close()
        logger.info(f"✅ Пользователь {user_id} заблокирован")
        return True, "Пользователь успешно заблокирован"
    except Exception as e:
        logger.error(f"❌ Ошибка блокировки: {e}")
        return False, f"Ошибка блокировки: {e}"

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
            return True, "Пользователь успешно разблокирован"
        else:
            return False, "Пользователь не найден в списке заблокированных"
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки: {e}")
        return False, f"Ошибка разблокировки: {e}"

def is_user_blocked(user_id):
    try:
        conn = sqlite3.connect('reports.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM blocked_users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка проверки: {e}")
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

# ===== СОСТОЯНИЯ =====
class UserState:
    WAITING_FOR_USERNAME = "waiting_for_username"
    WAITING_FOR_COMMENT = "waiting_for_comment"
    WAITING_FOR_PROOF = "waiting_for_proof"
    WAITING_FOR_STATUS = "waiting_for_status"
    WAITING_FOR_CUSTOM_STATUS = "waiting_for_custom_status"

class AdminState:
    WAITING_BLOCK_USER = "waiting_block_user"
    WAITING_BLOCK_REASON = "waiting_block_reason"
    WAITING_UNBLOCK_USER = "waiting_unblock_user"
    WAITING_DELETE_USER = "waiting_delete_user"
    WAITING_ANNOUNCEMENT = "waiting_announcement"

# ===== ВАЛИДАЦИЯ =====
def validate_username(username):
    if not username or len(username) < 3:
        return False, "❌ Юзернейм слишком короткий (минимум 3 символа)"
    
    if len(username) > 32:
        return False, "❌ Юзернейм слишком длинный (максимум 32 символа)"
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "❌ Юзернейм может содержать только буквы, цифры и подчеркивания"
    
    return True, "✅ Юзернейм корректен"

def cleanup_old_states():
    current_time = datetime.now()
    to_remove = []
    
    for user_id, state_data in user_states.items():
        if current_time - state_data['timestamp'] > timedelta(hours=1):
            to_remove.append(user_id)
    
    for user_id in to_remove:
        if user_id in user_states:
            del user_states[user_id]
        if user_id in user_data:
            del user_data[user_id]
    
    if to_remove:
        logger.info(f"🧹 Очищено {len(to_remove)} старых состояний")

# ===== ОБРАБОТЧИКИ КНОПОК =====
async def handle_complaint_button(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        
        if is_user_blocked(user_id):
            await message.reply("❌ Вы заблокированы в системе.")
            return
        
        recent_count = get_recent_reports_count(user_id)
        if recent_count >= 5:
            await message.reply(
                "❌ **Превышен лимит!**\n"
                "Максимум 5 жалоб в час!\n"
                "Жалобы проходят модерацию перед публикацией."
            )
            return
        
        user_states[user_id] = {
            'state': UserState.WAITING_FOR_USERNAME,
            'timestamp': datetime.now()
        }
        user_data[user_id] = {}
        
        await message.reply(
            "👤 **Введите юзернейм человека, о котором хотите сообщить:**\n"
            "(например: @username или просто username)",
            reply_markup=ReplyKeyboardMarkup(remove_keyboard=True)
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_complaint_button: {e}")
        await message.reply("❌ Произошла ошибка при создании жалобы")

async def handle_check_button(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        
        user_states[user_id] = {
            'state': "waiting_check_username",
            'timestamp': datetime.now()
        }
        
        await message.reply(
            "🔍 **Введите юзернейм для проверки:**\n"
            "(например: @username или просто username)",
            reply_markup=ReplyKeyboardMarkup(remove_keyboard=True)
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_check_button: {e}")
        await message.reply("❌ Произошла ошибка при проверке")

async def handle_help_button(client: Client, message: Message):
    try:
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
        await message.reply(help_text, reply_markup=user_keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_help_button: {e}")
        await message.reply("❌ Произошла ошибка при показе справки")

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====
@app.on_message(filters.command("start"))
async def cmd_start(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        
        is_muted, spam_msg = check_spam(user_id)
        if is_muted:
            await message.reply(spam_msg)
            return
        
        if is_user_blocked(user_id):
            await message.reply("❌ Вы заблокированы в системе.")
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
🔍 **Проверить** - узнать информацию о пользователе  
ℹ️ **Помощь** - получить справку по работе бота
        """
        await message.reply(welcome_text, reply_markup=user_keyboard)
        logger.info(f"👤 Пользователь {user_id} запустил бота")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в cmd_start: {e}")
        await message.reply("❌ Произошла ошибка при запуске бота")

@app.on_message(filters.command("admin") & filters.user(ADMIN_IDS))
async def cmd_admin(client: Client, message: Message):
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Показать жалобы", callback_data="admin_show_reports")],
            [InlineKeyboardButton("🗑️ Удалить жалобы на пользователя", callback_data="admin_delete_user")],
            [InlineKeyboardButton("📢 Сделать объявление", callback_data="admin_announcement")],
            [InlineKeyboardButton("🚫 Заблокировать пользователя", callback_data="admin_block")],
            [InlineKeyboardButton("✅ Разблокировать пользователя", callback_data="admin_unblock")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
        ])
        
        await message.reply("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в cmd_admin: {e}")
        await message.reply("❌ Произошла ошибка при открытии админ-панели")

@app.on_message(filters.text & filters.private)
async def handle_messages(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        text = message.text.strip()
        
        is_muted, spam_msg = check_spam(user_id)
        if is_muted:
            await message.reply(spam_msg)
            return
        
        if is_user_blocked(user_id):
            await message.reply("❌ Вы заблокированы в системе.")
            return
        
        cleanup_old_states()
        
        # Обработка кнопок
        if text == "📝 Жалоба":
            await handle_complaint_button(client, message)
            return
            
        elif text == "🔍 Проверить":
            await handle_check_button(client, message)
            return
            
        elif text == "ℹ️ Помощь":
            await handle_help_button(client, message)
            return
        
        # Обработка состояний проверки
        if user_id in user_states and user_states[user_id]['state'] == "waiting_check_username":
            if text.startswith('@'):
                text = text[1:]
            
            is_valid, validation_msg = validate_username(text)
            if not is_valid:
                await message.reply(f"{validation_msg}\nПопробуйте снова:")
                return
            
            reports = get_user_reports(text)
            
            if not reports:
                await message.reply(f"ℹ️ По пользователю @{text} информации нет", reply_markup=user_keyboard)
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
                
                await message.reply("\n".join(response), reply_markup=user_keyboard)
                logger.info(f"🔍 Проверка пользователя @{text}: найдено {len(reports)} жалоб")
            
            del user_states[user_id]
            return
        
        # Обработка состояний жалобы
        if user_id in user_states:
            state_data = user_states[user_id]
            state = state_data['state']
            
            if state == UserState.WAITING_FOR_USERNAME:
                if text.startswith('@'):
                    text = text[1:]
                
                is_valid, validation_msg = validate_username(text)
                if not is_valid:
                    await message.reply(f"{validation_msg}\nПопробуйте снова:")
                    return
                
                user_username = message.from_user.username
                if user_username and user_username.lower() == text.lower():
                    await message.reply(
                        "❌ Нельзя подать жалобу на самого себя!",
                        reply_markup=user_keyboard
                    )
                    del user_states[user_id]
                    return
                
                user_data[user_id]['target_username'] = text
                user_states[user_id]['state'] = UserState.WAITING_FOR_COMMENT
                await message.reply("📝 **Введите комментарий:**\n(например: «не отправил товар»)")
                
            elif state == UserState.WAITING_FOR_COMMENT:
                if not text or len(text) < 5:
                    await message.reply("❌ Комментарий слишком короткий (минимум 5 символов). Попробуйте снова:")
                    return
                
                if len(text) > 500:
                    await message.reply("❌ Комментарий слишком длинный (максимум 500 символов). Попробуйте снова:")
                    return
                
                user_data[user_id]['comment'] = text
                user_states[user_id]['state'] = UserState.WAITING_FOR_PROOF
                await message.reply(
                    "📎 **Пришлите скриншот или фото как доказательство.**\n"
                    "Если доказательств нет, отправьте текст 'пропустить'"
                )
                
            elif state == UserState.WAITING_FOR_PROOF:
                if text.lower() == 'пропустить':
                    user_data[user_id]['proof_photo'] = None
                    user_states[user_id]['state'] = UserState.WAITING_FOR_STATUS
                    await message.reply(
                        "Вы пропустили добавление доказательства. Теперь выберите статус:",
                        reply_markup=status_keyboard
                    )
                else:
                    await message.reply("❌ Отправьте фото как доказательство или напишите 'пропустить'")
                
            elif state == UserState.WAITING_FOR_STATUS:
                if text == "другое":
                    user_states[user_id]['state'] = UserState.WAITING_FOR_CUSTOM_STATUS
                    await message.reply("Введите свой вариант статуса:")
                    return
                
                await save_report(client, user_id, text, message)
                
            elif state == UserState.WAITING_FOR_CUSTOM_STATUS:
                await save_report(client, user_id, text, message)
        
        # Обработка админских состояний
        elif user_id in ADMIN_IDS and user_id in user_states:
            state_data = user_states[user_id]
            state = state_data['state']
            
            if state == AdminState.WAITING_BLOCK_USER:
                try:
                    target_id = int(text)
                    user_states[user_id]['state'] = AdminState.WAITING_BLOCK_REASON
                    user_data[user_id]['block_target_id'] = target_id
                    await message.reply("Введите причину блокировки:")
                except ValueError:
                    await message.reply("❌ Введите числовой ID пользователя:")
                
            elif state == AdminState.WAITING_BLOCK_REASON:
                target_id = user_data[user_id]['block_target_id']
                reason = text
                
                success, result_msg = block_user(target_id, f"user_{target_id}", reason, user_id)
                await message.reply(result_msg)
                
                del user_states[user_id]
                if user_id in user_data:
                    del user_data[user_id]
                
            elif state == AdminState.WAITING_UNBLOCK_USER:
                try:
                    target_id = int(text)
                    success, result_msg = unblock_user(target_id)
                    await message.reply(result_msg)
                except ValueError:
                    await message.reply("❌ Введите числовой ID пользователя")
                
                del user_states[user_id]
                if user_id in user_data:
                    del user_data[user_id]
                    
            elif state == AdminState.WAITING_DELETE_USER:
                if text.startswith('@'):
                    text = text[1:]
                
                is_valid, validation_msg = validate_username(text)
                if not is_valid:
                    await message.reply(f"{validation_msg}\nПопробуйте снова:")
                    return
                
                success, result_msg = delete_user_reports(text)
                await message.reply(result_msg)
                del user_states[user_id]
                
            elif state == AdminState.WAITING_ANNOUNCEMENT:
                users = get_all_bot_users()
                success_count = 0
                fail_count = 0
                
                announcement_text = f"📢 **Объявление от администратора:**\n\n{text}"
                
                for user_id in users:
                    try:
                        await client.send_message(user_id, announcement_text)
                        success_count += 1
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"❌ Ошибка отправки объявления пользователю {user_id}: {e}")
                
                await message.reply(
                    f"📢 **Объявление отправлено!**\n"
                    f"✅ Успешно: {success_count}\n"
                    f"❌ Не удалось: {fail_count}"
                )
                del user_states[user_id]
        
        else:
            await message.reply(
                "🎯 Выберите действие с помощью кнопок ниже:",
                reply_markup=user_keyboard
            )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_messages: {e}")
        await message.reply("❌ Произошла ошибка при обработке сообщения")

async def save_report(client: Client, user_id: int, status: str, message: Message):
    try:
        target_username = user_data[user_id]['target_username']
        comment = user_data[user_id]['comment']
        proof_photo = user_data[user_id].get('proof_photo')
        
        report_id = add_report(user_id, target_username, status, comment, proof_photo)
        
        if report_id:
            try:
                admin_text = (
                    f"🆕 Новая жалоба #{report_id}\n"
                    f"👤 На: @{target_username}\n"
                    f"📝 Комментарий: {comment}\n"
                    f"🏷 Статус: {status}\n"
                    f"👥 От: {user_id}"
                )
                
                if proof_photo:
                    await client.send_photo(
                        ADMIN_IDS[0],
                        proof_photo,
                        caption=admin_text,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ Принять", callback_data=f"approve_{report_id}"),
                            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{report_id}")
                        ]])
                    )
                else:
                    await client.send_message(
                        ADMIN_IDS[0],
                        admin_text + "\n\n📸 Без доказательств",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ Принять", callback_data=f"approve_{report_id}"),
                            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{report_id}")
                        ]])
                    )
            except Exception as e:
                logger.error(f"❌ Ошибка уведомления админа: {e}")
            
            await message.reply(
                "✅ **Жалоба отправлена на модерацию!**\n"
                "Вы получите уведомление когда её проверят.",
                reply_markup=user_keyboard
            )
        else:
            await message.reply("❌ Ошибка сохранения заявки", reply_markup=user_keyboard)
        
        if user_id in user_states:
            del user_states[user_id]
        if user_id in user_data:
            del user_data[user_id]
            
        logger.info(f"📨 Отправлена на модерацию жалоба от {user_id} на {target_username}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении жалобы: {e}")
        await message.reply("❌ Ошибка при сохранении заявки", reply_markup=user_keyboard)

@app.on_message(filters.photo & filters.private)
async def handle_photos(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        
        is_muted, spam_msg = check_spam(user_id)
        if is_muted:
            await message.reply(spam_msg)
            return
        
        if user_id in user_states and user_states[user_id]['state'] == UserState.WAITING_FOR_PROOF:
            user_data[user_id]['proof_photo'] = message.photo.file_id
            user_states[user_id]['state'] = UserState.WAITING_FOR_STATUS
            
            await message.reply(
                "📸 Доказательство сохранено! Теперь выберите статус:",
                reply_markup=status_keyboard
            )
    except Exception as e:
        logger.error(f"❌ Ошибка обработки фото: {e}")
        await message.reply("❌ Ошибка при обработке фотографии")

@app.on_callback_query()
async def handle_callbacks(client: Client, callback_query):
    try:
        user_id = callback_query.from_user.id
        data = callback_query.data
        
        if user_id not in ADMIN_IDS:
            await callback_query.answer("❌ Нет доступа", show_alert=True)
            return
        
        if data.startswith("approve_"):
            report_id = int(data.split("_")[1])
            reporter_id, target_username = approve_report(report_id, user_id)
            
            if reporter_id:
                try:
                    await client.send_message(
                        reporter_id,
                        f"✅ Ваша жалоба на @{target_username} была одобрена модератором и добавлена в базу."
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка уведомления пользователя {reporter_id}: {e}")
                
                await callback_query.message.edit_text(
                    f"✅ Жалоба #{report_id} одобрена\n"
                    f"Пользователь @{target_username} уведомлен"
                )
                await callback_query.answer("Жалоба одобрена")
            else:
                await callback_query.answer("❌ Ошибка одобрения или жалоба уже обработана", show_alert=True)
        
        elif data.startswith("reject_"):
            report_id = int(data.split("_")[1])
            reporter_id = reject_report(report_id, user_id)
            
            if reporter_id:
                try:
                    await client.send_message(
                        reporter_id,
                        "❌ Ваша жалоба была отклонена модератором из-за недостаточных доказательств."
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка уведомления пользователя {reporter_id}: {e}")
                
                await callback_query.message.edit_text(f"❌ Жалоба #{report_id} отклонена")
                await callback_query.answer("Жалоба отклонена")
            else:
                await callback_query.answer("❌ Ошибка отклонения или жалоба уже обработана", show_alert=True)
        
        elif data == "admin_show_reports":
            reports = get_pending_reports()
            if not reports:
                await callback_query.message.edit_text("📭 Нет жалоб ожидающих модерации")
            else:
                text = f"📋 Жалобы на модерации ({len(reports)}):\n\n"
                for report in reports[:10]:
                    report_id, reporter_id, target_username, status, comment, proof_photo = report
                    proof_text = "📸" if proof_photo else "📝"
                    text += f"#{report_id} {proof_text} @{target_username}\n{status}: {comment[:100]}...\n\n"
                
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]
                ])
                await callback_query.message.edit_text(text, reply_markup=keyboard)
            await callback_query.answer()
        
        elif data == "admin_delete_user":
            user_states[user_id] = {
                'state': AdminState.WAITING_DELETE_USER,
                'timestamp': datetime.now()
            }
            await callback_query.message.edit_text(
                "Введите юзернейм пользователя для удаления ВСЕХ жалоб (без @):"
            )
            await callback_query.answer()
            
        elif data == "admin_announcement":
            user_states[user_id] = {
                'state': AdminState.WAITING_ANNOUNCEMENT,
                'timestamp': datetime.now()
            }
            await callback_query.message.edit_text(
                "📢 Введите текст объявления для всех пользователей:"
            )
            await callback_query.answer()
        
        elif data == "admin_block":
            user_states[user_id] = {
                'state': AdminState.WAITING_BLOCK_USER,
                'timestamp': datetime.now()
            }
            await callback_query.message.edit_text(
                "Введите ID пользователя для блокировки (только число):"
            )
            await callback_query.answer()
        
        elif data == "admin_unblock":
            user_states[user_id] = {
                'state': AdminState.WAITING_UNBLOCK_USER,
                'timestamp': datetime.now()
            }
            await callback_query.message.edit_text(
                "Введите ID пользователя для разблокировки (только число):"
            )
            await callback_query.answer()
        
        elif data == "admin_stats":
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
            
            await callback_query.message.edit_text(stats_text)
            await callback_query.answer()
            
        elif data == "admin_back":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Показать жалобы", callback_data="admin_show_reports")],
                [InlineKeyboardButton("🗑️ Удалить жалобы на пользователя", callback_data="admin_delete_user")],
                [InlineKeyboardButton("📢 Сделать объявление", callback_data="admin_announcement")],
                [InlineKeyboardButton("🚫 Заблокировать пользователя", callback_data="admin_block")],
                [InlineKeyboardButton("✅ Разблокировать пользователя", callback_data="admin_unblock")],
                [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
            ])
            await callback_query.message.edit_text("🛠 **Панель администратора**\nВыберите действие:", reply_markup=keyboard)
            await callback_query.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки callback: {e}")
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)

# ===== ЗАПУСК =====
if __name__ == "__main__":
    print("🚀 Starting bot for Bothost...")
    init_db()
    app.run()
    print("🤖 Bot is running on Bothost!")
