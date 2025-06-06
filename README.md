# Worker Tracker Bot

Система отслеживания местоположения и статусов сотрудников через Telegram-бот

## Основные функции

- Отслеживание статусов сотрудников (В офисе, Домой, Болею, и т.д.)
- Отслеживание местоположения сотрудников через Telegram
- Генерация карт маршрутов сотрудников
- Формирование ежедневных отчетов
- Управление заявками на отгулы
- Автоматические уведомления о статусах сотрудников

## Режимы работы

- Webhook - для продакшена
- Polling - для разработки и тестирования

## Установка и запуск

1. Настройте переменные окружения в файле `.env`
2. Запустите веб-сервер Flask: `gunicorn --bind 0.0.0.0:5000 main:app`
3. Для запуска бота в режиме polling: `python standalone_polling_bot.py`
4. Для запуска в режиме webhook: `python run_webhook_port_5003.py`

## Файловая структура

- `main.py` - основной файл Flask-приложения
- `bot.py` - основной файл бота и его обработчиков
- `models.py` - модели данных и функции работы с БД
- `database.py` - инициализация БД и основные функции работы с данными
- `fixed_map_generator.py` - генерация карт маршрутов сотрудников
- `scheduled_tasks.py` - задачи, выполняемые по расписанию
- `timeoff_requests.py` - система запросов на отгулы
- `utils.py` - вспомогательные функции
- `config.py` - конфигурация приложения
- `standalone_polling_bot.py` - запуск бота в режиме polling
- `run_webhook_port_5003.py` - запуск webhook на порту 5003

## Настройка переменных окружения

Создайте файл `.env` со следующими переменными:

```
TELEGRAM_TOKEN=ваш_токен_бота
BOT_MODE=webhook или polling
WEBHOOK_URL=https://ваш_домен
PORT=5003 (для webhook)
ADMIN_IDS=id1,id2,id3
TZ=Europe/Moscow
```
