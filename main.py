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
gc.set_threshold(700, 10, 5)  # Агрессивная сборка мусора
os.environ['SQLITE_TMPDIR'] = '/tmp'

# ===== НАСТРОЙКА =====
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
BOT_TOKEN = "8223288154:AAEGGJGOXzIAUNRocxzKL7x-IAUhVfEb-xw"
ADMIN_IDS = [6986121067]

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

status_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("обманщик"), KeyboardButton("ненадёжный")],
        [KeyboardButton("мошенник"), KeyboardButton("другое")]
    ],
    resize_keyboard=True
)

# ===== ВАЛИДАЦИЯ =====
def validate_username(username):
    """Валидация юзернейма"""
    if not username or len(username) < 3:
        return False, "❌ Юзернейм слишком короткий (минимум 3 символа)"
    
    if len(username) > 32:
        return False, "❌ Юзернейм слишком длинный (максимум 32 символа)"
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "❌ Юзернейм может содержать только буквы, цифры и подчеркивания"
    
    return True, "✅ Юзернейм корректен"

def cleanup_old_states():
    """Очистка старых состояний"""
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
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_username ON reports(target_username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_approved ON reports(is_approved)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocked_user ON blocked_users(user_id)')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка БД: {e}")

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

# ===== ОБРАБОТЧИКИ КОМАНД =====
@Client.on_message(filters.command("start"))
async def cmd_start(client: Client, message: Message):
    if is_user_blocked(message.from_user.id):
        await message.reply("❌ Вы заблокированы в системе.")
        return
        
    welcome_text = """
🤖 Бот для проверки пользователей

Основные команды:
/add - добавить жалобу (с доказательствами)
/check @username - проверить пользователя
/help - справка

Внимание: Максимум 5 жалоб в час!
Жалобы проходят модерацию перед публикацией.
    """
    await message.reply(welcome_text)
    logger.info(f"👤 Пользователь {message.from_user.id} запустил бота")

@Client.on_message(filters.command("admin") & filters.user(ADMIN_IDS))
async def cmd_admin(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Жалобы на модерации", callback_data="admin_pending")],
        [InlineKeyboardButton("🚫 Заблокировать пользователя", callback_data="admin_block")],
        [InlineKeyboardButton("✅ Разблокировать пользователя", callback_data="admin_unblock")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.reply("🛠 Панель администратора:", reply_markup=keyboard)

@Client.on_message(filters.command("add"))
async def cmd_add(client: Client, message: Message):
    user_id = message.from_user.id
    
    if is_user_blocked(user_id):
        await message.reply("❌ Вы заблокированы в системе.")
        return
    
    recent_count = get_recent_reports_count(user_id)
    if recent_count >= 5:
        await message.reply("❌ Превышен лимит: максимум 5 жалоб в час!")
        return
    
    user_states[user_id] = {
        'state': UserState.WAITING_FOR_USERNAME,
        'timestamp': datetime.now()
    }
    user_data[user_id] = {}
    
    await message.reply(
        "Введите юзернейм человека, о котором хотите сообщить "
        "(например: @username или просто username):"
    )
    logger.info(f"👤 Пользователь {user_id} начал добавление жалобы")

@Client.on_message(filters.command("check"))
async def cmd_check(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            await message.reply("❌ Используйте: /check @username")
            return
        
        username = message.command[1].strip()
        if username.startswith('@'):
            username = username[1:]
        
        is_valid, validation_msg = validate_username(username)
        if not is_valid:
            await message.reply(f"❌ Неверный формат юзернейма: {validation_msg}")
            return
        
        reports = get_user_reports(username)
        
        if not reports:
            await message.reply(f"ℹ️ По пользователю @{username} информации нет")
            return
        
        statuses = set()
        comments = []
        
        for status, comment, timestamp in reports:
            statuses.add(status)
            comments.append(f"• {comment} ({timestamp[:10]})")
        
        response = [
            f"🔍 Юзернейм: @{username}",
            f"🏷 Статусы: {', '.join(sorted(statuses))}",
            f"📝 Комментарии ({len(comments)}):",
            *comments[:5],
            f"📊 Всего подтвержденных заявок: {len(reports)}"
        ]
        
        await message.reply("\n".join(response))
        logger.info(f"🔍 Проверка пользователя @{username}: найдено {len(reports)} жалоб")
    
    except Exception as e:
        logger.error(f"❌ Ошибка в команде /check: {e}")
        await message.reply("❌ Произошла ошибка при проверке")

@Client.on_message(filters.command("help"))
async def cmd_help(client: Client, message: Message):
    help_text = """
📋 Доступные команды:

/start - начать работу
/add - добавить жалобу на пользователя (с доказательствами)
/check @username - проверить пользователя
/help - эта справка

Для админов:
/admin - панель управления

Процесс добавления:
1. Введите юзернейм (@username или просто username)
2. Введите комментарий
3. Пришлите скриншот как доказательство
4. Выберите статус
5. Жалоба отправится на модерацию
    """
    await message.reply(help_text)

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
@Client.on_message(filters.text & filters.private)
async def handle_messages(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        text = message.text.strip()
        
        cleanup_old_states()
        
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
                
                user_data[user_id]['target_username'] = text
                user_states[user_id]['state'] = UserState.WAITING_FOR_COMMENT
                await message.reply("Введите комментарий (например: «не отправил товар»):")
                
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
                    "📎 Пришлите скриншот или фото как доказательство.\n"
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
                    await message.reply("Введите свой вариант статуса:", reply_markup=ReplyKeyboardMarkup(remove_keyboard=True))
                    return
                
                await save_report(client, user_id, text, message)
                
            elif state == UserState.WAITING_FOR_CUSTOM_STATUS:
                await save_report(client, user_id, text, message)
        
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
        
        else:
            await message.reply(
                "Используйте команды:\n"
                "/start - начало работы\n"
                "/add - добавить жалобу\n" 
                "/check @username - проверить пользователя\n"
                "/help - справка"
            )
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки сообщения: {e}")
        await message.reply("❌ Произошла ошибка")

async def save_report(client: Client, user_id: int, status: str, message: Message):
    """Сохраняет жалобу и отправляет уведомление"""
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
                "✅ Заявка отправлена на модерацию! Вы получите уведомление когда её проверят.",
                reply_markup=ReplyKeyboardMarkup(remove_keyboard=True)
            )
        else:
            await message.reply("❌ Ошибка сохранения заявки")
        
        if user_id in user_states:
            del user_states[user_id]
        if user_id in user_data:
            del user_data[user_id]
            
        logger.info(f"📨 Отправлена на модерацию жалоба от {user_id} на {target_username}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении жалобы: {e}")
        await message.reply("❌ Ошибка при сохранении заявки")

@Client.on_message(filters.photo & filters.private)
async def handle_photos(client: Client, message: Message):
    """Обработка фотографий как доказательств"""
    try:
        user_id = message.from_user.id
        
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

@Client.on_callback_query()
async def handle_callbacks(client: Client, callback_query):
    """Обработка callback кнопок"""
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
        
        elif data == "admin_pending":
            reports = get_pending_reports()
            if not reports:
                await callback_query.message.edit_text("📭 Нет жалоб ожидающих модерации")
            else:
                text = f"📋 Жалобы на модерации ({len(reports)}):\n\n"
                for report in reports[:10]:
                    report_id, reporter_id, target_username, status, comment, proof_photo = report
                    proof_text = "📸" if proof_photo else "📝"
                    text += f"#{report_id} {proof_text} @{target_username}\n{status}: {comment}\n—\n"
                
                await callback_query.message.edit_text(text)
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
            
            conn.close()
            
            stats_text = (
                f"📊 Статистика системы:\n\n"
                f"📨 Всего жалоб: {total_reports}\n"
                f"✅ Одобренных жалоб: {approved}\n"
                f"⏳ Ожидают модерации: {pending}\n"
                f"👤 Уникальных пользователей в базе: {unique_users}\n"
                f"🚫 Заблокировано пользователей: {blocked}"
            )
            
            await callback_query.message.edit_text(stats_text)
            await callback_query.answer()
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки callback: {e}")
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)

# ===== ЗАПУСК =====
async def run_bot():
    """Оптимизированный запуск для бесплатного хостинга"""
    init_db()
    
    app = Client(
        "my_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        workers=2,
        sleep_threshold=30,
    )
    
    try:
        await app.start()
        logger.info("✅ Бот успешно запущен на бесплатном плане!")
        
        try:
            await app.send_message(ADMIN_IDS[0], "🤖 Бот запущен в эконом-режиме!")
        except:
            pass
        
        while True:
            await asyncio.sleep(1800)
            cleanup_old_states()
            gc.collect()
            logger.info("💾 Состояние: активен (эконом-режим)")
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        raise
    finally:
        if await app.is_connected():
            await app.stop()
        logger.info("⏹️ Бот остановлен")

async def main():
    """Основная функция с автоперезапуском"""
    restart_count = 0
    while True:
        try:
            restart_count += 1
            logger.info(f"🔄 Запуск бота (попытка #{restart_count})")
            await run_bot()
            
        except KeyboardInterrupt:
            logger.info("⏹️ Бот остановлен пользователем")
            break
            
        except Exception as e:
            logger.error(f"🔄 Перезапуск через 30 сек. Ошибка: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
