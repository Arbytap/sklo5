#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Скрипт для запуска Telegram-бота для Replit Workflow.
Этот скрипт можно добавить в workflow и запускать автоматически.
"""

import os
import sys
import logging
import subprocess
import signal
import time

# Настройка логирования
log_file = "bot_launcher.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bot_launcher")

def kill_existing_bot():
    """Остановка ранее запущенного бота"""
    pid_file = "bot.pid"
    
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Остановлен существующий процесс бота с PID {pid}")
                time.sleep(2)  # Даем время на завершение
            except OSError:
                logger.info(f"Процесс с PID {pid} не найден")
        except Exception as e:
            logger.error(f"Ошибка при попытке остановить бота: {e}")
    
    # Удаляем PID файл
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except Exception as e:
            logger.error(f"Ошибка при удалении PID файла: {e}")

def main():
    """Основная функция запуска бота"""
    try:
        # Остановка существующего процесса бота
        kill_existing_bot()
        
        # Запуск бота
        logger.info("Запуск Telegram-бота...")
        bot_process = subprocess.Popen(["python", "standalone_polling_bot.py"])
        
        # Сохранение PID
        with open("bot.pid", "w") as f:
            f.write(str(bot_process.pid))
        
        logger.info(f"Telegram-бот запущен с PID: {bot_process.pid}")
        
        # Ожидание завершения процесса
        bot_process.wait()
        
        exit_code = bot_process.returncode
        logger.info(f"Бот завершил работу с кодом: {exit_code}")
        return exit_code
    
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания, завершение работы")
        return 0
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())