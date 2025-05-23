import os
import logging
import pytz
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
BOT_MODE = os.getenv("BOT_MODE", "polling")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "5001"))

# Admin configuration
ADMIN_ID = int(os.getenv("ADMIN_ID", "502488869"))  # Основной администратор
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # Список дополнительных администраторов

# Database configuration
DATABASE_FILE = "tracker.db"

# Location configuration
MAX_LOCATION_AGE_HOURS = 24

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Moscow timezone
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Установка серверного времени на московское для всех datetime.now()
import time
os.environ['TZ'] = 'Europe/Moscow'
try:
    time.tzset()
    logger.info("Установлен часовой пояс Москвы (Europe/Moscow)")
except AttributeError:
    logger.warning("Функция tzset() недоступна - вероятно, используется Windows")
except Exception as e:
    logger.error(f"Ошибка при установке часового пояса: {e}")

# Status options
STATUS_OPTIONS = {
    "office": "🏢 В офисе",
    "sick": "🏥 На больничном",
    "vacation": "🏖 В отпуске",
    "to_night": "🌃 В ночь",
    "from_night": "🌙 С ночи",
    "home": "🏠 Домой"
}

# Morning check configuration
MORNING_CHECK_START_TIME = (8, 30)  # 8:30 AM
MORNING_CHECK_END_TIME = (10, 0)    # 10:00 AM

# Daily report configuration
DAILY_REPORT_TIME = (17, 30)  # 17:30 PM
