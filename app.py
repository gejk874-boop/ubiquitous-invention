import os
import asyncio
from hydrogram import Client
from flask import Flask

# Настройки
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
BOT_TOKEN = "8223288154:AAEGGJGOXzIAUNRocxzKL7x-IAUhVfEb-xw"

# Создаем клиента
app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=1
)

# Импортируем основной код
from main import init_db

# Flask app для Bothost
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running!"

@web_app.route('/health')
def health():
    return "OK"

# Запускаем бота
async def run_bot():
    init_db()
    await app.start()
    print("🤖 Bot started on Bothost!")
    # Бесконечный цикл
    await asyncio.Event().wait()

# Запуск
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.create_task(run_bot())

application = web_app
