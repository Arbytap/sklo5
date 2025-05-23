#!/usr/bin/env python3
"""
Скрипт для создания реалистичных тестовых данных маршрута сотрудника
с корректным разделением на старт, промежуточные и конечные точки.
"""
import os
import sys
import logging
import random
import sqlite3
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Подключение к БД
DATABASE_FILE = 'tracker.db'

def get_user_name(user_id):
    """Получить имя пользователя по ID"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT full_name FROM user_mapping WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result[0]
        return f"Пользователь {user_id}"
    except Exception as e:
        logger.error(f"Ошибка при получении имени пользователя: {e}")
        return f"Пользователь {user_id}"

def create_path_between_points(start_point, end_point, num_points=3):
    """Создает промежуточные точки между двумя координатами"""
    points = []
    start_lat, start_lon = start_point
    end_lat, end_lon = end_point
    
    for i in range(num_points):
        # Линейная интерполяция между точками
        factor = (i + 1) / (num_points + 1)
        lat = start_lat + (end_lat - start_lat) * factor
        lon = start_lon + (end_lon - start_lon) * factor
        
        # Добавляем небольшое случайное отклонение для реалистичности (до 50 метров)
        lat_deviation = random.uniform(-0.0003, 0.0003)
        lon_deviation = random.uniform(-0.0003, 0.0003)
        
        points.append((lat + lat_deviation, lon + lon_deviation))
    
    return points

def add_location_with_timestamp(user_id, latitude, longitude, timestamp, session_id, location_type):
    """Добавляет местоположение с указанным временем"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Преобразуем timestamp в строку, если это объект datetime
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = timestamp
            
        cursor.execute(
            'INSERT INTO location_history (user_id, latitude, longitude, timestamp, session_id, location_type) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, latitude, longitude, timestamp_str, session_id, location_type)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении местоположения: {e}")
        return False

def add_status_with_timestamp(user_id, status, timestamp):
    """Добавляет статус с указанным временем"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Преобразуем timestamp в строку, если это объект datetime
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = timestamp
            
        cursor.execute(
            'INSERT INTO status_history (user_id, status, timestamp) VALUES (?, ?, ?)',
            (user_id, status, timestamp_str)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении статуса: {e}")
        return False

def create_route_segment(user_id, start_point, end_point, start_time, session_id, 
                         start_type="intermediate", end_type="intermediate", points_between=3):
    """Создает сегмент маршрута между двумя точками"""
    # Добавляем начальную точку сегмента
    start_lat, start_lon = start_point
    add_location_with_timestamp(user_id, start_lat, start_lon, start_time, session_id, start_type)
    current_time = start_time
    
    # Создаем промежуточные точки
    if points_between > 0:
        intermediate_points = create_path_between_points(start_point, end_point, points_between)
        
        for lat, lon in intermediate_points:
            # Увеличиваем время на случайный интервал (5-15 минут)
            current_time += timedelta(minutes=random.randint(5, 15))
            add_location_with_timestamp(user_id, lat, lon, current_time, session_id, "intermediate")
            logger.info(f"Добавлена промежуточная точка: ({lat:.6f}, {lon:.6f}) в {current_time}")
    
    # Добавляем конечную точку сегмента
    current_time += timedelta(minutes=random.randint(5, 15))
    end_lat, end_lon = end_point
    add_location_with_timestamp(user_id, end_lat, end_lon, current_time, session_id, end_type)
    
    return current_time

def create_test_route(user_id):
    """Создает тестовый маршрут для пользователя"""
    user_name = get_user_name(user_id)
    logger.info(f"Создание тестового маршрута для {user_name} (ID: {user_id})")
    
    # Текущая дата/время минус 6 часов для начала
    now = datetime.now()
    start_time = now - timedelta(hours=6)
    
    # Создаем уникальный ID сессии
    session_id = f"test_session_{now.strftime('%Y%m%d_%H%M%S')}"
    
    # Определяем ключевые точки маршрута (координаты и название)
    route_points = [
        ((55.752, 37.617), "Дом"), 
        ((55.754, 37.620), "Метро"),
        ((55.758, 37.617), "Работа"), 
        ((55.756, 37.615), "Обед"),
        ((55.758, 37.617), "Работа"), 
        ((55.754, 37.620), "Метро"),
        ((55.752, 37.617), "Дом")
    ]
    
    # Определяем статусы и время их изменения
    statuses = [
        ("home", start_time),
        ("office", start_time + timedelta(hours=2)),
        ("home", start_time + timedelta(hours=5))
    ]
    
    # Добавляем статусы
    for status, timestamp in statuses:
        add_status_with_timestamp(user_id, status, timestamp)
        logger.info(f"Добавлен статус: {status} в {timestamp}")
    
    # Создаем первый сегмент: Дом -> Метро (начальная точка маршрута)
    current_time = start_time
    current_time = create_route_segment(
        user_id, 
        route_points[0][0], 
        route_points[1][0], 
        current_time, 
        session_id,
        start_type="start",  # Первая точка - начальная
        end_type="intermediate"
    )
    logger.info(f"Добавлен сегмент: {route_points[0][1]} -> {route_points[1][1]}")
    
    # Метро -> Работа
    current_time = create_route_segment(
        user_id, 
        route_points[1][0], 
        route_points[2][0], 
        current_time + timedelta(minutes=random.randint(5, 15)), 
        session_id
    )
    logger.info(f"Добавлен сегмент: {route_points[1][1]} -> {route_points[2][1]}")
    
    # Работа -> Обед
    current_time = create_route_segment(
        user_id, 
        route_points[2][0], 
        route_points[3][0], 
        current_time + timedelta(hours=random.randint(2, 3)), 
        session_id
    )
    logger.info(f"Добавлен сегмент: {route_points[2][1]} -> {route_points[3][1]}")
    
    # Обед -> Работа
    current_time = create_route_segment(
        user_id, 
        route_points[3][0], 
        route_points[4][0], 
        current_time + timedelta(minutes=random.randint(30, 60)), 
        session_id
    )
    logger.info(f"Добавлен сегмент: {route_points[3][1]} -> {route_points[4][1]}")
    
    # Работа -> Метро
    current_time = create_route_segment(
        user_id, 
        route_points[4][0], 
        route_points[5][0], 
        current_time + timedelta(hours=random.randint(3, 4)), 
        session_id
    )
    logger.info(f"Добавлен сегмент: {route_points[4][1]} -> {route_points[5][1]}")
    
    # Метро -> Дом (конечная точка маршрута)
    current_time = create_route_segment(
        user_id, 
        route_points[5][0], 
        route_points[6][0], 
        current_time + timedelta(minutes=random.randint(5, 15)), 
        session_id,
        start_type="intermediate",
        end_type="end"  # Последняя точка - конечная
    )
    logger.info(f"Добавлен сегмент: {route_points[5][1]} -> {route_points[6][1]}")
    
    return session_id

def main():
    """Основная функция"""
    if len(sys.argv) > 1:
        try:
            user_id = int(sys.argv[1])
            session_id = create_test_route(user_id)
            logger.info(f"Тестовый маршрут создан успешно. ID сессии: {session_id}")
        except ValueError:
            logger.error(f"Неверный ID пользователя: {sys.argv[1]}")
    else:
        logger.error("Не указан ID пользователя. Пример использования: python create_test_route.py 502488869")

if __name__ == "__main__":
    main()