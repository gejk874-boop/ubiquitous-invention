from main import app, init_db
from flask import Flask

# Создаем Flask приложение для Bothost
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "🤖 Telegram Bot is running!"

@web_app.route('/health')
def health():
    return "OK"

# Инициализируем базу данных
init_db()

# Bothost будет использовать это приложение
application = web_app

print("✅ app.py loaded - Bot is ready!")
