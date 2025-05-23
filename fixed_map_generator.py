#!/usr/bin/env python3
"""
Улучшенный скрипт для создания карты с гарантированной работой
Добавлена поддержка создания карт даже при отсутствии точек маршрута
"""
import os
import sys
import logging
import folium
from datetime import datetime
import sqlite3

# Настройка логирования
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# База данных
DATABASE_FILE = 'tracker.db'

def get_user_name_by_id(user_id):
    """Получить имя пользователя по ID"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT full_name FROM user_mapping WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0]
    return f"User_{user_id}"

def get_status_history_from_db(user_id, date):
    """Получаем историю изменения статусов пользователя за указанную дату"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Получение всех статусов для пользователя в указанную дату
    if date:
        start_datetime = f"{date} 00:00:00"
        end_datetime = f"{date} 23:59:59"
        cursor.execute('''
            SELECT id, user_id, status, timestamp
            FROM status_history
            WHERE user_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        ''', (user_id, start_datetime, end_datetime))
    else:
        # Если дата не указана, возвращаем за сегодня
        today = datetime.now().strftime("%Y-%m-%d")
        start_datetime = f"{today} 00:00:00"
        end_datetime = f"{today} 23:59:59"
        cursor.execute('''
            SELECT id, user_id, status, timestamp
            FROM status_history
            WHERE user_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        ''', (user_id, start_datetime, end_datetime))
    
    status_history = cursor.fetchall()
    conn.close()
    logger.info(f"Извлечено {len(status_history)} записей о статусах для пользователя {user_id} за {date or 'сегодня'}")
    return status_history

def get_locations_from_db(user_id, date):
    """Напрямую получаем координаты из базы данных"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Получение всех точек для пользователя в указанную дату
    if date:
        start_datetime = f"{date} 00:00:00"
        end_datetime = f"{date} 23:59:59"
        cursor.execute('''
            SELECT latitude, longitude, timestamp, session_id, location_type
            FROM location_history
            WHERE user_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        ''', (user_id, start_datetime, end_datetime))
    else:
        # Если дата не указана, возвращаем за сегодня
        today = datetime.now().strftime("%Y-%m-%d")
        start_datetime = f"{today} 00:00:00"
        end_datetime = f"{today} 23:59:59"
        cursor.execute('''
            SELECT latitude, longitude, timestamp, session_id, location_type
            FROM location_history
            WHERE user_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        ''', (user_id, start_datetime, end_datetime))
    
    all_locations = cursor.fetchall()
    conn.close()
    logger.info(f"Извлечено {len(all_locations)} записей о местоположении для пользователя {user_id} за {date or 'сегодня'}")
    
    # Фильтруем только корректные записи, где координаты - числа
    valid_locations = []
    for loc in all_locations:
        try:
            # Преобразуем строки в числа, если координаты указаны как строки
            lat = float(loc[0])
            lon = float(loc[1])
            time_str = loc[2]
            session_id = loc[3] if len(loc) > 3 else "unknown_session"
            loc_type = loc[4] if len(loc) > 4 else "intermediate"
            
            # Добавляем только координаты с корректными значениями
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                valid_locations.append((lat, lon, time_str, session_id, loc_type))
            else:
                logger.warning(f"Координаты вне допустимых пределов: {lat}, {lon}")
        except (ValueError, TypeError) as e:
            logger.warning(f"Пропущена запись с некорректными координатами: {loc}, ошибка: {e}")
    
    logger.info(f"После обработки получено {len(valid_locations)} корректных записей")
    return valid_locations

def create_direct_map(user_id, date=None):
    """
    Создает карту напрямую из базы данных, минуя стандартные функции
    Даже при отсутствии данных о местоположении, создает базовую карту с информацией о статусах
    
    Args:
        user_id: ID пользователя
        date: Дата в формате 'YYYY-MM-DD', если None - сегодняшняя дата
        
    Returns:
        Имя файла карты или None если совсем нет данных
    """
    # Получаем имя пользователя
    user_name = get_user_name_by_id(user_id)
    # Убираем некорректные символы из имени файла
    safe_user_name = user_name.replace(' ', '_')
    
    logger.info(f"Создание карты для {user_name} (ID: {user_id}) за {date or 'сегодня'}")
    
    # Получаем данные о местоположении
    valid_locations = get_locations_from_db(user_id, date)
    
    # Получаем историю статусов
    status_history = get_status_history_from_db(user_id, date)
    
    # Проверяем, есть ли хоть какие-то данные
    if not valid_locations and not status_history:
        logger.warning(f"Нет ни координат, ни статусов для {user_name}")
        
        # Создаем пустую карту с информационным сообщением
        m = folium.Map(
            location=[55.7558, 37.6173],  # Москва по умолчанию
            zoom_start=10,
            tiles="OpenStreetMap"
        )
        
        # Добавляем информационный маркер
        folium.Marker(
            [55.7558, 37.6173],
            popup="<b>Нет данных о местоположении</b><br>Пользователь не передавал своё местоположение в указанную дату.",
            tooltip="Нет данных",
            icon=folium.Icon(color='gray', icon='info-sign')
        ).add_to(m)
        
        # Добавляем информационную надпись на карту
        title_html = '''
             <h3 align="center" style="font-size:16px"><b>Отчёт о местоположении: {}</b></h3>
             <h4 align="center" style="font-size:14px">Дата: {}</h4>
             <h4 align="center" style="font-size:14px"><b>Нет данных о местоположении за указанную дату</b></h4>
             <p align="center">Чтобы получить данные о местоположении, пользователь должен нажать кнопку "В офисе" или другую кнопку статуса в боте.</p>
        '''.format(user_name, date or datetime.now().strftime("%Y-%m-%d"))
        
        m.get_root().html.add_child(folium.Element(title_html))
        
        # Сохраняем карту
        map_filename = f"map_{safe_user_name}_{date or datetime.now().strftime('%Y-%m-%d')}.html"
        m.save(map_filename)
        logger.info(f"Создана пустая карта: {map_filename}")
        return map_filename
    
    # Если есть хотя бы координаты, создаем карту с маршрутом
    if valid_locations:
        # Вычисляем центр карты как среднее значение координат
        lat_sum = sum(loc[0] for loc in valid_locations)
        lon_sum = sum(loc[1] for loc in valid_locations)
        center_lat = lat_sum / len(valid_locations)
        center_lon = lon_sum / len(valid_locations)
    else:
        # Если нет координат, но есть статусы - используем Москву как центр
        center_lat = 55.7558
        center_lon = 37.6173
    
    # Создаем карту
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=14,
        tiles="OpenStreetMap"
    )
    
    # Добавляем заголовок карты
    title_html = '''
         <h3 align="center" style="font-size:16px"><b>Отчёт о местоположении: {}</b></h3>
         <h4 align="center" style="font-size:14px">Дата: {}</h4>
         <h4 align="center" style="font-size:14px">Статусы: {}</h4>
         <p align="center" style="font-size:12px; color:#666;"><i>Время указано в московском часовом поясе (UTC+3)</i></p>
    '''.format(
        user_name, 
        date or datetime.now().strftime("%Y-%m-%d"),
        ", ".join([status[2] for status in status_history]) if status_history else "Нет данных о статусах"
    )
    
    m.get_root().html.add_child(folium.Element(title_html))
    
    # Если нет координат, но есть статусы - создаем только информационную карту
    if not valid_locations and status_history:
        # Добавляем информационный маркер
        folium.Marker(
            [center_lat, center_lon],
            popup=f"<b>Статусы пользователя:</b><br>" + "<br>".join([f"{s[3]}: {s[2]}" for s in status_history]),
            tooltip="Статусы пользователя",
            icon=folium.Icon(color='blue', icon='info-sign')
        ).add_to(m)
        
        # Сохраняем карту
        map_filename = f"map_{safe_user_name}_{date or datetime.now().strftime('%Y-%m-%d')}.html"
        m.save(map_filename)
        logger.info(f"Создана карта со статусами без координат: {map_filename}")
        return map_filename
    
    # Преобразуем историю статусов в список для хронологического анализа
    status_events = []
    for status_entry in status_history:
        status_id, u_id, status, status_timestamp = status_entry
        status_time = status_timestamp
        if isinstance(status_timestamp, str):
            status_time = status_timestamp[:19]  # Убираем миллисекунды если есть
        status_events.append((status_time, status))
    
    # Сортируем статусы по времени
    status_events.sort(key=lambda x: x[0])
    
    logger.info(f"Найдено {len(status_events)} записей о смене статуса")
    
    # Сортируем точки по времени для правильного построения маршрута
    valid_locations.sort(key=lambda x: x[2])
    
    # Преобразуем все точки маршрута в единый формат с временной меткой
    location_events = []
    for loc in valid_locations:
        lat, lon = loc[0], loc[1]
        timestamp = loc[2]
        # Проверим, что координаты корректны и не строки
        if isinstance(lat, str) or isinstance(lon, str):
            try:
                lat = float(lat)
                lon = float(lon)
            except (ValueError, TypeError):
                logger.warning(f"Пропускаем точку с неверными координатами: {lat}, {lon}")
                continue
        
        loc_type = loc[4] if len(loc) > 4 else 'intermediate'
        time_key = timestamp
        if isinstance(timestamp, str):
            time_key = timestamp[:19]  # Используем только первые 19 символов

        location_events.append((time_key, lat, lon, loc_type, timestamp))
    
    # Сортируем все точки местоположения по времени
    location_events.sort(key=lambda x: x[0])
    
    # Объединяем статусы и местоположения в один временной ряд
    all_events = []
    for time_key, status in status_events:
        all_events.append(("status", time_key, status))
    
    for time_key, lat, lon, loc_type, timestamp in location_events:
        all_events.append(("location", time_key, lat, lon, loc_type, timestamp))
    
    # Функция для безопасного сравнения временных меток разных типов
    def safe_sort_key(event):
        time_key = event[1]
        if isinstance(time_key, str):
            try:
                # Пробуем преобразовать строку в объект datetime
                return datetime.strptime(time_key[:19], '%Y-%m-%d %H:%M:%S')
            except:
                # Если не удалось, используем строку
                return time_key
        return time_key  # Если time_key уже datetime
    
    # Сортируем все события по времени
    all_events.sort(key=safe_sort_key)
    
    # Переменная для хранения сегментов маршрута
    path_segments = []
    current_segment = []
    current_status = "Неизвестно"  # Начальный статус пользователя
    
    # Проходим по всем событиям в хронологическом порядке
    for event in all_events:
        if event[0] == "status":
            # Это событие смены статуса
            event_type, time_key, status = event
            
            # Если уже начали сегмент, сохраняем его и начинаем новый
            if current_segment:
                path_segments.append(current_segment)
                current_segment = []
            
            # Обновляем текущий статус
            current_status = status
            logger.debug(f"Изменение статуса на {status} в {time_key}")
            
            # Добавляем маркер изменения статуса, если есть координаты
            if location_events:
                try:
                    # Найдем ближайшую точку местоположения к моменту смены статуса
                    # Используем простой алгоритм - берем первую точку, которая ближе всего
                    # по времени (строковое сравнение)
                    status_time_str = str(time_key)[:19]  # Берем только первые 19 символов
                    
                    # Сортируем точки по близости ко времени статуса
                    sorted_events = sorted(location_events, 
                                          key=lambda x: abs(len(str(x[0])[:19]) - len(status_time_str)) 
                                          if isinstance(x[0], str) else 9999)
                    
                    if sorted_events:
                        closest_location = sorted_events[0]
                        lat, lon = closest_location[1], closest_location[2]
                        # Создаем маркер для смены статуса с детальной информацией
                        folium.Marker(
                            [lat, lon],
                            popup=f"<b>Изменение статуса</b><br><b>Время:</b> {time_key}<br><b>Координаты:</b> [{lat:.6f}, {lon:.6f}]<br><b>Новый статус:</b> {status}",
                            tooltip=f"ℹ️ Статус: {status} | ⏱️ {time_key} | 📍[{lat:.6f}, {lon:.6f}]",
                            icon=folium.Icon(color='purple', icon='info-sign')
                        ).add_to(m)
                except Exception as e:
                    logger.error(f"Ошибка при поиске ближайшей точки для статуса: {e}")
        
        elif event[0] == "location":
            # Это событие местоположения
            event_type, time_key, lat, lon, loc_type, timestamp = event
            
            # Форматируем время для отображения с учетом часового пояса Москвы (UTC+3)
            time_str = time_key
            try:
                if isinstance(time_key, str):
                    time_obj = datetime.strptime(time_key, '%Y-%m-%d %H:%M:%S')
                    # Добавляем 3 часа к времени для соответствия московскому часовому поясу
                    adjusted_time = time_obj.replace(hour=(time_obj.hour + 3) % 24)
                    time_str = adjusted_time.strftime('%H:%M:%S')
                    # Если перешли на следующий день
                    if adjusted_time.hour < time_obj.hour:
                        time_str += " (+1 день)"
            except Exception as e:
                logger.warning(f"Ошибка форматирования времени: {e}")
                pass
            
            # Добавляем точку в текущий сегмент
            current_segment.append([lat, lon])
            
            # Добавляем маркер для точки на карту
            icon_color = 'blue'
            icon_text = "Точка"
            
            if loc_type == 'start':
                icon_color = 'green'
                icon_text = "🟢 НАЧАЛО"
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(f"<b>Время:</b> {time_str}<br><b>Координаты:</b> [{lat:.6f}, {lon:.6f}]<br><b>Статус:</b> {current_status}", max_width=300),
                    tooltip=f"{icon_text} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}",
                    icon=folium.Icon(color=icon_color, icon='play')
                ).add_to(m)
            elif loc_type == 'end':
                icon_color = 'red'
                icon_text = "🔴 КОНЕЦ"
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(f"<b>Время:</b> {time_str}<br><b>Координаты:</b> [{lat:.6f}, {lon:.6f}]<br><b>Статус:</b> {current_status}", max_width=300),
                    tooltip=f"{icon_text} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}",
                    icon=folium.Icon(color=icon_color, icon='stop')
                ).add_to(m)
            elif loc_type == 'stationary':
                icon_color = 'orange'
                icon_text = "⏸️ ОСТАНОВКА"
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(f"<b>Время:</b> {time_str}<br><b>Координаты:</b> [{lat:.6f}, {lon:.6f}]<br><b>Статус:</b> {current_status}", max_width=300),
                    tooltip=f"{icon_text} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}",
                    icon=folium.Icon(color=icon_color, icon='pause')
                ).add_to(m)
            else:
                # Для обычных точек используем круговые маркеры
                folium.CircleMarker(
                    [lat, lon],
                    radius=3,
                    popup=folium.Popup(f"<b>Время:</b> {time_str}<br><b>Координаты:</b> [{lat:.6f}, {lon:.6f}]<br><b>Статус:</b> {current_status}", max_width=300),
                    tooltip=f"⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}",
                    color=icon_color,
                    fill=True,
                    fill_color=icon_color
                ).add_to(m)
    
    # Добавляем последний сегмент, если он не пустой
    if current_segment:
        path_segments.append(current_segment)
    
    # Отрисовываем сегменты маршрута разными цветами
    colors = ['blue', 'red', 'green', 'purple', 'orange', 'darkred', 'darkblue', 'darkgreen', 'cadetblue', 'darkpurple']
    
    for i, segment in enumerate(path_segments):
        # Проверяем, что в сегменте есть хотя бы 2 точки для рисования линии
        if len(segment) > 1:
            segment_color = colors[i % len(colors)]
            
            # Добавляем выразительные маркеры начала и конца сегмента
            # Начальная точка сегмента с явной меткой и подробной информацией
            lat, lon = segment[0]
            # Ищем ближайшую по времени точку к началу сегмента
            time_str = "Неизвестно"
            for event in location_events:
                if abs(event[1] - lat) < 0.001 and abs(event[2] - lon) < 0.001:
                    time_str = event[3] if len(event) > 3 else "Неизвестно"
                    break
                
            folium.CircleMarker(
                location=segment[0],
                radius=8,
                color=segment_color,
                fill=True,
                fill_color='white',
                fill_opacity=0.7,
                popup=f"<b>НАЧАЛО сегмента {i+1}</b><br>Время: {time_str}<br>Координаты: [{lat:.6f}, {lon:.6f}]<br>Статус: {current_status}",
                tooltip=f"🟢 НАЧАЛО сегмента {i+1} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}"
            ).add_to(m)
            
            # Конечная точка сегмента с явной меткой и подробной информацией
            lat, lon = segment[-1]
            # Ищем ближайшую по времени точку к концу сегмента
            time_str = "Неизвестно"
            for event in location_events:
                if abs(event[1] - lat) < 0.001 and abs(event[2] - lon) < 0.001:
                    time_str = event[3] if len(event) > 3 else "Неизвестно"
                    break
                
            folium.CircleMarker(
                location=segment[-1],
                radius=8,
                color=segment_color,
                fill=True,
                fill_color='black',
                fill_opacity=0.7,
                popup=f"<b>КОНЕЦ сегмента {i+1}</b><br>Время: {time_str}<br>Координаты: [{lat:.6f}, {lon:.6f}]<br>Статус: {current_status}",
                tooltip=f"🔴 КОНЕЦ сегмента {i+1} | ⏱️ {time_str} | 📍[{lat:.6f}, {lon:.6f}] | 📋 {current_status}"
            ).add_to(m)
            
            # Сам маршрут
            segment_popup = folium.Html(f"""
            <div style="width: 300px; max-width: 100%;">
                <h4>Сегмент маршрута {i+1}</h4>
                <p><b>Время:</b> {time_str}</p>
                <p><b>Статус:</b> {current_status}</p>
                <p><b>Начальные координаты:</b> [{segment[0][0]:.6f}, {segment[0][1]:.6f}]</p>
                <p><b>Конечные координаты:</b> [{segment[-1][0]:.6f}, {segment[-1][1]:.6f}]</p>
                <p><b>Количество точек:</b> {len(segment)}</p>
            </div>
            """, script=True)
            
            folium.PolyLine(
                segment,
                color=segment_color,
                weight=4,
                opacity=0.8,
                tooltip=f"🚶 Сегмент маршрута {i+1} | ⏱️ {time_str} | 📋 {current_status}",
                popup=folium.Popup(segment_popup, max_width=350)
            ).add_to(m)
            
    logger.info(f"Добавлено {len(path_segments)} сегментов маршрута с разными цветами")
    
    # Обязательно отмечаем начальную и конечную точку маршрута, если есть
    if location_events:
        # Первая точка
        first_event = location_events[0]
        lat, lon = first_event[1], first_event[2]
        first_time = first_event[3] if len(first_event) > 3 else "Неизвестно"
        folium.Marker(
            [lat, lon],
            popup=f"<b>Начало маршрута</b><br>Время: {first_time}<br>Координаты: [{lat:.6f}, {lon:.6f}]",
            tooltip=f"🟢 Начало маршрута | ⏱️ {first_time} | 📍[{lat:.6f}, {lon:.6f}]",
            icon=folium.Icon(color='green', icon='play')
        ).add_to(m)
        
        # Последняя точка
        last_event = location_events[-1]
        lat, lon = last_event[1], last_event[2]
        last_time = last_event[3] if len(last_event) > 3 else "Неизвестно"
        folium.Marker(
            [lat, lon],
            popup=f"<b>Конец маршрута</b><br>Время: {last_time}<br>Координаты: [{lat:.6f}, {lon:.6f}]",
            tooltip=f"🔴 Конец маршрута | ⏱️ {last_time} | 📍[{lat:.6f}, {lon:.6f}]",
            icon=folium.Icon(color='red', icon='stop')
        ).add_to(m)
    
    # Сохраняем карту
    map_filename = f"map_{safe_user_name}_{date or datetime.now().strftime('%Y-%m-%d')}.html"
    m.save(map_filename)
    logger.info(f"Карта успешно создана: {map_filename}")
    
    return map_filename

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            user_id = int(sys.argv[1])
            date = sys.argv[2] if len(sys.argv) > 2 else None
            
            map_file = create_direct_map(user_id, date)
            
            if os.path.exists(map_file):
                print(f"✅ Карта успешно создана: {map_file}")
                print(f"Размер файла: {os.path.getsize(map_file)} байт")
                sys.exit(0)
            else:
                print("❌ Карта не создана")
                sys.exit(1)
        except ValueError:
            print(f"Неверный формат ID пользователя: {sys.argv[1]}")
            sys.exit(1)
    else:
        print("Использование: python fixed_map_generator.py <user_id> [date]")
        print("Пример: python fixed_map_generator.py 502488869 2025-05-07")
        sys.exit(1)