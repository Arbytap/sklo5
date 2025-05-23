"""
Скрипт для обновления структуры базы данных.
Выполняет альтерации таблиц при необходимости.
"""
import sqlite3
import logging
from config import DATABASE_FILE

logger = logging.getLogger(__name__)

def update_db_structure():
    """Обновляет структуру базы данных, добавляя недостающие столбцы"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Проверка и добавление поля is_admin в таблицу user_mapping
    try:
        # Проверяем, существует ли уже поле is_admin
        cursor.execute("PRAGMA table_info(user_mapping)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'is_admin' not in columns:
            logger.info("Добавление поля is_admin в таблицу user_mapping")
            cursor.execute("ALTER TABLE user_mapping ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            conn.commit()
            logger.info("Поле is_admin успешно добавлено")
        else:
            logger.info("Поле is_admin уже существует в таблице user_mapping")
        
        # Проверяем необходимость других обновлений структуры
        # Например, проверка существования таблиц или других полей
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении структуры БД: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    # Настройка логирования, если скрипт запускается напрямую
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    update_db_structure()