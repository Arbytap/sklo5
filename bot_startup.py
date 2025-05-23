#!/usr/bin/env python3
"""
Скрипт для автоматического запуска Telegram-бота.
Этот скрипт предназначен для запуска из .bashrc или аналогичного скрипта при старте Replit.
"""

import os
import logging
import signal
import subprocess
import sys
import time
from threading import Thread

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_startup.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def check_process(pid):
    """Проверяет, работает ли процесс с указанным PID."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def save_bot_pid(pid):
    """Сохраняет PID бота в файл."""
    with open('bot.pid', 'w') as f:
        f.write(str(pid))
    logger.info(f"Bot PID {pid} saved to file")

def get_saved_bot_pid():
    """Получает сохраненный PID бота из файла."""
    try:
        with open('bot.pid', 'r') as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None

def run_bot():
    """Запускает Telegram-бота в фоновом режиме."""
    # Удаляем webhook перед запуском
    try:
        subprocess.run(["curl", "-s", "-X", "POST", 
                      f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_TOKEN')}/deleteWebhook?drop_pending_updates=true"],
                      capture_output=True)
        logger.info("Webhook deleted successfully")
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")

    # Запускаем бота
    try:
        process = subprocess.Popen(["python", "standalone_polling_bot.py"], 
                                 stdout=subprocess.PIPE, 
                                 stderr=subprocess.PIPE)
        logger.info(f"Bot started with PID: {process.pid}")
        save_bot_pid(process.pid)
        return process.pid
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        return None

def check_and_restart_bot():
    """Проверяет работу бота и перезапускает его при необходимости."""
    pid = get_saved_bot_pid()
    
    if pid is None or not check_process(pid):
        logger.info("Bot is not running. Starting...")
        run_bot()
    else:
        logger.info(f"Bot is already running with PID {pid}")

def main():
    """Основная функция."""
    logger.info("Bot startup script started")
    check_and_restart_bot()

if __name__ == "__main__":
    main()