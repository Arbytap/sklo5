#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import sqlite3
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def add_location_points(user_id, session_id, segment_num, recreate=True):
    """
    Добавляет точные 5 точек для сегмента маршрута, с нужными временными отметками
    
    Args:
        user_id (int): ID пользователя
        session_id (str): ID сессии
        segment_num (int): Номер сегмента (1 или 2)
        recreate (bool): Если True, удаляет существующие точки и создает новые
    """
    try:
        # Подключение к базе данных
        conn = sqlite3.connect('tracker.db')
        cursor = conn.cursor()
        
        # Определяем временные рамки сегмента
        if segment_num == 1:
            # Первый сегмент (В офисе)
            start_time_str = "2025-05-08 08:00:00"
            end_time_str = "2025-05-08 08:20:00"
            start_coords = (55.758, 37.617)  # Начальная точка
            end_coords = (55.751, 37.618)    # Конечная точка
            status = "В офисе 🏢"            # Статус для этого сегмента
        else:
            # Второй сегмент (В движении)
            start_time_str = "2025-05-08 08:30:00"
            end_time_str = "2025-05-08 08:50:00"
            start_coords = (55.747, 37.621)   # Начальная точка
            end_coords = (55.745, 37.625)     # Конечная точка
            status = "Перерыв ☕"             # Статус для этого сегмента
        
        # Если нужно, удаляем существующие точки
        if recreate:
            if segment_num == 1:
                cursor.execute(
                    "DELETE FROM location_history WHERE user_id = ? AND timestamp BETWEEN ? AND ?",
                    (user_id, start_time_str, end_time_str)
                )
            else:
                cursor.execute(
                    "DELETE FROM location_history WHERE user_id = ? AND timestamp BETWEEN ? AND ?",
                    (user_id, start_time_str, end_time_str)
                )
            
            # Также удаляем статусы для чистоты эксперимента
            cursor.execute(
                "DELETE FROM status_history WHERE user_id = ? AND timestamp BETWEEN ? AND ?",
                (user_id, start_time_str, end_time_str)
            )
            
            # Добавляем статус для сегмента
            cursor.execute(
                "INSERT INTO status_history (user_id, status, timestamp) VALUES (?, ?, ?)",
                (user_id, status, start_time_str)
            )
        
        # Конвертируем временные значения
        start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
        
        # Вычисляем шаг для создания ровно 5 точек (включая начальную и конечную)
        time_step = (end_time - start_time) / 4  # 4 интервала для 5 точек
        
        # Координаты для промежуточных точек - создаем плавную линию
        # Добавляем начальную точку
        location_type = "start" if segment_num == 1 else "intermediate"
        cursor.execute(
            "INSERT INTO location_history (user_id, latitude, longitude, timestamp, session_id, location_type) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, start_coords[0], start_coords[1], start_time_str, session_id, location_type)
        )
        
        # Создаем промежуточные точки (3 штуки)
        points = []
        for i in range(1, 4):
            # Линейная интерполяция координат
            progress = i / 4.0  # от 0.25 до 0.75
            lat = start_coords[0] + (end_coords[0] - start_coords[0]) * progress
            lon = start_coords[1] + (end_coords[1] - start_coords[1]) * progress
            
            # Добавляем небольшое случайное отклонение для реалистичности
            import random
            lat_jitter = random.uniform(-0.0003, 0.0003)
            lon_jitter = random.uniform(-0.0003, 0.0003)
            lat += lat_jitter
            lon += lon_jitter
            
            # Вычисляем время для этой точки
            point_time = start_time + time_step * i
            point_time_str = point_time.strftime("%Y-%m-%d %H:%M:%S")
            
            points.append((
                user_id, 
                lat, 
                lon, 
                point_time_str, 
                session_id, 
                "intermediate"
            ))
        
        # Добавляем промежуточные точки
        cursor.executemany(
            "INSERT INTO location_history (user_id, latitude, longitude, timestamp, session_id, location_type) VALUES (?, ?, ?, ?, ?, ?)",
            points
        )
        
        # Добавляем конечную точку
        location_type = "end" if segment_num == 2 else "intermediate"
        cursor.execute(
            "INSERT INTO location_history (user_id, latitude, longitude, timestamp, session_id, location_type) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, end_coords[0], end_coords[1], end_time_str, session_id, location_type)
        )
        
        conn.commit()
        logger.info(f"Создано 5 точек для сегмента {segment_num} со статусом '{status}'")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка добавления точек: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def update_tooltips_for_markers():
    """
    Обновляет отображение времени и координат для всех точек, чтобы они всегда были видны в тултипах
    """
    try:
        # Проверяем, есть ли изменения в fixed_map_generator.py, которые нужно внести
        import fixed_map_generator
        file_path = 'fixed_map_generator.py'
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Проверяем, содержит ли файл маркер для обычных точек
        if "tooltip=f\"" in content:
            logger.info("Обновляем отображение в тултипах для всех типов точек")
            updated_content = content
            
            # Обновляем тултипы для обычных точек
            if "tooltip=f\"{time_str}\"," in content:
                updated_content = updated_content.replace(
                    "tooltip=f\"{time_str}\",", 
                    "tooltip=f\"⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}\","
                )
            elif "tooltip=f\"Время: {time_str}" in content:
                updated_content = updated_content.replace(
                    "tooltip=f\"Время: {time_str} | Статус: {current_status}\",", 
                    "tooltip=f\"⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}\","
                )
            
            # Обновляем тултипы для начала сегмента
            if "tooltip=f\"НАЧАЛО сегмента {i+1}\"" in content:
                updated_content = updated_content.replace(
                    "tooltip=f\"НАЧАЛО сегмента {i+1}\"", 
                    "tooltip=f\"🟢 НАЧАЛО сегмента {i+1} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}\""
                )
            elif "tooltip=f\"НАЧАЛО сегмента {i+1} | Статус:" in content:
                updated_content = updated_content.replace(
                    "tooltip=f\"НАЧАЛО сегмента {i+1} | Статус: {current_status}\"", 
                    "tooltip=f\"🟢 НАЧАЛО сегмента {i+1} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}\""
                )
            
            # Обновляем тултипы для конца сегмента
            if "tooltip=f\"КОНЕЦ сегмента {i+1}\"" in content:
                updated_content = updated_content.replace(
                    "tooltip=f\"КОНЕЦ сегмента {i+1}\"", 
                    "tooltip=f\"🔴 КОНЕЦ сегмента {i+1} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}\""
                )
            elif "tooltip=f\"КОНЕЦ сегмента {i+1} | Статус:" in content:
                updated_content = updated_content.replace(
                    "tooltip=f\"КОНЕЦ сегмента {i+1} | Статус: {current_status}\"", 
                    "tooltip=f\"🔴 КОНЕЦ сегмента {i+1} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}\""
                )
            
            # Обновляем тултипы для начала и конца всего маршрута
            if "tooltip=\"Начало маршрута\"," in content:
                updated_content = updated_content.replace(
                    "tooltip=\"Начало маршрута\",", 
                    "tooltip=f\"🟢 Начало маршрута | ⏱️ {first_event[3]} | 📍[{lat:.6f}, {lon:.6f}]\","
                )
            if "tooltip=\"Конец маршрута\"," in content:
                updated_content = updated_content.replace(
                    "tooltip=\"Конец маршрута\",", 
                    "tooltip=f\"🔴 Конец маршрута | ⏱️ {last_event[3]} | 📍[{lat:.6f}, {lon:.6f}]\","
                )
                
            with open(file_path, 'w') as f:
                f.write(updated_content)
            
            logger.info("Отображение времени и координат в тултипах обновлено")
            return True
        else:
            logger.info("Отображение тултипов уже настроено корректно")
            return False
    
    except Exception as e:
        logger.error(f"Ошибка при обновлении отображения тултипов: {e}")
        return False

def main():
    # ID тестового пользователя
    user_id = 999999
    session_id = "test_session_1"
    
    # Обновляем отображение времени для точек
    update_result = update_tooltips_for_markers()
    
    # Добавляем дополнительные точки для обоих сегментов
    seg1_result = add_location_points(user_id, session_id, 1)
    seg2_result = add_location_points(user_id, session_id, 2)
    
    if seg1_result and seg2_result:
        logger.info("Успешно добавлены дополнительные точки для обоих сегментов")
        # Генерируем обновленную карту
        from fixed_map_generator import create_direct_map
        map_file = create_direct_map(user_id, "2025-05-08")
        logger.info(f"Карта обновлена: {map_file}")
        print(f"✅ Карта успешно обновлена: {map_file}")
    else:
        logger.error("Произошла ошибка при добавлении точек")
        print("❌ Ошибка обновления точек")

if __name__ == "__main__":
    main()