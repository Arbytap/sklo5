#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Main entry point for the WorkerTracker bot.
Flask server and background Telegram bot.
"""

import os
import logging
import threading
import time
import subprocess
import signal
import atexit
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, send_from_directory, abort
import json

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bvjhgf7834nfvwuei8743890bfndsfj")

# Initialize database
from database import init_db
init_db()

# Обновление структуры базы данных
from update_db_structure import update_db_structure
update_db_structure()

# Инициализация бота для webhook
if os.getenv("BOT_MODE", "polling").lower() == "webhook":
    try:
        logger.info("Предварительная инициализация бота для webhook режима")
        import bot as worker_bot
        worker_bot.setup_bot()
        logger.info("Бот успешно инициализирован")
        
        # Создаем глобальную переменную для хранения состояния инициализации
        webhook_bot_initialized = True
    except Exception as e:
        logger.error(f"Ошибка при инициализации бота: {e}")
        webhook_bot_initialized = False

# Global variables
bot_process = None
BOT_PID_FILE = "bot.pid"

def start_bot_in_background():
    """Start the Telegram bot in background"""
    global bot_process
    
    # First kill any existing bot process
    try:
        if os.path.exists(BOT_PID_FILE):
            with open(BOT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Killed existing bot process with PID {pid}")
            except OSError:
                logger.info(f"No process with PID {pid} found")
    except Exception as e:
        logger.error(f"Error killing existing bot process: {e}")
    
    # Delete webhook first
    try:
        token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        if token:
            import requests
            response = requests.post(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true")
            logger.info(f"Webhook deleted: {response.json()}")
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
    
    # Start the bot process
    try:
        bot_process = subprocess.Popen(["python", "standalone_polling_bot.py"])
        
        # Save bot PID to file
        with open(BOT_PID_FILE, 'w') as f:
            f.write(str(bot_process.pid))
        
        logger.info(f"Bot started with PID {bot_process.pid}")
        return True
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        return False

def cleanup_on_exit():
    """Cleanup function to kill the bot process on exit"""
    global bot_process
    
    if bot_process:
        logger.info(f"Killing bot process with PID {bot_process.pid}")
        bot_process.terminate()
    
    # Also try to kill from PID file
    try:
        if os.path.exists(BOT_PID_FILE):
            with open(BOT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Killed bot process with PID {pid} from file")
            except OSError:
                pass
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

# Register the cleanup function
atexit.register(cleanup_on_exit)

@app.route('/')
def index():
    """Main page of the server"""
    # Get webhook information for display
    token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    
    try:
        import requests
        if token:
            response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
            if response.status_code == 200:
                webhook_info = response.json().get("result", {})
                webhook_url = webhook_info.get("url", "Not set")
                webhook_status = "Active" if webhook_url else "Not set"
                last_error = webhook_info.get("last_error_message", "No errors")
            else:
                webhook_url = "Error getting information"
                webhook_status = "Unknown"
                last_error = "No data"
        else:
            webhook_url = "Token not set"
            webhook_status = "Cannot check"
            last_error = "No data"
    except Exception as e:
        webhook_url = "Error getting information"
        webhook_status = "Error"
        last_error = str(e)
    
    # Check if bot is running
    bot_status = "Unknown"
    bot_pid = None
    
    try:
        if os.path.exists(BOT_PID_FILE):
            with open(BOT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)  # Check if process exists
                bot_status = "Running"
                bot_pid = pid
            except OSError:
                bot_status = "Not running (process dead)"
        else:
            bot_status = "Not running (no PID file)"
    except Exception as e:
        bot_status = f"Error checking: {str(e)}"
    
    env_info = {
        'webhook_url': os.getenv("WEBHOOK_URL", "Not configured"),
        'bot_token': "Configured" if token else "Not configured",
        'bot_mode': os.getenv("BOT_MODE", "polling"),
        'port': os.getenv("FLASK_RUN_PORT", "5000"),
        'bot_status': bot_status,
        'bot_pid': bot_pid
    }
    
    return render_template('index.html', 
                          env_info=env_info, 
                          webhook_status=webhook_status, 
                          last_error=last_error)

@app.route('/start_bot')
def start_bot():
    """Start the Telegram bot"""
    if start_bot_in_background():
        return """
        <html>
            <head>
                <meta http-equiv="refresh" content="3;url=/" />
            </head>
            <body>
                <h2>Бот запущен! Перенаправление на главную страницу...</h2>
            </body>
        </html>
        """
    else:
        return "Ошибка при запуске бота"

@app.route('/stop_bot')
def stop_bot():
    """Stop the Telegram bot"""
    global bot_process
    
    try:
        if bot_process:
            bot_process.terminate()
            bot_process = None
            
        # Also try to kill from PID file
        if os.path.exists(BOT_PID_FILE):
            with open(BOT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            
            os.remove(BOT_PID_FILE)
            
        return """
        <html>
            <head>
                <meta http-equiv="refresh" content="3;url=/" />
            </head>
            <body>
                <h2>Бот остановлен! Перенаправление на главную страницу...</h2>
            </body>
        </html>
        """
    except Exception as e:
        return f"Ошибка при остановке бота: {str(e)}"

@app.route('/setup_webhook')
def setup_webhook():
    """Set up webhook for Telegram bot"""
    token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")
    
    if not token or not webhook_url:
        return jsonify({"status": "error", "message": "Token or webhook URL not configured"})
    
    try:
        import requests
        full_webhook_url = f"{webhook_url}/webhook"
        response = requests.get(
            f"https://api.telegram.org/bot{token}/setWebhook?url={full_webhook_url}"
        )
        
        if response.status_code == 200 and response.json().get("ok"):
            return """
            <html>
                <head>
                    <meta http-equiv="refresh" content="3;url=/" />
                </head>
                <body>
                    <h2>Webhook установлен успешно! Перенаправление на главную страницу...</h2>
                </body>
            </html>
            """
        else:
            error_msg = response.json().get("description", "Unknown error")
            return f"Error setting webhook: {error_msg}"
    except Exception as e:
        return f"Error setting webhook: {str(e)}"

@app.route('/remove_webhook')
def remove_webhook():
    """Remove webhook for Telegram bot"""
    token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        return jsonify({"status": "error", "message": "Token not configured"})
    
    try:
        import requests
        response = requests.get(
            f"https://api.telegram.org/bot{token}/deleteWebhook"
        )
        
        if response.status_code == 200 and response.json().get("ok"):
            return """
            <html>
                <head>
                    <meta http-equiv="refresh" content="3;url=/" />
                </head>
                <body>
                    <h2>Webhook удален успешно! Перенаправление на главную страницу...</h2>
                </body>
            </html>
            """
        else:
            error_msg = response.json().get("description", "Unknown error")
            return f"Error removing webhook: {error_msg}"
    except Exception as e:
        return f"Error removing webhook: {str(e)}"

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Handle webhook from Telegram"""
    logger.info(f"Webhook request received: Method={request.method}, Remote IP={request.remote_addr}")
    
    if request.method == 'GET':
        logger.info("Returning webhook operational status for GET request")
        return jsonify({"status": "success", "message": "Webhook endpoint is operational"})
    elif request.method == 'POST':
        try:
            logger.info(f"Headers: {dict(request.headers)}")
            
            # Сохраняем сырые данные запроса
            raw_data = request.data.decode('utf-8')
            logger.info(f"Raw request data: {raw_data}")
            
            # Сохраняем запрос в файл для анализа
            with open('last_webhook_request.json', 'w', encoding='utf-8') as f:
                f.write(raw_data)
            logger.info("Saved request data to last_webhook_request.json")
            
            # Разбираем JSON
            update = request.get_json(force=True)
            logger.info(f"Received update: {json.dumps(update)[:200]}...")
            
            # Используем глобально инициализированный бот если возможно
            global webhook_bot_initialized
            
            if 'webhook_bot_initialized' in globals() and webhook_bot_initialized:
                logger.info("Используем предварительно инициализированный бот")
                import bot as worker_bot
                from telegram import Update
                # Получаем updater из функции setup_bot для обработки запроса
                updater = worker_bot.setup_bot()
            else:
                # Резервный вариант - инициализируем при первом запросе
                logger.info("Предварительная инициализация не удалась, инициализируем бот сейчас")
                import bot as worker_bot
                from telegram import Update
                
                updater = worker_bot.setup_bot()
                logger.info("Бот инициализирован в момент обработки запроса")
            
            # Process the update
            logger.info("Processing update with bot dispatcher")
            
            # Правильно получаем диспетчера и бота из функции setup_bot
            dispatcher = updater.dispatcher if 'updater' in locals() else worker_bot.setup_bot().dispatcher
            dispatcher.process_update(Update.de_json(update, dispatcher.bot))
            logger.info("Update processed successfully")
            return jsonify({"status": "success"})
            
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # В случае ошибки тоже пытаемся сохранить данные запроса
            try:
                raw_data = request.data.decode('utf-8')
                with open('error_webhook_request.json', 'w', encoding='utf-8') as f:
                    f.write(raw_data)
                logger.error("Saved error request data to error_webhook_request.json")
            except Exception as save_error:
                logger.error(f"Could not save error request data: {save_error}")
                
            return jsonify({"status": "error", "error": str(e)})

# User management routes
@app.route('/users')
def users():
    """User management page"""
    from models import get_all_users
    users = get_all_users()
    return render_template('users.html', users=users)

@app.route('/add_user', methods=['POST'])
def add_user():
    """Add a new user"""
    try:
        from models import add_or_update_user_mapping
        
        user_id = int(request.form.get('user_id'))
        full_name = request.form.get('full_name')
        # Правильная обработка чекбокса is_admin
        is_admin = request.form.get('is_admin') == '1'
        
        logger.info(f"Attempting to add/update user: ID={user_id}, name={full_name}, is_admin={is_admin}")
        
        if add_or_update_user_mapping(user_id, full_name, is_admin):
            flash('Пользователь успешно добавлен!', 'success')
            logger.info(f"Successfully added/updated user with ID {user_id}")
        else:
            flash('Ошибка при добавлении пользователя.', 'danger')
            logger.error(f"Failed to add/update user with ID {user_id}")
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        flash(f'Ошибка при добавлении пользователя: {str(e)}', 'danger')
        
    return redirect(url_for('users'))

@app.route('/delete_user', methods=['POST'])
def delete_user():
    """Delete a user"""
    try:
        from models import delete_user
        
        user_id = int(request.form.get('user_id'))
        
        logger.info(f"Attempting to delete user with ID: {user_id}")
        
        if delete_user(user_id):
            flash('Пользователь успешно удален!', 'success')
            logger.info(f"Successfully deleted user with ID: {user_id}")
        else:
            flash('Ошибка при удалении пользователя.', 'danger')
            logger.error(f"Failed to delete user with ID: {user_id}")
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        flash(f'Ошибка при удалении пользователя: {str(e)}', 'danger')
        
    return redirect(url_for('users'))

@app.route('/set_admin_status', methods=['POST'])
def set_admin_status():
    """Set admin status for a user"""
    try:
        from models import set_user_admin_status
        
        user_id = int(request.form.get('user_id'))
        is_admin = request.form.get('is_admin') == '1'
        
        logger.info(f"Attempting to set admin status for user ID {user_id} to {is_admin}")
        
        if set_user_admin_status(user_id, is_admin):
            if is_admin:
                flash('Пользователю успешно присвоен статус администратора!', 'success')
                logger.info(f"Successfully set admin status to TRUE for user ID: {user_id}")
            else:
                flash('Статус администратора успешно снят!', 'success')
                logger.info(f"Successfully set admin status to FALSE for user ID: {user_id}")
        else:
            flash('Ошибка при изменении статуса администратора.', 'danger')
            logger.error(f"Failed to update admin status for user ID: {user_id}")
    except Exception as e:
        logger.error(f"Error setting admin status: {e}")
        flash(f'Ошибка при изменении статуса администратора: {str(e)}', 'danger')
        
    return redirect(url_for('users'))

@app.route('/reports')
def reports():
    """Reports page"""
    try:
        from models import get_all_users
        import os
        from datetime import datetime, timedelta
        
        # Получаем список всех пользователей
        users = get_all_users()
        
        # Получаем список всех файлов отчетов
        report_files = []
        map_files = []
        
        for file in os.listdir('.'):
            if file.startswith('report_') and file.endswith('.csv'):
                # Извлекаем user_id и дату из имени файла
                parts = file.replace('report_', '').replace('.csv', '').split('_')
                if len(parts) == 2:
                    user_id, date = parts
                    user_name = None
                    
                    # Находим имя пользователя
                    for user in users:
                        if str(user[0]) == user_id:
                            user_name = user[1]
                            break
                    
                    report_files.append({
                        'file_name': file,
                        'user_id': user_id,
                        'user_name': user_name or 'Неизвестный пользователь',
                        'date': date
                    })
            
            # Также ищем файлы карт
            elif file.startswith('map_') and file.endswith('.html'):
                map_files.append(file)
        
        # Сортируем отчеты по дате (новые вверху)
        report_files.sort(key=lambda x: x['date'], reverse=True)
        
        # Создаем список доступных дат за последние 30 дней (для выбора в форме)
        available_dates = []
        today = datetime.now()
        for i in range(30):
            date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            available_dates.append(date)
        
        return render_template('reports.html', 
                              report_files=report_files,
                              map_files=map_files,
                              users=users,
                              available_dates=available_dates)
    except Exception as e:
        logger.error(f"Error loading reports page: {e}")
        flash(f'Ошибка при загрузке страницы отчетов: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/generate_report', methods=['POST'])
def generate_report():
    """Generate a report for a specific user and date"""
    try:
        from utils import generate_csv_report, generate_map
        
        user_id = request.form.get('user_id')
        date = request.form.get('date')
        
        if not user_id or not date:
            flash('Необходимо указать ID пользователя и дату!', 'danger')
            return redirect(url_for('reports'))
        
        logger.info(f"Generating report for user {user_id} and date {date}")
        
        # Генерируем отчет
        report_file = generate_csv_report(user_id, date=date)
        
        # Генерируем карту
        map_file = generate_map(user_id, date=date)
        
        if report_file:
            flash(f'Отчет успешно создан: {report_file}', 'success')
            if map_file:
                flash(f'Карта маршрута создана: {map_file}', 'success')
            else:
                flash('Не удалось создать карту (недостаточно данных о местоположении)', 'warning')
        else:
            flash('Не удалось создать отчет', 'danger')
        
        return redirect(url_for('reports'))
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        flash(f'Ошибка при создании отчета: {str(e)}', 'danger')
        return redirect(url_for('reports'))

@app.route('/file/<path:filename>')
@app.route('/serve_file/<path:filename>')
def serve_file(filename):
    """Serve CSV, HTML reports and map files from root directory"""
    if (filename.startswith('report_') and (filename.endswith('.csv') or filename.endswith('.html'))) or \
       (filename.startswith('map_') and filename.endswith('.html')):
        return send_from_directory('.', filename)
    else:
        abort(404)

# Start bot if not already running
def ensure_bot_running():
    """Make sure the bot is running"""
    try:
        if os.path.exists(BOT_PID_FILE):
            with open(BOT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)  # Check if process exists
                logger.info(f"Bot is already running with PID {pid}")
                return
            except OSError:
                logger.info(f"Found dead bot PID {pid}, restarting")
        
        # No bot running, start it
        start_bot_in_background()
    except Exception as e:
        logger.error(f"Error ensuring bot is running: {e}")

if __name__ == "__main__":
    # Start bot in background
    threading.Thread(target=ensure_bot_running).start()
    
    # Run Flask server
    port = int(os.getenv("FLASK_RUN_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
