#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Скрипт для переключения режимов работы бота (webhook/polling)
и правильной настройки webhook URL с учетом порта.
"""

import os
import sys
import logging
import time
import argparse
import requests
from dotenv import load_dotenv
import telegram

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("mode_switcher")

def load_config():
    """Загрузка конфигурации из .env файла"""
    load_dotenv()
    
    token = os.getenv("TELEGRAM_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")
    webhook_port = os.getenv("PORT", "5003")
    
    if not token:
        logger.error("Не найден TELEGRAM_TOKEN в .env файле")
        sys.exit(1)
    
    if not webhook_url:
        logger.warning("Не найден WEBHOOK_URL в .env файле")
    
    return {
        "token": token,
        "webhook_url": webhook_url,
        "webhook_port": int(webhook_port)
    }

def update_env_file(mode):
    """Обновление режима работы в .env файле"""
    try:
        with open(".env", "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        updated = False
        for i, line in enumerate(lines):
            if line.startswith("BOT_MODE="):
                lines[i] = f"BOT_MODE={mode}\n"
                updated = True
                break
        
        if not updated:
            lines.append(f"BOT_MODE={mode}\n")
        
        with open(".env", "w", encoding="utf-8") as f:
            f.writelines(lines)
            
        logger.info(f"Режим работы в .env изменен на {mode}")
        return True
    except Exception as e:
        logger.error(f"Не удалось обновить .env файл: {e}")
        return False

def set_webhook(token, webhook_url, port):
    """Установка webhook URL в настройках Telegram API"""
    if not webhook_url:
        logger.error("WEBHOOK_URL не указан. Не удалось установить webhook.")
        return False
    
    # Формируем полный URL с путем /webhook и портом
    if port != 443 and port != 80 and port != 5000:
        full_url = f"{webhook_url}:{port}/webhook"
    else:
        full_url = f"{webhook_url}/webhook"
    
    # Проверяем, что URL не содержит двойных слешей
    full_url = full_url.replace("://", "|||").replace("//", "/").replace("|||", "://")
    
    logger.info(f"Устанавливаем webhook URL: {full_url}")
    
    try:
        bot = telegram.Bot(token)
        
        # Удаляем старый webhook для избежания конфликтов
        bot.delete_webhook(drop_pending_updates=True)
        logger.info("Старый webhook удален")
        
        # Даем Telegram API время на обработку удаления webhook
        time.sleep(3)
        
        # Устанавливаем новый webhook
        result = bot.set_webhook(url=full_url)
        
        if result:
            logger.info(f"Webhook успешно установлен на {full_url}")
            
            # Проверяем установку webhook
            webhook_info = bot.get_webhook_info()
            logger.info(f"Информация о webhook: URL={webhook_info.url}, pending_updates={webhook_info.pending_update_count}")
            
            return True
        else:
            logger.error("Не удалось установить webhook")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при установке webhook: {e}")
        return False

def delete_webhook(token):
    """Удаление webhook в настройках Telegram API"""
    try:
        bot = telegram.Bot(token)
        webhook_info = bot.get_webhook_info()
        
        if webhook_info.url:
            logger.info(f"Обнаружен webhook: {webhook_info.url}, удаляем")
            result = bot.delete_webhook(drop_pending_updates=True)
            
            if result:
                logger.info("Webhook успешно удален")
                
                # Даем Telegram API время на обработку удаления webhook
                time.sleep(3)
                
                # Проверяем, что webhook действительно удален
                webhook_info = bot.get_webhook_info()
                if webhook_info.url:
                    logger.warning(f"Webhook все еще активен: {webhook_info.url}")
                    logger.info("Повторная попытка удаления webhook")
                    bot.delete_webhook(drop_pending_updates=True)
                    time.sleep(3)
                    
                    webhook_info = bot.get_webhook_info()
                    if webhook_info.url:
                        logger.error(f"Не удалось удалить webhook: {webhook_info.url}")
                        return False
                
                return True
            else:
                logger.error("Не удалось удалить webhook")
                return False
        else:
            logger.info("Webhook не настроен")
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при удалении webhook: {e}")
        return False

def check_cloudflare_url(webhook_url):
    """Проверка доступности Cloudflare URL"""
    if not webhook_url:
        return False
        
    try:
        response = requests.get(webhook_url, timeout=10)
        if response.status_code < 400:
            logger.info(f"URL {webhook_url} доступен, статус: {response.status_code}")
            return True
        else:
            logger.warning(f"URL {webhook_url} вернул статус: {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Не удалось подключиться к {webhook_url}: {e}")
        return False

def switch_to_webhook(config):
    """Переключение на режим webhook"""
    logger.info("Переключение на режим webhook")
    
    # Проверяем наличие URL
    if not config["webhook_url"]:
        logger.error("WEBHOOK_URL не указан в .env файле. Не удалось переключиться на webhook режим.")
        return False
    
    # Проверяем доступность URL
    if not check_cloudflare_url(config["webhook_url"]):
        logger.warning("WEBHOOK_URL недоступен или возвращает ошибку")
        choice = input("URL недоступен. Все равно продолжить? (y/n): ")
        if choice.lower() != 'y':
            logger.info("Операция отменена")
            return False
    
    # Обновляем .env файл
    if not update_env_file("webhook"):
        return False
    
    # Устанавливаем webhook
    if not set_webhook(config["token"], config["webhook_url"], config["webhook_port"]):
        logger.error("Не удалось установить webhook. Режим в .env изменен, но webhook не настроен.")
        return False
    
    logger.info(f"Бот успешно переключен в режим webhook на URL: {config['webhook_url']}:{config['webhook_port']}/webhook")
    logger.info("Запустите 'python run_webhook_on_windows.py' для запуска сервера")
    return True

def switch_to_polling(config):
    """Переключение на режим polling"""
    logger.info("Переключение на режим polling")
    
    # Удаляем webhook
    if not delete_webhook(config["token"]):
        logger.warning("Не удалось полностью удалить webhook. Возможны проблемы при запуске в режиме polling.")
    
    # Обновляем .env файл
    if not update_env_file("polling"):
        return False
    
    logger.info("Бот успешно переключен в режим polling")
    logger.info("Запустите 'python standalone_polling_bot.py' для запуска бота")
    return True

def main():
    """Основная функция"""
    parser = argparse.ArgumentParser(description="Переключение режимов работы Telegram бота")
    parser.add_argument("mode", choices=["webhook", "polling"], help="Режим работы бота")
    
    args = parser.parse_args()
    
    # Загружаем конфигурацию
    config = load_config()
    
    if args.mode == "webhook":
        switch_to_webhook(config)
    else:
        switch_to_polling(config)

if __name__ == "__main__":
    main()