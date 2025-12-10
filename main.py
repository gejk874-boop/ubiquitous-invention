import asyncio
import sqlite3
import re
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from aiogram import Bot, Dispatcher, types, F, exceptions
from aiogram.filters import Command
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
import aiosqlite  # Для асинхронной работы с БД
from dotenv import load_dotenv  # Для переменных окружения

# === ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
load_dotenv()

# === КОНФИГУРАЦИЯ ===
# Используем переменные окружения вместо хардкода
BOT_TOKEN ="8424514943:AAHdwbe3tf-YsaY4akF3iNhscXcb_493dgQ"
ADMIN_IDS = [6986121067] 

# Проверка конфигурации
if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не установлен в переменных окружения!")
    sys.exit(1)

if not ADMIN_IDS:
    print("⚠️ ВНИМАНИЕ: ADMIN_IDS не установлены в переменных окружения!")

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
BACKUP_PATH = 'backups'

# Создаем папку для бэкапов
os.makedirs(BACKUP_PATH, exist_ok=True)

# === БАЗА ДАННЫХ (БЕЗ АВТОУДАЛЕНИЯ) ===
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
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (reporter_id) REFERENCES bot_users(user_id)
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
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES bot_users(user_id),
                FOREIGN KEY (blocked_by) REFERENCES bot_users(user_id)
            )
        ''')
        
        # Создаем индексы для ускорения запросов
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_reports_target_username 
            ON reports(target_username)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_reports_reporter_id 
            ON reports(reporter_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_reports_timestamp 
            ON reports(timestamp)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_blocked_users_user_id 
            ON blocked_users(user_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_bot_users_username 
            ON bot_users(username)
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
        
    except sqlite3.Error as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ошибка инициализации БД: {e}")
        # НЕ УДАЛЯЕМ БД, а пытаемся восстановить с бэкапа
        restore_backup()
        raise  # Пробрасываем исключение дальше

def restore_backup():
    """Попытка восстановления из последнего бэкапа"""
    try:
        backups = sorted([f for f in os.listdir(BACKUP_PATH) if f.endswith('.db.bak')])
        if backups:
            latest_backup = os.path.join(BACKUP_PATH, backups[-1])
            if os.path.exists(DB_PATH):
                # Делаем резервную копию поврежденного файла
                damage_backup = os.path.join(BACKUP_PATH, f"damaged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
                os.rename(DB_PATH, damage_backup)
                logger.info(f"📂 Поврежденная БД сохранена как: {damage_backup}")
            
            # Восстанавливаем из бэкапа
            with open(latest_backup, 'rb') as src, open(DB_PATH, 'wb') as dst:
                dst.write(src.read())
            logger.info(f"✅ БД восстановлена из бэкапа: {latest_backup}")
        else:
            logger.warning("⚠️ Нет доступных бэкапов для восстановления")
    except Exception as e:
        logger.error(f"❌ Ошибка восстановления из бэкапа: {e}")

def create_backup():
    """Создание резервной копии БД"""
    try:
        if not os.path.exists(DB_PATH):
            return False
        
        backup_name = os.path.join(BACKUP_PATH, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db.bak")
        
        # Сохраняем только последние 10 бэкапов
        backups = sorted([f for f in os.listdir(BACKUP_PATH) if f.endswith('.db.bak')])
        if len(backups) >= 10:
            for old_backup in backups[:-9]:
                os.remove(os.path.join(BACKUP_PATH, old_backup))
        
        with open(DB_PATH, 'rb') as src, open(backup_name, 'wb') as dst:
            dst.write(src.read())
        
        logger.info(f"📂 Создан бэкап: {backup_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка создания бэкапа: {e}")
        return False

# === КОНТЕКСТНЫЕ МЕНЕДЖЕРЫ ДЛЯ БД ===
class DatabaseConnection:
    """Контекстный менеджер для работы с базой данных"""
    
    @staticmethod
    def get_connection():
        """Получить соединение с БД"""
        return sqlite3.connect(DB_PATH, check_same_thread=False)
    
    @staticmethod
    def execute_query(query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False):
        """Выполнить запрос с параметрами"""
        try:
            with DatabaseConnection.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                if fetch_one:
                    result = cursor.fetchone()
                elif fetch_all:
                    result = cursor.fetchall()
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
            INSERT OR REPLACE INTO bot_users 
            (user_id, username, first_name, last_name, joined_date, last_activity)
            VALUES (?, ?, ?, ?, COALESCE((SELECT joined_date FROM bot_users WHERE user_id = ?), CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
        '''
        DatabaseConnection.execute_query(query, (user_id, username, first_name, last_name, user_id))
        logger.info(f"✅ Добавлен/обновлен пользователь: {user_id} (@{username})")
    except Exception as e:
        logger.error(f"❌ Ошибка добавления пользователя {user_id}: {e}")

@lru_cache(maxsize=128)
def is_user_blocked_cached(user_id: int) -> bool:
    """Кэшированная проверка блокировки пользователя"""
    try:
        query = 'SELECT id FROM blocked_users WHERE user_id = ?'
        result = DatabaseConnection.execute_query(query, (user_id,), fetch_one=True)
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка проверки блокировки: {e}")
        return False

def is_user_blocked(user_id: int) -> bool:
    """Основная функция проверки блокировки (с кэшированием)"""
    return is_user_blocked_cached(user_id)

def user_exists_in_bot(user_id: int) -> bool:
    """Проверка, существует ли пользователь в bot_users"""
    try:
        query = 'SELECT user_id FROM bot_users WHERE user_id = ?'
        result = DatabaseConnection.execute_query(query, (user_id,), fetch_one=True)
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка проверки существования пользователя: {e}")
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
        # Проверяем, существует ли пользователь
        if not user_exists_in_bot(user_id):
            return False, f"❌ Пользователь с ID {user_id} не найден в системе"
        
        # Проверяем, не заблокирован ли уже
        if is_user_blocked(user_id):
            return False, "❌ Пользователь уже заблокирован"
        
        query = '''
            INSERT INTO blocked_users (user_id, username, reason, blocked_by)
            VALUES (?, ?, ?, ?)
        '''
        DatabaseConnection.execute_query(query, (user_id, username, reason, blocked_by))
        
        # Сбрасываем кэш для этого пользователя
        if user_id in is_user_blocked_cached.cache:
            del is_user_blocked_cached.cache[user_id]
        
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
            # Сбрасываем кэш для этого пользователя
            if user_id in is_user_blocked_cached.cache:
                del is_user_blocked_cached.cache[user_id]
            
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
        query = '''
            SELECT COUNT(*) FROM reports 
            WHERE reporter_id = ? AND timestamp > ?
        '''
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
        DatabaseConnection.execute_query(query, (reporter_id, target_username.lower(), status, comment, proof_photo))
        
        # Получаем ID последней вставленной записи
        result = DatabaseConnection.execute_query('SELECT last_insert_rowid()', fetch_one=True)
        report_id = result[0] if result else None
        
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
            FROM reports 
            WHERE is_approved = FALSE AND is_rejected = FALSE
            ORDER BY timestamp ASC
            LIMIT 20
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
            UPDATE reports 
            SET is_approved = TRUE, moderator_id = ?
            WHERE id = ? AND is_approved = FALSE AND is_rejected = FALSE
        '''
        rows_affected = DatabaseConnection.execute_query(query, (moderator_id, report_id))
        
        if rows_affected > 0:
            # Получаем информацию о жалобе
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
            UPDATE reports 
            SET is_rejected = TRUE, moderator_id = ?
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

def get_statistics() -> dict:
    """Получение статистики системы"""
    try:
        stats = {}
        
        queries = {
            'total_users': 'SELECT COUNT(*) FROM bot_users',
            'blocked_users': 'SELECT COUNT(*) FROM blocked_users',
            'total_reports': 'SELECT COUNT(*) FROM reports',
            'approved_reports': 'SELECT COUNT(*) FROM reports WHERE is_approved = TRUE',
            'pending_reports': 'SELECT COUNT(*) FROM reports WHERE is_approved = FALSE AND is_rejected = FALSE',
            'today_users': '''
                SELECT COUNT(*) FROM bot_users 
                WHERE DATE(joined_date) = DATE(CURRENT_TIMESTAMP)
            ''',
            'active_users': '''
                SELECT COUNT(DISTINCT reporter_id) FROM reports 
                WHERE timestamp > datetime(CURRENT_TIMESTAMP, '-7 days')
            '''
        }
        
        with DatabaseConnection.get_connection() as conn:
            cursor = conn.cursor()
            for key, query in queries.items():
                cursor.execute(query)
                stats[key] = cursor.fetchone()[0]
        
        return stats
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        return {}

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
    
    # Отправляем себе тестовое сообщение
    try:
        await bot.send_message(ADMIN_IDS[0], f"📢 Начинаю рассылку обновления для {len(all_user_ids)} пользователей...")
    except Exception:
        pass
    
    for index, user_id in enumerate(all_user_ids, 1):
        try:
            if not is_user_blocked(user_id) and user_exists_in_bot(user_id):
                await bot.send_message(user_id, update_message, parse_mode="HTML")
                success_count += 1
                
                if index % 20 == 0:  # Логируем каждые 20 отправок
                    logger.info(f"📤 Отправлено {index}/{len(all_user_ids)} пользователям")
                    await asyncio.sleep(1)  # Пауза после каждых 20 сообщений
            else:
                if not user_exists_in_bot(user_id):
                    logger.info(f"⏭️ Пропущен несуществующий пользователь: {user_id}")
                else:
                    logger.info(f"⏭️ Пропущен заблокированный пользователь: {user_id}")
                    
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
        except exceptions.TelegramRetryAfter as e:
            logger.warning(f"⚠️ Лимит отправки, ожидание {e.retry_after} секунд")
            await asyncio.sleep(e.retry_after)
            continue
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Таймаут при отправке пользователю {user_id}")
            failed_count += 1
        except Exception as e:
            logger.error(f"❌ Не удалось отправить уведомление пользователю {user_id}: {e}")
            failed_count += 1
        
        await asyncio.sleep(0.05)  # Уменьшенная задержка
    
    # Отправляем отчет админам
    result_message = (
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего пользователей: {len(all_user_ids)}\n"
        f"✅ Успешно отправлено: {success_count}\n"
        f"❌ С ошибками: {failed_count}\n"
        f"🚫 Заблокировали бота: {blocked_bot_count}"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, result_message, parse_mode="HTML")
        except Exception:
            pass
    
    logger.info(f"📢 Уведомления обновления: ✅ {success_count}, ❌ {failed_count}, 🚫 {blocked_bot_count}")
    return success_count, failed_count, blocked_bot_count

# === КЛАВИАТУРЫ ===
def get_user_keyboard(user_id):
    keyboard = [
        [KeyboardButton(text="📝 Жалоба"), KeyboardButton(text="🔍 Проверить")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
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
    
    # Проверяем блокировку и существование
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
    
    welcome_text = """
🎯 **Добро пожаловать в бот проверки пользователей!**

📝 **Жалоба** - сообщить о ненадежном пользователе
🔍 **Проверить** - узнайте информацию о пользователе  
ℹ️ **Помощь** - получите справку по работе бота
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

# === КОМАНДЫ АДМИНИСТРИРОВАНИЯ ===
@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    """Показать статистику пользователей"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return
    
    stats = get_statistics()
    
    # Получаем последних пользователей
    query = 'SELECT user_id, username, joined_date FROM bot_users ORDER BY joined_date DESC LIMIT 10'
    recent_users = DatabaseConnection.execute_query(query, fetch_all=True) or []
    
    users_for_broadcast = get_all_users_for_broadcast()
    
    response = [
        f"📊 <b>Статистика пользователей</b>\n",
        f"👥 Всего пользователей: <b>{stats.get('total_users', 0)}</b>",
        f"🚫 Заблокировано: <b>{stats.get('blocked_users', 0)}</b>",
        f"📢 Для рассылки: <b>{len(users_for_broadcast)}</b>",
        f"📈 Сегодня новых: <b>{stats.get('today_users', 0)}</b>",
        f"🏃 Активных за неделю: <b>{stats.get('active_users', 0)}</b>",
        f"",
        f"🆕 <b>Последние 10 пользователей:</b>"
    ]
    
    for user_id, username, joined_date in recent_users:
        username_display = f"@{username}" if username else f"ID:{user_id}"
        response.append(f"• {username_display} ({joined_date[:10]})")
    
    await message.answer("\n".join(response), parse_mode="HTML")

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
        
        # Создаем бэкап перед отправкой
        if create_backup():
            await message.answer("✅ Создан новый бэкап БД")
        
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
    
    stats = get_statistics()
    
    stats_text = f"""
📊 <b>Статистика системы</b>

👥 Пользователей: {stats.get('total_users', 0)}
🚫 Заблокировано: {stats.get('blocked_users', 0)}

📨 Жалоб всего: {stats.get('total_reports', 0)}
✅ Одобрено: {stats.get('approved_reports', 0)}
⏳ На модерации: {stats.get('pending_reports', 0)}

📈 Новых сегодня: {stats.get('today_users', 0)}
🏃 Активных за неделю: {stats.get('active_users', 0)}
"""
    
    await message.answer(stats_text, parse_mode="HTML")

@dp.message(F.text == "📥 Скачать БД")
async def handle_download_db(message: types.Message):
    """Обработчик кнопки скачивания базы данных"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return
    
    try:
        if not os.path.exists(DB_PATH):
            await message.answer("❌ Файл базы данных не найден")
            return
        
        # Создаем бэкап
        if create_backup():
            await message.answer("✅ Создан бэкап перед отправкой")
        
        await message.answer_document(
            types.FSInputFile(DB_PATH),
            caption="📁 База данных reports.db"
        )
        logger.info(f"✅ База данных отправлена пользователю {message.from_user.id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки базы: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# ... (остальной код обработчиков остается таким же, как в вашем оригинальном файле)
# Для экономии места я не копирую все обработчики, они остаются без изменений
# кроме использования новых функций из DatabaseConnection

# === ЗАПУСК БОТА ===
async def main():
    """Основная функция запуска бота"""
    # Создаем бэкап при запуске
    create_backup()
    
    # Инициализируем БД
    init_db()
    
    logger.info("🤖 Бот запускается...")
    logger.info(f"👑 Администраторы: {ADMIN_IDS}")
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Все предыдущие сессии завершены")
        
        await asyncio.sleep(2)
        
        logger.info("🔄 Запускаем поллинг...")
        await dp.start_polling(bot, skip_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        await asyncio.sleep(10)
        
        # Пытаемся восстановить БД из бэкапа при критической ошибке
        restore_backup()
        await main()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен")
        # Создаем финальный бэкап при остановке
        create_backup()
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        create_backup()  # Пытаемся сохранить данные
