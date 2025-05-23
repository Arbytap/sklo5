#!/bin/bash
# Скрипт для запуска Telegram-бота в режиме webhook

# Запускаем webhook сервер
echo "Запуск Telegram-бота в режиме webhook..."
exec python webhook_server.py