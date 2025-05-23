"""
Скрипт для очистки геоданных и статусов определенного пользователя.
"""
import sqlite3
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Путь к файлу базы данных
DATABASE_FILE = "tracker.db"

def clean_user_location_data(user_id):
    """Очистить данные о местоположении пользователя"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Получаем количество записей о местоположении перед удалением
    cursor.execute(
        'SELECT COUNT(*) FROM location_history WHERE user_id = ?', 
        (user_id,)
    )
    count_before = cursor.fetchone()[0]
    
    # Удаляем записи о местоположении
    cursor.execute(
        'DELETE FROM location_history WHERE user_id = ?', 
        (user_id,)
    )
    
    # Фиксируем изменения
    conn.commit()
    logger.info(f"Удалено {count_before} записей о местоположении пользователя {user_id}")
    
    conn.close()
    return count_before

def clean_user_status_data(user_id):
    """Очистить данные о статусах пользователя"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Получаем количество записей о статусах перед удалением
    cursor.execute(
        'SELECT COUNT(*) FROM status_history WHERE user_id = ?', 
        (user_id,)
    )
    count_before = cursor.fetchone()[0]
    
    # Удаляем записи о статусах
    cursor.execute(
        'DELETE FROM status_history WHERE user_id = ?', 
        (user_id,)
    )
    
    # Фиксируем изменения
    conn.commit()
    logger.info(f"Удалено {count_before} записей о статусах пользователя {user_id}")
    
    conn.close()
    return count_before

def get_user_name(user_id):
    """Получить имя пользователя по его ID"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        'SELECT full_name FROM user_mapping WHERE user_id = ?', 
        (user_id,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0]
    return f"User {user_id}"

def main():
    """Основная функция для очистки данных пользователя"""
    # ID пользователя Копытина Андрея Владимировича
    user_id = 502488869
    user_name = get_user_name(user_id)
    
    logger.info(f"Начало очистки данных пользователя {user_name} (ID: {user_id})")
    
    # Очистка данных о местоположении
    locations_deleted = clean_user_location_data(user_id)
    
    # Очистка данных о статусах
    statuses_deleted = clean_user_status_data(user_id)
    
    logger.info(f"Очистка данных пользователя {user_name} завершена")
    logger.info(f"Итого удалено: {locations_deleted} записей о местоположении, {statuses_deleted} записей о статусах")

if __name__ == "__main__":
    main()