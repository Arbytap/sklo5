import logging
import os
from datetime import datetime, time, timedelta
from telegram.ext import CallbackContext
from models import (
    get_unchecked_users_for_morning, record_morning_check, 
    update_morning_check_notification, is_user_in_night_shift,
    get_all_users
)
from config import MOSCOW_TZ, ADMIN_ID, MORNING_CHECK_START_TIME, MORNING_CHECK_END_TIME, DAILY_REPORT_TIME
from utils import is_workday, generate_csv_report, create_map_for_user
from database import get_user_locations, get_active_location_sessions, mark_session_ended

logger = logging.getLogger(__name__)

def morning_check_task(context: CallbackContext):
    """Task to check if users have reported their status by 8:30 AM"""
    now = datetime.now(MOSCOW_TZ)
    
    # Only run this check on workdays
    if not is_workday():
        logger.info(f"Skipping morning check on non-workday: {now.strftime('%A')}")
        return
    
    # Only run between configured times (default 8:30 AM - 10:00 AM)
    current_time = now.time()
    start_time = time(*MORNING_CHECK_START_TIME)  # 8:30 AM
    end_time = time(*MORNING_CHECK_END_TIME)      # 10:00 AM
    
    if not (start_time <= current_time < end_time):
        return
    
    today_date = now.strftime('%Y-%m-%d')
    
    # Get users who haven't checked in this morning
    unchecked_users = get_unchecked_users_for_morning(today_date)
    
    for user_id, full_name, notified, admin_notified in unchecked_users:
        # Skip if both notifications have been sent
        if notified and admin_notified:
            continue
        
        # Skip users currently in night shift
        if is_user_in_night_shift(user_id):
            logger.info(f"Skipping morning check for user {full_name} (ID: {user_id}) - in night shift")
            # Mark as notified to prevent future notifications
            update_morning_check_notification(user_id, today_date, notified=True, admin_notified=True)
            continue
        
        # Check if user has special status today (С ночи, В отпуске, На больничном)
        from database import get_user_status_history
        
        # Получаем статусы за текущий день
        today_statuses = get_user_status_history(user_id, date=today_date)
        
        logger.info(f"Checking statuses for user {full_name} (ID: {user_id}). Found {len(today_statuses)} statuses for today.")
        
        # Статусы, для которых не нужно отправлять утреннее оповещение
        skip_statuses = ["from_night", "vacation", "sick"]  # С ночи, В отпуске, На больничном
        
        # Проверяем статусы за сегодня
        if today_statuses:
            # Логируем все статусы пользователя за сегодня
            status_list = ", ".join([f"{status} ({ts})" for status, ts in today_statuses])
            logger.info(f"User {full_name} statuses for today: {status_list}")
            
            # Проверяем последний статус пользователя
            last_status = today_statuses[-1][0] if today_statuses else None
            logger.info(f"Last status for user {full_name}: {last_status}")
            
            # Проверяем, есть ли среди статусов те, которые исключают утреннее оповещение
            has_skip_status = any(status in skip_statuses for status, _ in today_statuses)
            
            if has_skip_status:
                status_desc = ""
                if any(status == "from_night" for status, _ in today_statuses):
                    status_desc = "С ночи"
                elif any(status == "vacation" for status, _ in today_statuses):
                    status_desc = "В отпуске"
                elif any(status == "sick" for status, _ in today_statuses):
                    status_desc = "На больничном"
                    
                logger.info(f"Skipping morning check for user {full_name} (ID: {user_id}) - status '{status_desc}'")
                # Mark as notified to prevent future notifications
                update_morning_check_notification(user_id, today_date, notified=True, admin_notified=True)
                continue
        
        # Если нет статусов за сегодня, проверяем вчерашний день для длительных статусов (отпуск, больничный)
        yesterday = (datetime.now(MOSCOW_TZ) - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_statuses = get_user_status_history(user_id, date=yesterday)
        
        if yesterday_statuses:
            logger.info(f"Checking yesterday's statuses for user {full_name}. Found {len(yesterday_statuses)} statuses.")
            
            # Проверяем только последний статус за вчера
            last_yesterday_status = yesterday_statuses[-1][0] if yesterday_statuses else None
            
            # Если последний статус вчера был "vacation" или "sick", пропускаем утреннее оповещение
            if last_yesterday_status in ["vacation", "sick"]:
                status_desc = "В отпуске" if last_yesterday_status == "vacation" else "На больничном"
                logger.info(f"Skipping morning check for user {full_name} (ID: {user_id}) - last status from yesterday: '{status_desc}'")
                update_morning_check_notification(user_id, today_date, notified=True, admin_notified=True)
                continue
        
        # Send notification to user if not sent yet
        if not notified:
            try:
                user_message = (
                    f"⚠️ Доброе утро, {full_name}!\n\n"
                    f"Вы еще не отметили свой статус сегодня. "
                    f"Пожалуйста, нажмите одну из кнопок статуса на клавиатуре."
                )
                # Get user keyboard from bot.py
                from bot import get_user_keyboard
                from telegram import ReplyKeyboardMarkup
                
                # Create keyboard with status buttons
                user_keyboard = get_user_keyboard(user_id)
                reply_markup = ReplyKeyboardMarkup(user_keyboard, resize_keyboard=True)
                
                # Send message with keyboard
                context.bot.send_message(
                    chat_id=user_id, 
                    text=user_message,
                    reply_markup=reply_markup
                )
                logger.info(f"Morning check notification sent to user {full_name} (ID: {user_id}) with keyboard")
            except Exception as e:
                logger.error(f"Error sending notification to user {user_id}: {e}")
        
        # Send notification to admin if not sent yet
        if not admin_notified:
            try:
                admin_message = (
                    f"⚠️ Уведомление о непройденной утренней отметке:\n\n"
                    f"Пользователь {full_name} не отметил свой статус сегодня до 8:30."
                )
                context.bot.send_message(chat_id=ADMIN_ID, text=admin_message)
                logger.info(f"Admin notification sent for user {full_name} (ID: {user_id})")
            except Exception as e:
                logger.error(f"Error sending notification to admin: {e}")
        
        # Update the notification status
        update_morning_check_notification(user_id, today_date, notified=True, admin_notified=True)

def reset_morning_checks_task(context: CallbackContext):
    """Task to reset morning checks for the new day"""
    now = datetime.now(MOSCOW_TZ)
    
    # Only run this at midnight
    current_time = now.time()
    if not (time(0, 0) <= current_time < time(0, 10)):
        return
    
    # Only run on workdays or Sunday night (to prepare for Monday)
    if now.weekday() >= 5 and now.weekday() != 6:  # Skip Saturday, but run on Sunday
        return
    
    # The date for the new day
    today_date = now.strftime('%Y-%m-%d')
    logger.info(f"Resetting morning checks for {today_date}")
    
    # Reset will happen automatically in get_unchecked_users_for_morning() when called

def location_interval_task(context: CallbackContext):
    """Задача для сохранения местоположения пользователей каждые 5 минут
    
    Эта функция запрашивает у Telegram последнее известное местоположение
    для пользователей, которые активно делятся своей геолокацией.
    """
    logger.info("Запуск задачи интервального сохранения местоположения")
    
    # Получаем всех пользователей, которые активно делятся местоположением
    active_users = []
    chat_data = context.dispatcher.chat_data
    
    # Итерация по всем чатам
    for chat_id, data in chat_data.items():
        # Проверяем, что data - это словарь (dict)
        if isinstance(data, dict):
            # Проверяем, есть ли ключи отслеживания местоположения
            for key, value in data.items():
                if isinstance(key, str) and key.startswith("location_tracking_") and value:
                    user_id = int(key.replace("location_tracking_", ""))
                    session_id = data.get(f"location_session_{user_id}")
                    if session_id:
                        active_users.append((user_id, session_id))
    
    # Также добавляем все активные сессии из базы данных для дополнительной надежности
    try:
        from database import get_active_location_sessions
        from models import get_all_users
        
        users = get_all_users()
        for user_id, user_name, _ in users:
            try:
                sessions = get_active_location_sessions(user_id)
                for session_id in sessions:
                    user_session_pair = (user_id, session_id)
                    if user_session_pair not in active_users:
                        active_users.append(user_session_pair)
                        logger.info(f"Добавлена активная сессия {session_id} для пользователя {user_name} из БД")
            except Exception as e:
                logger.error(f"Ошибка при получении активных сессий для пользователя {user_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при получении пользователей из БД: {e}")
    
    logger.info(f"Найдено {len(active_users)} активных пользователей для обновления местоположения")
    
    # Для каждого активного пользователя пробуем получить актуальное местоположение от Telegram
    # Мы не можем получить местоположение напрямую, поэтому используем Live Location API
    # Но мы можем запросить у пользователя его текущее местоположение
    for user_id, session_id in active_users:
        try:
            # Получаем имя пользователя
            from models import get_user_name_by_id
            user_name = get_user_name_by_id(user_id) or f"User {user_id}"
            
            # Пробуем найти пользователя в chat_data и проверяем наличие обновленного местоположения
            # В функции handle_location мы записываем последнее местоположение в chat_data
            user_location_data = context.dispatcher.chat_data.get(user_id, {}).get('last_location', None)
            
            if user_location_data:
                lat = user_location_data.get('latitude')
                lon = user_location_data.get('longitude')
                
                # Проверяем данные на валидность
                if lat is not None and lon is not None:
                    from database import save_location
                    
                    # Сохраняем новую промежуточную точку с актуальными координатами
                    save_location(user_id, lat, lon, session_id=session_id, location_type='intermediate')
                    logger.info(f"Сохранено актуальное местоположение [{lat}, {lon}] для пользователя {user_name}")
                    
                    # Сбрасываем местоположение в chat_data, чтобы при следующем обновлении не использовать старые данные
                    context.dispatcher.chat_data[user_id]['last_location'] = None
                else:
                    logger.warning(f"Некорректные координаты для пользователя {user_name}: {user_location_data}")
            else:
                # Если нет данных о местоположении в chat_data, запрашиваем его у пользователя
                try:
                    # Запрашиваем местоположение только если давно не обновлялось (не чаще раза в час)
                    from database import get_user_locations
                    
                    last_locations = get_user_locations(user_id, hours_limit=1, session_id=session_id)
                    current_time = datetime.now()
                    
                    # Если последнее обновление было более 1 часа назад или местоположений нет совсем
                    should_request = False
                    if not last_locations:
                        should_request = True
                    else:
                        # Проверяем формат timestamp и безопасно конвертируем его
                        last_timestamp = last_locations[-1][2]
                        if isinstance(last_timestamp, str):
                            try:
                                last_timestamp_dt = datetime.strptime(last_timestamp, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                try:
                                    last_timestamp_dt = datetime.strptime(last_timestamp, '%Y-%m-%d %H:%M:%S.%f')
                                except Exception:
                                    # Если не удалось распарсить, считаем что обновление нужно
                                    should_request = True
                                    last_timestamp_dt = None
                        else:
                            last_timestamp_dt = last_timestamp
                        
                        # Проверяем разницу во времени, если timestamp успешно преобразован
                        if last_timestamp_dt is not None:
                            # Преобразуем current_time в зависимости от типа last_timestamp_dt
                            if last_timestamp_dt.tzinfo:
                                # Если last_timestamp_dt с часовым поясом, сравниваем с current_time с часовым поясом
                                current_time_tz = current_time.replace(tzinfo=last_timestamp_dt.tzinfo)
                                diff_seconds = (current_time_tz - last_timestamp_dt).total_seconds()
                            else:
                                # Если last_timestamp_dt без часового пояса, то сравниваем с current_time без часового пояса
                                current_time_naive = current_time.replace(tzinfo=None)
                                diff_seconds = (current_time_naive - last_timestamp_dt).total_seconds()
                            
                            should_request = diff_seconds > 3600
                        else:
                            should_request = True
                    
                    if should_request:
                        # Отправляем пользователю сообщение с просьбой поделиться местоположением
                        context.bot.send_message(
                            chat_id=user_id,
                            text="Пожалуйста, поделитесь вашим текущим местоположением для обновления маршрута."
                        )
                        logger.info(f"Отправлен запрос местоположения пользователю {user_name}")
                except Exception as loc_err:
                    logger.error(f"Ошибка при запросе местоположения у пользователя {user_name}: {loc_err}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении местоположения для пользователя {user_id}: {e}")

def daily_report_task(context: CallbackContext, force=False):
    """Task to generate and send daily reports at 17:30
    
    Args:
        context: CallbackContext from the update handler
        force: If True, skip time check and generate reports immediately
    """
    now = datetime.now(MOSCOW_TZ)
    
    # Skip time and workday checks if force=True
    if not force:
        # Only run this check on workdays
        if not is_workday():
            logger.info(f"Skipping daily report on non-workday: {now.strftime('%A')}")
            return
        
        # Only run at the configured time (default 17:30)
        current_time = now.time()
        report_time = time(*DAILY_REPORT_TIME)  # 17:30
        
        # Allow a 5-minute window for the job to run
        if not (report_time <= current_time < time(report_time.hour, report_time.minute + 5)):
            return
            
    logger.info(f"Starting daily report generation{' (forced)' if force else ''}")
    
    today_date = now.strftime('%Y-%m-%d')
    logger.info(f"Generating daily reports for {today_date}")
    
    # Get all users
    from models import get_all_users
    users_data = get_all_users()
    # Преобразуем формат данных в (user_id, user_name)
    users = [(user[0], user[1]) for user in users_data]
    logger.info(f"Обработка {len(users)} пользователей")
    
    for user_id, user_name in users:
        try:
            # End any active location sessions
            active_sessions = get_active_location_sessions(user_id)
            for session_id in active_sessions:
                mark_session_ended(session_id, user_id)
                logger.info(f"Ended active location session {session_id} for user {user_name} (ID: {user_id})")
            
            # Generate report
            report_file = generate_csv_report(user_id, today_date)
            
            if os.path.exists(report_file):
                # Отправляем отчет только администраторам
                report_message = f"📊 Ежедневный отчет для {user_name} ({today_date})"
                
                # Отправка отчета только администраторам
                context.bot.send_document(
                    chat_id=ADMIN_ID,
                    document=open(report_file, 'rb'),
                    filename=f"report_{user_name}_{today_date}.csv",
                    caption=f"{report_message} (отправлен автоматически)"
                )
                
                # Generate map if locations available
                locations = get_user_locations(user_id, hours_limit=24, date=today_date)
                
                if locations:
                    try:
                        # Format locations for map
                        map_locations = []
                        logger.info(f"Получено {len(locations)} точек для карты пользователя {user_name}")
                        
                        for loc in locations:
                            try:
                                # В get_today_locations_for_user возвращаются следующие данные:
                                # (latitude, longitude, timestamp, session_id, location_type)
                                lat, lon, timestamp, session_id, loc_type = loc
                                
                                # Проверяем и конвертируем данные
                                if isinstance(lat, str):
                                    lat = float(lat)
                                if isinstance(lon, str):
                                    lon = float(lon)
                                
                                # Форматируем timestamp, если он строка
                                if isinstance(timestamp, str):
                                    try:
                                        timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                                    except ValueError:
                                        try:
                                            timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f')
                                        except Exception as e:
                                            logger.error(f"Не удалось распарсить timestamp локации: {e}")
                                            timestamp = datetime.now(MOSCOW_TZ)
                                
                                map_locations.append((lat, lon, timestamp, loc_type))
                                logger.debug(f"Точка добавлена: {lat}, {lon}, {timestamp}, {loc_type}")
                            except Exception as e:
                                logger.error(f"Ошибка при обработке локации для карты: {e}, данные: {loc}")
                                continue
                        
                        if map_locations:
                            logger.info(f"Создание карты для {user_name} с {len(map_locations)} точками")
                            map_file = create_map_for_user(user_id, map_locations, user_name)
                            
                            if map_file and os.path.exists(map_file):
                                # Отправка карты только администраторам
                                with open(map_file, 'rb') as f:
                                    context.bot.send_document(
                                        chat_id=ADMIN_ID,
                                        document=f,
                                        filename=f"map_{user_name}_{today_date}.html",
                                        caption=f"🗺️ Карта перемещений {user_name} за {today_date}"
                                    )
                                
                                # Clean up
                                os.remove(map_file)
                                logger.info(f"Карта успешно отправлена для {user_name}")
                            else:
                                logger.warning(f"Файл карты не был создан для {user_name}")
                        else:
                            logger.warning(f"Нет точек для создания карты для {user_name}")
                    except Exception as e:
                        logger.error(f"Ошибка при генерации карты для ежедневного отчета: {e}")
                
                # Clean up
                os.remove(report_file)
                logger.info(f"Daily report sent for user {user_name} (ID: {user_id})")
            else:
                logger.warning(f"No report file generated for user {user_name} (ID: {user_id})")
        except Exception as e:
            logger.error(f"Error generating daily report for user {user_id}: {e}")


def check_user_activity(context: CallbackContext):
    """Проверка активности пользователей
    
    Функция проверяет, если пользователь не отправлял координаты в течение 30 минут
    и не менял свой статус, оповещает администратора.
    """
    logger.info("Запуск проверки активности пользователей")
    
    try:
        from database import get_user_locations, get_user_status_history
        from models import get_user_name_by_id, get_all_users
        from config import ADMIN_ID
        
        # Получаем всех пользователей (не админов)
        users = get_all_users()
        current_time = datetime.now()
        
        for user_id, user_name, is_admin in users:
            try:
                # Пропускаем проверку для администраторов
                if is_admin:
                    logger.debug(f"Пропускаем проверку активности для администратора {user_name}")
                    continue
                    
                # Проверяем текущий статус пользователя
                status_history = get_user_status_history(user_id, days=1)
                
                # Если у пользователя нет записей о статусах совсем, пропускаем его
                if not status_history:
                    logger.debug(f"Пользователь {user_name} не имеет записей о статусах, пропускаем проверку")
                    continue
                
                # Получаем последний статус и время его установки
                last_status, status_timestamp = status_history[-1]
                
                # Безопасно конвертируем timestamp в datetime
                if isinstance(status_timestamp, str):
                    try:
                        status_timestamp_dt = datetime.strptime(status_timestamp, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            status_timestamp_dt = datetime.strptime(status_timestamp, '%Y-%m-%d %H:%M:%S.%f')
                        except Exception as e:
                            logger.error(f"Не удалось распарсить timestamp статуса для {user_name}: {e}")
                            status_timestamp_dt = current_time
                else:
                    status_timestamp_dt = status_timestamp
                
                # Проверяем, не является ли текущий статус "безопасным" (отпуск, больничный, ночная смена)
                safe_statuses = ['vacation', 'sick', 'to_night', 'from_night']
                if last_status in safe_statuses:
                    logger.debug(f"Пользователь {user_name} имеет безопасный статус '{last_status}', пропускаем проверку")
                    continue
                
                # Если статус изменялся недавно (менее 30 минут назад), считаем пользователя активным
                status_time_diff = (current_time - status_timestamp_dt).total_seconds()
                if status_time_diff < 30 * 60:
                    logger.debug(f"Пользователь {user_name} недавно менял статус ({int(status_time_diff/60)} мин. назад), считаем активным")
                    continue
                
                # Запрашиваем последние местоположения пользователя
                last_locations = get_user_locations(user_id, hours_limit=1)
                
                # Если местоположений нет вообще, пропускаем проверку (возможно, не используется трекинг)
                if not last_locations:
                    logger.debug(f"У пользователя {user_name} нет данных о местоположении, пропускаем проверку")
                    continue
                
                # Получаем время последнего обновления координат
                last_timestamp = last_locations[-1][2]
                
                # Безопасно конвертируем timestamp в datetime
                if isinstance(last_timestamp, str):
                    try:
                        last_timestamp_dt = datetime.strptime(last_timestamp, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            last_timestamp_dt = datetime.strptime(last_timestamp, '%Y-%m-%d %H:%M:%S.%f')
                        except Exception as e:
                            logger.error(f"Не удалось распарсить timestamp локации для {user_name}: {e}")
                            last_timestamp_dt = current_time
                else:
                    last_timestamp_dt = last_timestamp
                
                # Проверяем, прошло ли 30 минут с момента последнего обновления координат
                location_time_diff = (current_time - last_timestamp_dt).total_seconds()
                
                # Если прошло более 30 минут и статус не менялся, отправляем уведомление администратору
                if location_time_diff > 30 * 60:
                    # Проверяем, не отправлялось ли уже уведомление в течение последнего часа
                    notification_key = f"inactivity_notified_{user_id}"
                    last_notification = context.bot_data.get(notification_key, 0)
                    
                    # Отправляем уведомление не чаще раза в час
                    if current_time.timestamp() - last_notification > 3600:
                        # Форматируем время для сообщения
                        time_diff_minutes = int(location_time_diff / 60)
                        last_coord_time = last_timestamp_dt.strftime('%H:%M:%S')
                        
                        # Получаем текущий статус в понятном формате
                        from config import STATUS_OPTIONS
                        status_display = STATUS_OPTIONS.get(last_status, last_status)
                        
                        # Отправляем уведомление администратору
                        admin_message = (
                            f"⚠️ <b>Внимание!</b> Пользователь <b>{user_name}</b> не отправлял координаты "
                            f"в течение <b>{time_diff_minutes} минут</b>.\n\n"
                            f"Последние координаты в: <b>{last_coord_time}</b>\n"
                            f"Текущий статус: <b>{status_display}</b>\n"
                            f"Статус установлен: <b>{status_timestamp_dt.strftime('%H:%M:%S')}</b>"
                        )
                        
                        try:
                            context.bot.send_message(
                                chat_id=ADMIN_ID,
                                text=admin_message,
                                parse_mode='HTML'
                            )
                            
                            # Сохраняем время отправки уведомления
                            context.bot_data[notification_key] = current_time.timestamp()
                            
                            logger.info(f"Отправлено уведомление администратору о неактивности пользователя {user_name}: "
                                      f"{time_diff_minutes} мин. без координат, статус: {last_status}")
                        except Exception as e:
                            logger.error(f"Ошибка при отправке уведомления администратору о неактивности {user_name}: {e}")
                    else:
                        logger.debug(f"Уведомление о неактивности пользователя {user_name} уже отправлялось недавно, пропускаем")
                else:
                    logger.debug(f"Пользователь {user_name} активен, последнее обновление координат {int(location_time_diff/60)} мин. назад")
            
            except Exception as e:
                logger.error(f"Ошибка при проверке активности пользователя {user_id}: {e}")
    
    except Exception as e:
        logger.error(f"Общая ошибка при проверке активности пользователей: {e}")
