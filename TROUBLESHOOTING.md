# Руководство по устранению неполадок Worker Tracker Bot

## Проблемы с запуском бота

### Бот не запускается

1. Проверьте файл .env:
   ```bash
   cat .env
   ```
   Убедитесь, что указан корректный TELEGRAM_TOKEN и настройки бота.

2. Проверьте режим работы бота:
   ```
   echo $BOT_MODE
   ```
   Должно быть `webhook` или `polling`.

3. Проверьте логи:
   ```bash
   cat bot_log.txt
   ```

### Ошибка "Unauthorized" при запуске бота

1. Проверьте токен бота:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getMe"
   ```
   Должен вернуть информацию о боте.

2. Перегенерируйте токен у @BotFather, если необходимо.

## Проблемы с Webhook

### Webhook не работает

1. Проверьте настройки webhook:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
   ```

2. Если webhook не установлен, установите его:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=<YOUR_WEBHOOK_URL>"
   ```

3. Проверьте доступность URL webhook'а:
   ```bash
   curl -I <YOUR_WEBHOOK_URL>
   ```
   Должен вернуть код 200.

4. Убедитесь, что сервер запущен:
   ```bash
   ps aux | grep python
   ```

### Конфликт с другим ботом на том же порту

1. Проверьте занятые порты:
   ```bash
   netstat -tulpn | grep python
   ```

2. Измените порт в файле .env и в скрипте запуска.

## Проблемы с базой данных

### Ошибки при работе с базой данных

1. Проверьте структуру базы данных:
   ```bash
   python -c "import sqlite3; conn = sqlite3.connect('tracker.db'); cursor = conn.cursor(); cursor.execute('SELECT name FROM sqlite_master WHERE type=\"table\"'); print(cursor.fetchall())"
   ```

2. Обновите структуру базы данных:
   ```bash
   python update_db_structure.py
   ```

### Сброс всех данных и начало с чистой базой

1. Остановите бота
2. Сделайте резервную копию текущей базы:
   ```bash
   cp tracker.db tracker.db.backup
   ```
3. Удалите базу данных:
   ```bash
   rm tracker.db
   ```
4. Запустите бота - новая база данных будет создана автоматически.

## Проблемы с генерацией карт

### Карты не генерируются или содержат ошибки

1. Убедитесь, что установлены необходимые библиотеки

2. Проверьте данные о местоположении:
   ```bash
   python -c "import sqlite3; conn = sqlite3.connect('tracker.db'); cursor = conn.cursor(); cursor.execute('SELECT * FROM location_history LIMIT 10'); print(cursor.fetchall())"
   ```

3. Проверьте временную зону:
   ```bash
   echo $TZ
   date
   ```
   Должно соответствовать настройкам в .env файле.

## Планировщик задач

### Ежедневные отчеты не отправляются

1. Проверьте работу планировщика задач:
   ```bash
   grep "scheduled" bot_log.txt
   ```

2. Проверьте настройки времени в scheduled_tasks.py

### Ошибка tzinfo в задачах планировщика

Если видите ошибку "float object has no attribute tzinfo":

1. Проверьте установленные версии pytz и python-dateutil

2. Убедитесь, что используете корректные объекты datetime с timezone в scheduled_tasks.py
