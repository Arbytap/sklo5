# Скрипты запуска Worker Tracker Bot

Этот документ описывает различные скрипты, используемые для запуска и управления ботом.

## Скрипты для запуска бота

### run_bot.sh
Запускает бота в режиме, указанном в файле `.env`
```bash
#!/bin/bash
source .env
if [ "$BOT_MODE" == "webhook" ]; then
  python run_webhook_port_5003.py
else
  python standalone_polling_bot.py
fi
```

### start_bot.sh
Запускает бота в фоновом режиме и сохраняет его PID для дальнейшего управления
```bash
#!/bin/bash
# Остановка старого процесса бота, если он запущен
if [ -f bot.pid ]; then
    old_pid=$(cat bot.pid)
    if ps -p $old_pid > /dev/null; then
        echo "Stopping old bot process (PID: $old_pid)"
        kill $old_pid
        sleep 2
    fi
    rm bot.pid
fi

# Запуск бота в фоновом режиме
echo "Starting bot in background..."
nohup python bot_startup.py > bot_log.txt 2>&1 &
echo $! > bot.pid

echo "Bot started with PID: $(cat bot.pid)"
```

### run_webhook.sh
Запускает бота в режиме webhook на порту 5003
```bash
#!/bin/bash
python run_webhook_port_5003.py
```

## Скрипты для управления ботом

### bot_launcher.py
Скрипт для запуска бота в workflow:
- Проверяет существующий процесс
- Останавливает старый процесс
- Запускает новый процесс бота

### bot_startup.py
Скрипт для автоматического запуска и контроля бота:
- Сохраняет PID процесса
- Проверяет статус работы
- Перезапускает бот при необходимости

## Рекомендации по запуску

1. Для разработки и тестирования:
   ```
   python standalone_polling_bot.py
   ```

2. Для продакшена с webhook:
   ```
   python run_webhook_port_5003.py
   ```

3. Для автоматического перезапуска:
   ```
   ./start_bot.sh
   ```

4. Для запуска в контейнере или через systemd:
   ```
   ./run_bot.sh
   ```
