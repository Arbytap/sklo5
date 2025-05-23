#!/bin/bash
# Скрипт для запуска Telegram-бота в режиме polling

# Удаляем webhook перед запуском
TOKEN=$(grep -o 'TELEGRAM_TOKEN=[^[:space:]]*' .env | cut -d '=' -f2)
curl -s -X POST "https://api.telegram.org/bot$TOKEN/deleteWebhook?drop_pending_updates=true"

# Запускаем бота
echo "Запуск Telegram-бота..."
exec python standalone_polling_bot.py