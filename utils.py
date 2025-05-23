import logging
import pandas as pd
import folium
import io
from datetime import datetime, time as dt_time
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import MOSCOW_TZ, STATUS_OPTIONS

logger = logging.getLogger(__name__)

def log_update(update):
    """Log information about the incoming update."""
    if update.message:
        logger.info(f"Received message from {update.message.from_user.username or update.message.from_user.id}: "
                   f"{update.message.text}")
    elif update.callback_query:
        logger.info(f"Received callback query from {update.callback_query.from_user.username or update.callback_query.from_user.id}: "
                   f"{update.callback_query.data}")

def extract_user_data(user):
    """Extract user data from a Telegram User object."""
    return {
        'user_id': user.id,
        'is_bot': user.is_bot,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'username': user.username,
        'language_code': user.language_code
    }

def format_bot_help():
    """Format the help message for the bot."""
    help_text = (
        "🤖 *Команды бота* 🤖\n\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать это сообщение\n"
        "/status - Установить статус\n"
        "/request - Запросить отгул/отпуск\n"
        "/myrequests - Посмотреть мои заявки\n"
        "/timeoff_stats - Статистика по отгулам\n"
        "/cancel - Отменить текущую операцию\n\n"
        "🔸 *Для администраторов* 🔸\n"
        "/admin - Панель администратора\n"
        "/locate - Найти сотрудника\n"
        "/requests - Просмотр ожидающих заявок\n"
        "/report - Сформировать отчет\n"
        "/generate_reports - Запустить отправку ежедневных отчетов\n"
    )
    return help_text

def is_workday():
    """Check if today is a workday (Monday-Friday)"""
    now = datetime.now(MOSCOW_TZ)
    # 0 = Monday, 6 = Sunday
    return now.weekday() < 5

def is_admin(user_id):
    """Check if a user is an admin"""
    from config import ADMIN_ID, ADMIN_IDS
    
    # Проверяем основного администратора
    if user_id == ADMIN_ID:
        return True
    
    # Проверяем список дополнительных администраторов
    if ADMIN_IDS:
        try:
            admin_list = [int(id.strip()) for id in ADMIN_IDS.split(",")]
            return user_id in admin_list
        except (ValueError, AttributeError) as e:
            logger.error(f"Ошибка при разборе списка администраторов: {e}")
    
    return False

def create_map_for_user(user_id, locations, user_name=None, date=None):
    """Create a map with user's locations
    
    Args:
        user_id: ID of the user
        locations: List of (lat, lon, timestamp, loc_type) tuples
        user_name: Optional name of the user
        date: Date string in format 'YYYY-MM-DD' for the map filename
    
    Returns:
        Path to the generated HTML map file
    """
    # Используем напрямую нашу исправленную функцию из direct_map_fix
    try:
        # Импортируем функцию
        from fixed_map_generator import create_direct_map
        
        # Если дата не указана, используем текущую
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
            
        # Вызываем нашу исправленную функцию
        logger.info(f"Вызов исправленной функции create_direct_map для пользователя {user_id} за {date}")
        map_filename = create_direct_map(user_id, date)
        
        # Проверяем результат
        if map_filename and os.path.exists(map_filename):
            logger.info(f"Карта успешно создана через create_direct_map: {map_filename}")
            return map_filename
        else:
            logger.warning(f"Не удалось создать карту через create_direct_map для пользователя {user_id}")
            # Продолжаем выполнение оригинальной функции
    except Exception as e:
        logger.error(f"Ошибка при вызове create_direct_map: {e}")
        # Продолжаем выполнение оригинальной функции
    if not locations:
        logger.warning(f"No locations provided")
        return None
    
    if not user_name:
        from models import get_user_name_by_id
        user_name = get_user_name_by_id(user_id) or f"User {user_id}"
    
    # Filter out invalid coordinates
    valid_locations = []
    for loc in locations:
        # Check location format
        if len(loc) < 3:
            logger.warning(f"Неверный формат данных местоположения: {loc}")
            continue
        
        # Extract lat and lon
        if len(loc) >= 4:
            lat, lon = loc[0], loc[1]
        else:
            lat, lon = loc[0], loc[1]
        
        # Validate coordinates
        try:
            if isinstance(lat, str):
                lat = float(lat)
            if isinstance(lon, str):
                lon = float(lon)
                
            # Skip invalid coordinates
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                logger.warning(f"Координаты вне допустимого диапазона: {lat}, {lon}")
                continue
                
            valid_locations.append(loc)
        except (ValueError, TypeError) as e:
            logger.warning(f"Ошибка при конвертации координат {lat}, {lon}: {e}")
            continue
    
    if not valid_locations:
        logger.warning(f"Нет корректных координат для пользователя {user_name}")
        return None
    
    # Сортируем по времени, чтобы точки были последовательными
    # Сначала приводим все timestamp к datetime
    processed_locations = []
    for loc in valid_locations:
        try:
            # Преобразуем timestamp в datetime, если он строка
            if len(loc) >= 3:
                timestamp = loc[2]
                if isinstance(timestamp, str):
                    try:
                        timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f')
                        except Exception as e:
                            logger.error(f"Не удалось распарсить timestamp: {e}")
                            timestamp = datetime.now(MOSCOW_TZ)
                
                # Создаем новый кортеж с datetime вместо строки
                new_loc = list(loc)
                new_loc[2] = timestamp
                processed_locations.append(tuple(new_loc))
            else:
                processed_locations.append(loc)
        except Exception as e:
            logger.error(f"Ошибка при обработке времени локации: {e}")
            processed_locations.append(loc)
    
    # Сортируем локации по времени
    processed_locations.sort(key=lambda x: x[2] if len(x) >= 3 else datetime.now(MOSCOW_TZ))
    
    # Calculate map center
    lats = [float(loc[0]) if isinstance(loc[0], str) else loc[0] for loc in processed_locations]
    lons = [float(loc[1]) if isinstance(loc[1], str) else loc[1] for loc in processed_locations]
    
    avg_lat = sum(lats) / len(lats)
    avg_lon = sum(lons) / len(lons)
    
    # Create the map with OpenStreetMap tiles
    m = folium.Map(
        location=[avg_lat, avg_lon], 
        zoom_start=15, 
        tiles='OpenStreetMap',
        control_scale=True
    )
    
    # Add markers and path
    path_coords = []
    path_times = []
    path_speeds = []
    movement_types = []
    
    # Define custom icons for different point types
    start_icon = folium.Icon(color='green', icon='play')
    end_icon = folium.Icon(color='red', icon='stop')
    stationary_icon = folium.Icon(color='orange', icon='pause')
    
    # Добавление на карту общей информации
    total_distance = 0  # общее расстояние в метрах
    total_time = 0      # общее время в секундах
    last_lat, last_lon, last_time = None, None, None
    
    # Процессим точки маршрута
    for i, loc_item in enumerate(processed_locations):
        try:
            # Разбираем данные локации в зависимости от формата
            if len(loc_item) >= 5:  # Формат с полями lat, lon, timestamp, session_id, loc_type
                lat, lon, timestamp, _, loc_type = loc_item[:5]
            elif len(loc_item) >= 4:  # Формат локации с четырьмя параметрами
                lat, lon, timestamp, loc_type = loc_item[:4]
                # Если четвертый параметр не строка, то это не тип, а что-то другое
                if not isinstance(loc_type, str):
                    loc_type = 'intermediate'
                    # Автоматически определяем начальную и конечную точки
                    if i == 0:
                        loc_type = 'start'
                    elif i == len(processed_locations) - 1:
                        loc_type = 'end'
            elif len(loc_item) >= 3:  # Минимальный формат
                lat, lon, timestamp = loc_item[:3]
                # Автоматически определяем начальную, промежуточную и конечную точки
                if i == 0:
                    loc_type = 'start'
                elif i == len(processed_locations) - 1:
                    loc_type = 'end'
                else:
                    loc_type = 'intermediate'
            else:
                # Недостаточно данных, пропускаем
                logger.warning(f"Недостаточно данных в записи: {loc_item}")
                continue
                
            # Проверяем и конвертируем координаты
            if not (isinstance(lat, (int, float)) or (isinstance(lat, str) and lat.replace('.', '', 1).isdigit())):
                logger.warning(f"Некорректное значение широты: {lat}, тип: {type(lat)}")
                continue
                
            if not (isinstance(lon, (int, float)) or (isinstance(lon, str) and lon.replace('.', '', 1).isdigit())):
                logger.warning(f"Некорректное значение долготы: {lon}, тип: {type(lon)}")
                continue
                
            # Преобразуем в числовой формат
            if isinstance(lat, str):
                lat = float(lat)
            if isinstance(lon, str):
                lon = float(lon)
            
            # Расчет расстояния и времени относительно предыдущей точки
            distance = 0
            speed = 0
            time_diff = 0
            
            # Если это не первая точка, рассчитываем расстояние и скорость
            if last_lat is not None and last_time is not None:
                from math import sin, cos, sqrt, atan2, radians
                
                R = 6371000  # Радиус Земли в метрах
                
                lat1 = radians(float(last_lat))
                lon1 = radians(float(last_lon))
                lat2 = radians(float(lat))
                lon2 = radians(float(lon))
                
                dlon = lon2 - lon1
                dlat = lat2 - lat1
                
                a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
                c = 2 * atan2(sqrt(a), sqrt(1 - a))
                
                distance = R * c  # Расстояние в метрах
                total_distance += distance
                
                # Расчет времени и скорости
                try:
                    # Проверяем, что timestamp и last_time - объекты datetime
                    if isinstance(timestamp, datetime) and isinstance(last_time, datetime):
                        time_diff = (timestamp - last_time).total_seconds()
                        total_time += time_diff
                        
                        if time_diff > 0:
                            speed = (distance / time_diff) * 3.6  # км/ч
                        else:
                            speed = 0
                    else:
                        # Если это не datetime объекты, используем значения по умолчанию
                        logger.warning(f"Один из timestamp не является datetime объектом: {timestamp}, {last_time}")
                        time_diff = 0
                        speed = 0
                except Exception as e:
                    logger.warning(f"Ошибка при расчете времени: {e}")
                    time_diff = 0
                    speed = 0
            
            # Сохраняем текущие координаты и время для следующей итерации
            last_lat, last_lon, last_time = lat, lon, timestamp
            
            # Определяем статус движения и цвет точки
            point_color = 'blue'  # По умолчанию для промежуточных точек
            movement_status = 'unknown'
            
            # Используем loc_type для определения статуса
            if loc_type == 'start':
                point_color = 'green'
                movement_status = 'start'
            elif loc_type == 'end':
                point_color = 'red'
                movement_status = 'end'
            elif loc_type == 'stationary':
                point_color = 'orange'
                movement_status = 'stationary'
            elif loc_type == 'moving':
                point_color = 'purple'
                movement_status = 'moving'
                if speed > 50:
                    movement_status = 'fast_moving'
                    point_color = 'darkpurple'
            
            movement_types.append(movement_status)
            
            # Обрабатываем timestamp в зависимости от его типа
            try:
                # Если timestamp - строка, пробуем преобразовать в datetime
                if isinstance(timestamp, str):
                    try:
                        # Пытаемся разобрать строку в datetime
                        display_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        # Если не получилось стандартным форматом, пробуем другие варианты
                        try:
                            display_time = datetime.fromisoformat(timestamp)
                        except ValueError:
                            # Если все попытки не удались, используем строку как есть
                            logger.warning(f"Невозможно преобразовать строку времени: {timestamp}")
                            display_time = timestamp
                            time_str = timestamp
                            # Пропускаем дальнейшую обработку
                            continue
                # Если timestamp - объект datetime, используем его напрямую
                elif isinstance(timestamp, datetime):
                    # Преобразуем timestamp в московское время, если он еще не в нем
                    if hasattr(timestamp, 'astimezone'):
                        try:
                            display_time = timestamp.astimezone(MOSCOW_TZ)
                        except Exception as e:
                            logger.warning(f"Ошибка при конвертации времени: {e}")
                            display_time = timestamp
                    else:
                        display_time = timestamp
                else:
                    # Если timestamp не строка и не datetime, пропускаем точку
                    logger.warning(f"Некорректный формат времени: {timestamp}, тип: {type(timestamp)}")
                    continue
                
                # Форматируем время для отображения
                if isinstance(display_time, datetime):
                    time_str = display_time.strftime('%H:%M:%S')
                else:
                    # Если что-то пошло не так и display_time не datetime, преобразуем в строку
                    time_str = str(display_time)
            except Exception as e:
                logger.warning(f"Ошибка при обработке временной метки: {e}")
                time_str = "Неизвестное время"
            
            # Создаем текст для всплывающей подсказки - только время и координаты
            marker_text = f"<b>Время:</b> {time_str}<br><b>Координаты:</b> {lat:.6f}, {lon:.6f}"
            
            # Особая обработка точек в зависимости от статуса
            if loc_type == 'start':
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(marker_text, max_width=300),
                    tooltip=f"🟢 НАЧАЛО {time_str}",
                    icon=start_icon
                ).add_to(m)
            elif loc_type == 'end':
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(marker_text, max_width=300),
                    tooltip=f"🔴 КОНЕЦ {time_str}",
                    icon=end_icon
                ).add_to(m)
            elif loc_type == 'stationary':
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(marker_text, max_width=300),
                    tooltip=f"⏸️ ОСТАНОВКА {time_str}",
                    icon=stationary_icon
                ).add_to(m)
            else:
                # Для промежуточных точек разного типа используем разные цвета и размеры
                radius = 3
                if movement_status == 'moving' or movement_status == 'fast_moving':
                    # Для точек движения увеличиваем размер в зависимости от скорости
                    radius = min(3 + speed / 10, 8)  # Ограничиваем максимальный размер
                
                folium.CircleMarker(
                    [lat, lon],
                    radius=radius,
                    color=point_color,
                    fill=True,
                    fill_color=point_color,
                    fill_opacity=0.7,
                    popup=folium.Popup(marker_text, max_width=300),
                    tooltip=f"{time_str}"
                ).add_to(m)
            
            # Добавляем точку в массив для построения линии маршрута
            path_coords.append([lat, lon])
            path_times.append(time_str)
            path_speeds.append(speed)
            
            logger.debug(f"Добавлена точка: {lat:.6f}, {lon:.6f}, {time_str}, {loc_type}, {speed:.1f} км/ч")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке локации: {e}, данные: {loc_item}")
            continue
    
    # Добавляем линии маршрута, соединяющие точки с учетом времени фиксации
    if len(path_coords) > 1:
        # Создаем простую соединяющую линию через все точки
        folium.PolyLine(
            path_coords,
            color='blue',
            weight=4,
            opacity=0.8,
            tooltip="Маршрут"
        ).add_to(m)
        
        logger.info(f"Добавлены {len(path_coords)} точки маршрута с соединительной линией")
    
    # Итоговая информация о маршруте убрана по запросу пользователя
    
    # Сохраняем карту в файл с именем пользователя и датой данных
    # Используем дату из параметра locations, а не текущую дату
    if user_name and date:
        map_filename = f"map_{user_name}_{date}.html"
    else:
        today_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
        map_filename = f"map_{user_name}_{today_date}.html"
    
    # Добавляем элементы управления и стилизацию
    folium.LayerControl().add_to(m)
    
    # Устанавливаем размеры карты
    m.get_root().html.add_child(folium.Element('''
        <style>
        .leaflet-container {
            height: 100vh;
            width: 100%;
            max-width: 100%;
            max-height: 100%;
        }
        </style>
    '''))
    
    # Легенда удалена по запросу пользователя
    
    # Сохраняем карту
    m.save(map_filename)
    logger.info(f"Карта сохранена в файл: {map_filename}")
    
    return map_filename

def generate_csv_report(user_id, date=None, html_format=False):
    """Generate a CSV or HTML report for a user's activity on a specific date
    
    Args:
        user_id: ID пользователя
        date: Дата в формате строки 'YYYY-MM-DD', если None - используется сегодняшняя дата
        html_format: Если True, дополнительно создает HTML-версию отчета
        
    Returns:
        Путь к созданному файлу отчета (CSV или HTML)
    """
    from database import get_user_status_history, get_today_locations_for_user, get_active_location_sessions, mark_session_ended
    from models import get_user_name_by_id, get_timeoff_stats_for_user, get_timeoff_requests_for_user
    from config import STATUS_OPTIONS
    
    # If date not provided, use today
    if not date:
        date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
    
    # Get user name
    user_name = get_user_name_by_id(user_id) or f"User {user_id}"
    
    logger.info(f"Начало генерации отчета для {user_name} (ID: {user_id}) за {date}")
    
    # Перед получением данных закроем все активные сессии местоположений для актуальности
    if date == datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d'):  # Только для сегодняшней даты
        try:
            active_sessions = get_active_location_sessions(user_id)
            for session_id in active_sessions:
                mark_session_ended(session_id, user_id)
                logger.info(f"Завершена активная сессия {session_id} для отчета пользователя {user_name}")
        except Exception as e:
            logger.error(f"Ошибка при закрытии активных сессий: {e}")
    
    # Get status history for the specified date
    status_history = get_user_status_history(user_id, date=date)
    logger.info(f"Получено {len(status_history)} записей о статусах для пользователя {user_name}")
    logger.debug(f"Записи о статусах: {status_history}")
    
    # Get location history for the specified date
    locations = get_today_locations_for_user(user_id, date=date)
    logger.info(f"Получено {len(locations)} записей о местоположении для пользователя {user_name}")
    logger.debug(f"Первые 5 записей о местоположении: {locations[:5] if locations else []}")
    
    # Get timeoff statistics
    timeoff_stats = get_timeoff_stats_for_user(user_id, date=date)
    
    # Prepare data for unified report
    report_data = []
    
    # Add timeoff statistics if there are any requests
    if timeoff_stats['total'] > 0:
        report_data.append({
            'id': len(report_data) + 1,
            'name': user_name,
            'user_id': user_id,
            'event_type': 'Статистика отгулов',
            'value': f"Всего запросов: {timeoff_stats['total']}, Одобрено: {timeoff_stats['approved']}, Отклонено: {timeoff_stats['rejected']}, Ожидает: {timeoff_stats['pending']}",
            'timestamp': datetime.now(MOSCOW_TZ)
        })
        
        # Get detailed timeoff requests for this date
        timeoff_requests = get_timeoff_requests_for_user(user_id)
        for req_id, reason, request_time, status, response_time in timeoff_requests:
            # Проверка является ли request_time объектом datetime или строкой
            if isinstance(request_time, str):
                try:
                    req_timestamp = datetime.fromisoformat(request_time)
                except ValueError:
                    try:
                        req_timestamp = datetime.strptime(request_time, '%Y-%m-%d %H:%M:%S')
                    except Exception as e:
                        logger.error(f"Не удалось распарсить timestamp запроса отгула: {e}")
                        req_timestamp = datetime.now(MOSCOW_TZ)
            else:
                req_timestamp = request_time
                
            # Сравниваем дату запроса с датой отчета
            if req_timestamp.strftime('%Y-%m-%d') == date:
                # Добавляем запрос отгула в отчет, если он был создан в выбранную дату
                status_texts = {
                    'pending': 'Ожидает рассмотрения',
                    'approved': 'Одобрено',
                    'rejected': 'Отклонено'
                }
                status_text = status_texts.get(status, status)
                
                report_data.append({
                    'id': len(report_data) + 1,
                    'name': user_name,
                    'user_id': user_id,
                    'event_type': 'Запрос отгула',
                    'value': f"Причина: {reason}. Статус: {status_text}",
                    'timestamp': req_timestamp
                })
    
    # Соответствие статусов для перевода (включая сменные статусы)
    status_translations = {
        "office": "🏢 В офисе",
        "sick": "🏥 На больничном",
        "vacation": "🏖 В отпуске",
        "to_night": "🌃 В ночь",
        "from_night": "🌙 С ночи",
        "home": "🏠 Домой",
        "night_shift_start": "🌃 В ночь",
        "night_shift_end": "🌙 С ночи"
    }
    
    # Используем STATUS_OPTIONS как основу для переводов, на случай если там что-то изменится
    for key, value in STATUS_OPTIONS.items():
        status_translations[key] = value
    
    # Process status updates
    for status, timestamp in status_history:
        try:
            # Преобразование timestamp в datetime, если он строка
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    try:
                        timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f')
                    except Exception as e:
                        logger.error(f"Не удалось распарсить timestamp статуса: {e}")
                        continue
            
            # Преобразуем код статуса в русское название
            status_display = status_translations.get(status, status)
            
            report_data.append({
                'id': len(report_data) + 1,
                'name': user_name,
                'user_id': user_id,
                'event_type': 'Статус',
                'value': status_display,
                'timestamp': timestamp
            })
        except Exception as e:
            logger.error(f"Ошибка при обработке статуса: {e}, данные: {status}, {timestamp}")
            continue
    
    # Process location updates
    for loc in locations:
        try:
            # Обрабатываем разные форматы данных о местоположении
            if len(loc) >= 5:  # Полный формат с 5 полями
                lat, lon, ts, session_id, loc_type = loc
            elif len(loc) >= 4:  # Формат с 4 полями
                lat, lon, ts, session_id = loc
                loc_type = 'intermediate'
            elif len(loc) >= 3:  # Минимальный формат с 3 полями
                lat, lon, ts = loc[:3]
                loc_type = 'intermediate'
                session_id = None
            else:
                # Недостаточно данных, пропускаем
                logger.warning(f"Недостаточно данных в записи о местоположении: {loc}")
                continue
            
            # Преобразование координат в числовой формат при необходимости
            if isinstance(lat, str):
                lat = float(lat)
            if isinstance(lon, str):
                lon = float(lon)
                
            # Преобразование timestamp в datetime, если он строка
            if isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    try:
                        ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
                    except Exception as e:
                        logger.error(f"Не удалось распарсить timestamp локации: {e}")
                        continue
            
            # Перевод типов локаций на понятный язык
            location_type_translations = {
                'start': 'Начало трансляции',
                'intermediate': 'Промежуточная точка',
                'end': 'Конец трансляции'
            }
            
            location_type_display = location_type_translations.get(loc_type, loc_type)
            
            # Добавляем координаты в отчет с упорядоченными данными
            report_data.append({
                'id': len(report_data) + 1,
                'name': user_name,
                'user_id': user_id,
                'event_type': f'Местоположение ({location_type_display})',
                'value': f"{lat:.6f},{lon:.6f}",  # Форматируем координаты с фиксированной точностью
                'timestamp': ts
            })
            logger.debug(f"Добавлены данные о местоположении: {lat:.6f}, {lon:.6f}, {ts}, {loc_type}")
        except Exception as e:
            # Логируем ошибку и продолжаем обработку
            logger.error(f"Ошибка при обработке координат: {e}, данные: {loc}")
            continue
    
    # Сортируем данные по времени для хронологического порядка
    report_data.sort(key=lambda x: x['timestamp'])
    
    # Обновляем id после сортировки для последовательной нумерации
    for i, item in enumerate(report_data):
        item['id'] = i + 1
    
    # Импортируем необходимые библиотеки
    from datetime import timedelta
    import pytz
    
    def format_time_moscow(dt):
        """Форматирует время с учетом московского часового пояса"""
        try:
            # Создаем UTC смещение для московского времени (UTC+3)
            moscow_offset = 3  # часы
            
            # Обработка naive datetime объектов (без часового пояса)
            if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
                # Если у datetime нет часового пояса, исходим из того, что это UTC
                # и добавляем 3 часа для московского времени
                moscow_time = dt + timedelta(hours=moscow_offset)
            elif hasattr(dt, 'astimezone'):
                # Если у datetime есть часовой пояс, конвертируем его в UTC сначала,
                # а затем добавляем смещение для московского времени
                utc_time = dt.astimezone(pytz.UTC)
                moscow_time = utc_time + timedelta(hours=moscow_offset)
            else:
                # Если это не datetime объект, просто возвращаем как есть
                return str(dt)
            
            # Форматируем время без указания часового пояса
            return moscow_time.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logger.error(f"Ошибка при форматировании времени: {e}, тип: {type(dt)}")
            # В случае ошибки, возвращаем входное значение как строку
            return str(dt)
    
    # Создаем DataFrame и файл отчета
    try:
        # Создаем DataFrame с нужными колонками в нужном порядке
        if report_data:
            df = pd.DataFrame(report_data)
        else:
            # Если нет данных, создаем DataFrame с одной записью что данных нет
            logger.warning(f"Нет данных для отчета пользователя {user_name} (ID: {user_id}) за {date}")
            df = pd.DataFrame([{
                'id': 1,
                'name': user_name,
                'user_id': user_id,
                'event_type': 'Информация',
                'value': 'Нет данных о местоположении и статусах за указанный период',
                'timestamp': datetime.now(MOSCOW_TZ)
            }])
            
        # Переименовываем колонки для отчета
        df = df.rename(columns={
            'id': 'ID',
            'name': 'ФИО',
            'user_id': 'Пользователь',
            'event_type': 'Тип события',
            'value': 'Значение',
            'timestamp': 'Время'
        })
        
        # Применяем функцию конвертации к столбцу "Время"
        df['Время'] = df['Время'].apply(format_time_moscow)
        
        # Сохраняем в CSV файл
        csv_filename = f"report_{user_id}_{date}.csv"
        df.to_csv(csv_filename, index=False, encoding='utf-8')
        logger.info(f"CSV отчет успешно создан: {csv_filename}, {len(report_data) if report_data else 1} записей")
        
        # Если запрошен HTML формат, создаем и HTML-версию
        if html_format:
            html_filename = f"report_{user_id}_{date}.html"
            
            # Заголовок с информацией о пользователе и дате
            html_header = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Отчет для {user_name} за {date}</title>
                <style>
                    body {{ 
                        font-family: 'Segoe UI', Arial, sans-serif; 
                        margin: 20px;
                        background-color: #f9f9f9;
                        color: #333;
                        font-size: 16px;
                    }}
                    h1 {{ 
                        color: #2c3e50; 
                        padding-bottom: 10px;
                        border-bottom: 2px solid #3498db;
                        margin-bottom: 20px;
                        font-size: 24px;
                    }}
                    table {{ 
                        border-collapse: collapse; 
                        width: 100%; 
                        margin-top: 20px; 
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                        background-color: white;
                        font-size: 14px;
                    }}
                    th, td {{ 
                        border: 1px solid #ddd; 
                        padding: 12px; 
                        text-align: left;
                    }}
                    th {{ 
                        background-color: #3498db; 
                        font-weight: bold;
                        color: white;
                        font-size: 15px;
                    }}
                    tr:nth-child(even) {{ 
                        background-color: #f2f2f2; 
                    }}
                    .status-event {{ 
                        background-color: #d6eaf8; 
                        font-weight: bold;
                    }}
                    .location-event {{ 
                        background-color: #eafaf1; 
                    }}
                    .timestamp {{
                        white-space: nowrap;
                        font-family: monospace;
                        font-size: 14px;
                    }}
                    p {{
                        line-height: 1.5;
                        margin-bottom: 15px;
                        font-size: 16px;
                    }}
                    strong {{
                        font-weight: 600;
                        color: #2c3e50;
                    }}
                </style>
            </head>
            <body>
                <h1>Отчет активности сотрудника</h1>
                <p><strong>Сотрудник:</strong> {user_name} (ID: {user_id})</p>
                <p><strong>Дата отчета:</strong> {date}</p>
                <p><strong>Время формирования:</strong> {datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d %H:%M:%S')}</p>
            """
            
            # Улучшенное форматирование таблицы для HTML-отчета
            # Добавляем класс timestamp к столбцу с временем для лучшего отображения
            for i, col in enumerate(df.columns):
                if col == 'Время':
                    df[col] = df[col].apply(lambda x: f'<span class="timestamp">{x}</span>')
            
            # Преобразуем DataFrame в HTML таблицу с дополнительным форматированием
            # Устанавливаем escape=False чтобы сохранить HTML-теги
            table_html = df.to_html(index=False, classes='report-table', escape=False)
            
            # Заменяем стандартные стили на свои для строк с разными типами событий
            table_html = table_html.replace('<tr>', '<tr class="status-event">')
            table_html = table_html.replace('Местоположение', '</tr><tr class="location-event">Местоположение')
            
            # Завершаем HTML файл
            html_footer = """
            </body>
            </html>
            """
            
            # Собираем полный HTML и сохраняем в файл
            with open(html_filename, 'w', encoding='utf-8') as f:
                f.write(html_header + table_html + html_footer)
            
            logger.info(f"HTML отчет успешно создан: {html_filename}")
            # Удаляем CSV-файл, т.к. в HTML формате он не нужен
            if os.path.exists(csv_filename):
                os.remove(csv_filename)
                logger.info(f"Удален ненужный CSV-файл: {csv_filename}")
            return html_filename
        
        return csv_filename
        
    except Exception as e:
        logger.error(f"Ошибка при создании DataFrame или сохранении файла: {e}")
        # Создаем резервный отчет в случае ошибки DataFrame
        csv_filename = f"report_{user_id}_{date}.csv"
        with open(csv_filename, 'w', encoding='utf-8') as f:
            f.write("ID,ФИО,Пользователь,Тип события,Значение,Время\n")
            if not report_data:
                # Если нет данных, добавляем информационную строку
                time_str = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"1,{user_name},{user_id},Информация,Нет данных о местоположении и статусах за указанный период,{time_str}\n")
            else:
                for item in report_data:
                    # Форматируем время с учетом московского часового пояса
                    time_str = format_time_moscow(item['timestamp'])
                    f.write(f"{item['id']},{item['name']},{item['user_id']},{item['event_type']},{item['value']},{time_str}\n")
        
        logger.info(f"Резервный CSV отчет успешно создан: {csv_filename}")
        return csv_filename

def get_admin_keyboard():
    """Create admin keyboard with admin functions"""
    keyboard = [
        [InlineKeyboardButton("👁️ Местоположение сотрудников", callback_data="admin_locate")],
        [InlineKeyboardButton("📋 Заявки на отсутствие", callback_data="admin_requests")],
        [InlineKeyboardButton("📊 Генерировать отчет", callback_data="admin_report")],
        [InlineKeyboardButton("📅 Управление сменами", callback_data="admin_shifts")],
        [InlineKeyboardButton("📊 Отчеты за сегодня", callback_data="admin_daily_reports")],
        [InlineKeyboardButton("📈 Статистика отгулов", callback_data="admin_timeoff_stats")],
        [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")]
    ]
    
    # Отладочное логирование
    logger.info("Создана клавиатура администратора со следующими кнопками:")
    for row in keyboard:
        for button in row:
            logger.info(f"- Кнопка: {button.text}, callback_data: {button.callback_data}")
    
    return InlineKeyboardMarkup(keyboard)

def handle_error(update, context):
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        update.effective_message.reply_text(
            "Извините, произошла ошибка. Проблема записана в журнал."
        )
        
def generate_map(user_id, date=None):
    """
    Функция-обертка для создания карты маршрута пользователя за указанную дату.
    Использует create_direct_map для генерации карты напрямую из БД.
    
    Args:
        user_id: ID пользователя
        date: Дата в формате 'YYYY-MM-DD', если None - используется сегодняшняя дата
        
    Returns:
        Имя созданного файла карты
    """
    # Используем только функцию из fixed_map_generator для единообразия карт
    try:
        # Импортируем функцию
        from fixed_map_generator import create_direct_map
        
        # Если дата не указана, используем текущую
        if not date:
            date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
            
        # Логируем операцию
        logger.info(f"Генерация карты для пользователя {user_id} за дату {date}")
            
        # Вызываем нашу исправленную функцию
        map_filename = create_direct_map(user_id, date)
        
        # Проверяем результат
        if map_filename and os.path.exists(map_filename):
            logger.info(f"Карта успешно создана: {map_filename}")
            return map_filename
        else:
            logger.warning(f"Не удалось создать карту для пользователя {user_id}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при создании карты: {e}")
        return None
