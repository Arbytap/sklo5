import logging
import os
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ParseMode, 
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, 
    CallbackContext, CallbackQueryHandler, ConversationHandler
)
from datetime import datetime, timedelta
import pandas as pd
import folium
import io

from fixed_map_generator import create_direct_map
# Import our modules
from config import TOKEN, BOT_MODE, WEBHOOK_URL, PORT, ADMIN_ID, MOSCOW_TZ, STATUS_OPTIONS
from database import init_db, save_location, save_status, get_user_locations, get_user_status_history, mark_session_ended
from models import add_or_update_user_mapping, get_user_name_by_id, update_morning_check, is_user_in_night_shift
from utils import log_update, format_bot_help, is_workday, is_admin, create_map_for_user, generate_csv_report
from scheduled_tasks import morning_check_task, reset_morning_checks_task, daily_report_task
from user_management import load_user_mappings_from_file, get_admin_user_selector, find_user_location
from timeoff_requests import register_timeoff_handlers

# Configure logging
logger = logging.getLogger(__name__)

def get_user_keyboard(user_id):
    """Create a custom keyboard based on user's role"""
    # Basic keyboard with status buttons
    keyboard = [
        [KeyboardButton(STATUS_OPTIONS["office"]), KeyboardButton(STATUS_OPTIONS["home"])],
        [KeyboardButton(STATUS_OPTIONS["sick"]), KeyboardButton(STATUS_OPTIONS["vacation"])],
        [KeyboardButton(STATUS_OPTIONS["to_night"]), KeyboardButton(STATUS_OPTIONS["from_night"])],
        [KeyboardButton("📝 Отпроситься")]
    ]
    
    # Add admin buttons if user is admin
    if is_admin(user_id):
        keyboard.append([KeyboardButton("👤 Панель администратора")])
    
    return keyboard

def start(update: Update, context: CallbackContext):
    """Handle the /start command"""
    user = update.effective_user
    
    # Log the new user
    logger.info(f"New user: {user.id} ({user.username or 'No username'})")
    
    # Проверяем, есть ли пользователь в базе данных по ID
    user_name = get_user_name_by_id(user.id)
    
    # Если пользователя нет в базе, проверяем в файле, но не обновляем базу
    if not user_name:
        user_mappings = load_user_mappings_from_file(update_db=False)
        user_name = user_mappings.get(user.id)
        
        # Если пользователь найден в файле, добавляем его в базу данных
        if user_name:
            add_or_update_user_mapping(user.id, user_name)
    
    if user_name:
        welcome_msg = (
            f"Здравствуйте, {user_name}! Добро пожаловать в систему отслеживания статуса и геолокации.\n\n"
            f"📍 Как включить трансляцию геолокации:\n"
            f"1. Нажмите на скрепку 📎 (вложение) справа от поля ввода сообщения\n"
            f"2. Выберите 'Геопозиция' 📍\n"
            f"3. Нажмите 'Транслировать геопозицию' и выберите время трансляции\n"
            f"4. Нажмите 'Поделиться'\n\n"
            f"❗️ Важно: если вы закрыли чат с ботом, трансляция может прерваться. "
            f"При необходимости повторите шаги для возобновления трансляции.\n\n"
            f"Используйте кнопки ниже для установки вашего статуса."
        )
    else:
        welcome_msg = (
            f"Здравствуйте, {user.first_name}! Добро пожаловать в систему отслеживания статуса и геолокации.\n\n"
            f"Ваш ID: {user.id}\n"
            f"⚠️ Обратитесь к администратору для добавления вас в систему."
        )
    
    # Create keyboard based on user role
    keyboard = get_user_keyboard(user.id)
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Send welcome message with keyboard
    update.message.reply_text(welcome_msg, reply_markup=reply_markup)

def help_command(update: Update, context: CallbackContext):
    """Handle the /help command"""
    help_text = format_bot_help()
    update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
def timeoff_stats_command(update: Update, context: CallbackContext):
    """Handle the /timeoff_stats command - show timeoff statistics"""
    user_id = update.effective_user.id
    user_name = get_user_name_by_id(user_id) or update.effective_user.first_name
    
    # Get timeoff statistics for the user
    from models import get_timeoff_stats_for_user
    
    # Default period - last 30 days
    days = 30
    
    # Check if user provided a different period
    if context.args and len(context.args) > 0:
        try:
            days = int(context.args[0])
            if days <= 0:
                days = 30  # Default if invalid
        except ValueError:
            days = 30  # Default if invalid
    
    stats = get_timeoff_stats_for_user(user_id, days=days)
    
    # Create the statistics message
    if stats['total'] > 0:
        message = (
            f"📊 Статистика запросов на отгул за последние {days} дней\n\n"
            f"👤 {user_name}\n"
            f"📑 Всего запросов: {stats['total']}\n"
            f"✅ Одобрено: {stats['approved']}\n"
            f"❌ Отклонено: {stats['rejected']}\n"
            f"⏳ Ожидает рассмотрения: {stats['pending']}\n\n"
            f"Используйте /timeoff_stats [дни] для изменения периода."
        )
    else:
        message = (
            f"📊 Статистика запросов на отгул\n\n"
            f"👤 {user_name}\n"
            f"ℹ️ Нет запросов на отгул за последние {days} дней.\n\n"
            f"Используйте /timeoff_stats [дни] для изменения периода."
        )
    
    update.message.reply_text(message)

def status_command(update: Update, context: CallbackContext):
    """Handle the /status command - allow user to set status"""
    keyboard = get_user_keyboard(update.effective_user.id)
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        "Выберите ваш статус:",
        reply_markup=reply_markup
    )

def handle_status_message(update: Update, context: CallbackContext):
    """Handle status messages from keyboard buttons"""
    if not update.message or not update.message.text:
        logger.error("Получен неверный формат сообщения со статусом")
        return
        
    message_text = update.message.text
    user_id = update.effective_user.id
    user_name = get_user_name_by_id(user_id) or update.effective_user.first_name
    
    # Обработка кнопки "Отпроситься" теперь осуществляется через отдельный обработчик в timeoff_requests.py
    if message_text == "📝 Отпроситься":
        # Мы не обрабатываем это здесь, т.к. есть отдельный обработчик
        return
    
    # Check if message is a status option
    status_map = {value: key for key, value in STATUS_OPTIONS.items()}
    status_key = status_map.get(message_text)
    
    if not status_key:
        return  # Not a status message
    
    # Save the status
    save_status(user_id, status_key)
    
    # Mark morning check as completed
    today_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
    update_morning_check(user_id, today_date, checked_in=True)
    
    # Check if user was tracking location
    location_tracking = context.chat_data.get(f"location_tracking_{user_id}", False)
    session_id = context.chat_data.get(f"location_session_{user_id}")
    
    # Respond based on status
    if status_key == "home":
        # User is going home, stop location tracking if active
        if location_tracking and session_id:
            # Mark location session as ended
            try:
                # If they sent a final location, use it for ending
                if update.message.location:
                    location = update.message.location
                    mark_session_ended(session_id, user_id, location.latitude, location.longitude)
                else:
                    # Just mark the last tracked location as end
                    mark_session_ended(session_id, user_id)
                
                # Clear tracking state
                context.chat_data[f"location_tracking_{user_id}"] = False
                context.chat_data[f"location_session_{user_id}"] = None
                
                update.message.reply_text(
                    f"Статус обновлен: {message_text}\n"
                    f"✅ Трансляция геопозиции остановлена.\n"
                    f"Хорошего вечера, {user_name}!"
                )
            except Exception as e:
                logger.error(f"Error ending location session: {e}")
                update.message.reply_text(
                    f"Статус обновлен: {message_text}\n"
                    f"⚠️ Ошибка при остановке трансляции геопозиции: {str(e)}\n"
                    f"Хорошего вечера, {user_name}!"
                )
        else:
            # No active location tracking
            update.message.reply_text(
                f"Статус обновлен: {message_text}\n"
                f"Хорошего вечера, {user_name}!"
            )
        
        # Пользователь закончил день - сохраняем этот факт
        # но НЕ генерируем отчет здесь, чтобы избежать дублирования с ежедневным отчетом
        logger.info(f"Пользователь {user_name} (ID: {user_id}) закончил день")
        
        # Завершаем все активные сессии отслеживания местоположения
        try:
            from database import get_active_location_sessions
            active_sessions = get_active_location_sessions(user_id)
            if active_sessions:
                for session_id in active_sessions:
                    mark_session_ended(session_id, user_id)
                    logger.info(f"Завершена активная сессия {session_id} для пользователя {user_name}")
        except Exception as e:
            logger.error(f"Ошибка при остановке трансляции геопозиции: {e}")
            # Продолжаем выполнение без остановки работы
        
        # Отправляем уведомление администратору о том, что пользователь закончил день
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"ℹ️ Пользователь {user_name} закончил день ({today_date})"
        )
    elif status_key == "night_shift_start":
        # User is starting night shift, add to night shift
        today_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
        tomorrow_date = (datetime.now(MOSCOW_TZ) + timedelta(days=1)).strftime('%Y-%m-%d')
        
        try:
            from models import add_night_shift
            add_night_shift(user_id, today_date, tomorrow_date)
            update.message.reply_text(
                f"Статус обновлен: {message_text}\n"
                f"✅ Вы добавлены в ночную смену с {today_date} по {tomorrow_date}.\n"
                f"Утренние оповещения будут отключены до следующих суток."
            )
        except Exception as e:
            logger.error(f"Error adding night shift: {e}")
            update.message.reply_text(
                f"Статус обновлен: {message_text}\n"
                f"⚠️ Ошибка при добавлении в ночную смену: {str(e)}"
            )
    
    elif status_key == "night_shift_end":
        # User is ending night shift
        # В этот момент мы можем удалить ночную смену из БД, 
        # но это не обязательно, так как проверка is_user_in_night_shift 
        # учитывает даты начала и конца смены
        today_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
        
        try:
            # Проверяем, действительно ли пользователь был в ночной смене
            if is_user_in_night_shift(user_id):
                # Отмечаем утреннюю проверку как выполненную, чтобы не беспокоить пользователя сегодня
                update_morning_check(user_id, today_date, checked_in=True)
                
                update.message.reply_text(
                    f"Статус обновлен: {message_text}\n"
                    f"✅ Ночная смена завершена. Утренние оповещения будут включены с завтрашнего дня."
                )
            else:
                update.message.reply_text(
                    f"Статус обновлен: {message_text}\n"
                    f"ℹ️ Информация: Вы не были отмечены в ночной смене."
                )
        except Exception as e:
            logger.error(f"Error handling night shift end: {e}")
            update.message.reply_text(
                f"Статус обновлен: {message_text}\n"
                f"⚠️ Ошибка при обработке окончания ночной смены: {str(e)}"
            )
    
    else:
        # For other statuses, just confirm
        update.message.reply_text(f"Статус обновлен: {message_text}")
    
    logger.info(f"User {user_id} set status to {status_key}")

def handle_location(update: Update, context: CallbackContext):
    """Handle location updates from users"""
    if not update.message or not update.message.location:
        # Проверяем, является ли это обновлением живой геолокации
        if update.edited_message and update.edited_message.location:
            message = update.edited_message
            is_live_location = True
            logger.info("Получено обновление живой геолокации")
        else:
            logger.error("Получен неверный формат сообщения с локацией")
            return
    else:
        message = update.message
        is_live_location = False
    
    user_id = message.from_user.id
    user_name = get_user_name_by_id(user_id) or message.from_user.first_name
    location = message.location
    
    # Инициализируем структуру chat_data для пользователя, если ее еще нет
    if user_id not in context.chat_data:
        context.chat_data[user_id] = {}
        context.chat_data[user_id]['movement_status'] = 'unknown'
        context.chat_data[user_id]['stationary_duration'] = 0
    
    # Получаем текущие координаты
    lat = location.latitude
    lon = location.longitude
    current_time = datetime.now()
    
    # Определяем перемещение пользователя
    location_type = 'intermediate'  # По умолчанию - промежуточная точка
    
    # Проверяем, есть ли предыдущее местоположение для сравнения
    if 'last_location' in context.chat_data[user_id]:
        prev_loc = context.chat_data[user_id]['last_location']
        prev_lat = prev_loc.get('latitude')
        prev_lon = prev_loc.get('longitude')
        prev_time_str = prev_loc.get('timestamp')
        
        if prev_lat and prev_lon and prev_time_str:
            # Расчет расстояния между точками
            from math import sin, cos, sqrt, atan2, radians
            
            R = 6371000  # Радиус Земли в метрах
            
            lat1 = radians(float(prev_lat))
            lon1 = radians(float(prev_lon))
            lat2 = radians(float(lat))
            lon2 = radians(float(lon))
            
            dlon = lon2 - lon1
            dlat = lat2 - lat1
            
            a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))
            
            distance = R * c  # Расстояние в метрах
            
            # Расчет времени между отметками
            prev_time = datetime.fromisoformat(prev_time_str)
            time_diff_seconds = (current_time - prev_time).total_seconds()
            
            # Определение статуса движения
            if distance < 10:  # Если переместился менее чем на 10 метров
                # Пользователь на месте или почти на месте
                context.chat_data[user_id]['stationary_duration'] += time_diff_seconds
                if context.chat_data[user_id]['stationary_duration'] > 300:  # 5 минут на месте
                    context.chat_data[user_id]['movement_status'] = 'stationary'
                    location_type = 'stationary'
                    
                    # Уведомляем админа, если пользователь на месте более 30 минут и это не первое уведомление
                    if context.chat_data[user_id]['stationary_duration'] > 1800 and not context.chat_data[user_id].get('admin_notified', False):
                        try:
                            from config import ADMIN_ID
                            context.bot.send_message(
                                chat_id=ADMIN_ID,
                                text=f"⚠️ Пользователь {user_name} находится на месте более 30 минут.\n"
                                     f"Координаты: {lat}, {lon}\n"
                                     f"<a href='https://maps.google.com/maps?q={lat},{lon}'>Посмотреть на карте</a>",
                                parse_mode='HTML'
                            )
                            context.chat_data[user_id]['admin_notified'] = True
                            logger.info(f"Отправлено уведомление админу о неподвижности пользователя {user_name}")
                        except Exception as e:
                            logger.error(f"Ошибка при отправке уведомления админу: {e}")
            else:
                # Пользователь в движении
                # Рассчитываем скорость в км/ч
                speed = (distance / time_diff_seconds) * 3.6 if time_diff_seconds > 0 else 0
                
                context.chat_data[user_id]['movement_status'] = 'moving'
                context.chat_data[user_id]['stationary_duration'] = 0
                context.chat_data[user_id]['admin_notified'] = False
                location_type = 'moving'
                
                # Добавляем данные о скорости
                context.chat_data[user_id]['speed'] = speed
                logger.info(f"Пользователь {user_name} в движении, скорость: {speed:.1f} км/ч, расстояние: {distance:.1f} м")
    
    # Сохраняем последнее местоположение в chat_data для обновления каждые 5 минут
    context.chat_data[user_id]['last_location'] = {
        'latitude': lat,
        'longitude': lon,
        'timestamp': current_time.isoformat(),
        'movement_status': context.chat_data[user_id].get('movement_status', 'unknown'),
        'speed': context.chat_data[user_id].get('speed', 0)
    }
    
    # Check if user just started sharing location (first point in a new session)
    start_new_session = False
    
    # Store user state for location sharing in chat_data
    if not context.chat_data.get(f"location_tracking_{user_id}"):
        start_new_session = True
        context.chat_data[f"location_tracking_{user_id}"] = True
    
    # Save location to database
    if start_new_session:
        # Create new session and mark this as start point
        session_id = save_location(user_id, lat, lon, location_type='start')
        context.chat_data[f"location_session_{user_id}"] = session_id
        
        if not is_live_location:
            message.reply_text(
                "✅ Трансляция геопозиции начата. Для остановки трансляции нажмите '🏠 Домой'."
            )
    else:
        # Continue existing session
        session_id = context.chat_data.get(f"location_session_{user_id}")
        save_location(user_id, lat, lon, session_id=session_id, location_type=location_type)
        
        if not is_live_location:
            message.reply_text("📍 Местоположение обновлено")
    
    # Mark morning check as completed
    today_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
    update_morning_check(user_id, today_date, checked_in=True)
    
    # Логируем с дополнительной информацией о движении
    movement_status = context.chat_data[user_id].get('movement_status', 'unknown')
    speed = context.chat_data[user_id].get('speed', 0)
    logger.info(f"Saved location for user {user_name} [{lat}, {lon}], status: {movement_status}, speed: {speed:.1f} км/ч")

def handle_admin_panel(update: Update, context: CallbackContext):
    """Handle admin panel button press"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        update.message.reply_text("У вас нет прав для выполнения этого действия.")
        return
    
    from utils import get_admin_keyboard
    
    # Send admin panel
    update.message.reply_text(
        "🔐 Панель администратора\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard()
    )

def handle_admin_callback(update: Update, context: CallbackContext):
    """Handle admin panel callback buttons"""
    if not update.callback_query:
        logger.error("Некорректный формат запроса callback")
        return
        
    query = update.callback_query
    query.answer()
    
    # Получаем callback data
    callback_data = query.data
    logger.info(f"Начало обработки admin_callback: {callback_data}")
    
    # Проверка наличия поля from_user в callback_query
    if not hasattr(query, 'from_user') or query.from_user is None:
        logger.error("Объект from_user отсутствует в callback_query")
        return
    
    user_id = query.from_user.id
    logger.info(f"User ID в admin_callback: {user_id}")
    
    # Check if user is admin
    from user_management import is_admin, get_admin_user_selector
    if not is_admin(user_id):
        logger.warning(f"Пользователь {user_id} не является администратором")
        query.edit_message_text("У вас нет прав для выполнения этого действия.")
        return
        
    logger.info(f"Пользователь {user_id} имеет права администратора, обрабатываем callback: {callback_data}")
    
    try:
        if callback_data == "admin_locate":
            # Show user selector for location tracking
            query.edit_message_text(
                "Выберите пользователя для просмотра местоположения:",
                reply_markup=get_admin_user_selector("locate_user")
            )
        
        elif callback_data == "admin_requests":
            # Show pending time-off requests
            from timeoff_requests import get_pending_timeoff_requests
            
            requests = get_pending_timeoff_requests()
            
            if not requests:
                query.edit_message_text("Нет заявок, ожидающих рассмотрения.")
                return
            
            query.edit_message_text("Загружаю список заявок...")
            
            # Use show_pending_timeoff_requests via a direct message
            context.bot.send_message(
                chat_id=user_id,
                text="Заявки, ожидающие рассмотрения:"
            )
            
            from timeoff_requests import show_pending_timeoff_requests
            show_pending_timeoff_requests(update, context)
        
        elif callback_data == "admin_report":
            # Предложить выбрать дату для отчета
            keyboard = [
                [InlineKeyboardButton("За сегодня", callback_data="report_date_today")],
                [InlineKeyboardButton("За вчера", callback_data="report_date_yesterday")],
                [InlineKeyboardButton("За 7 дней", callback_data="report_date_week")],
                [InlineKeyboardButton("Другая дата", callback_data="report_date_custom")],
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
            ]
            
            query.edit_message_text(
                "Выберите дату для отчета:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        elif callback_data == "report_date_today":
            # Отчет за сегодня - используем стандартную функцию
            today = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
            logger.info(f"Обработка запроса отчета за сегодня ({today})")
            
            # Сохраняем выбранную дату в контекст
            context.user_data['selected_report_date'] = today
            logger.info(f"Сохранена дата в контекст: {today}")
            
            try:
                # Показываем список пользователей, используя готовую функцию
                from user_management import get_admin_user_selector
                
                # Используем префикс report_user_date_ для callback данных
                user_selector = get_admin_user_selector("report_user_date")
                logger.info("Получена клавиатура с пользователями через get_admin_user_selector")
                
                # Добавляем кнопку Назад
                keyboard_buttons = user_selector.inline_keyboard
                keyboard_buttons.append([InlineKeyboardButton("🔙 Назад к выбору даты", callback_data="admin_report")])
                
                message_text = f"Выберите пользователя для отчета за {today}:"
                logger.info(f"Отправка сообщения: {message_text}")
                
                query.edit_message_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard_buttons)
                )
                logger.info("Сообщение с клавиатурой отправлено успешно")
            except Exception as e:
                logger.error(f"Ошибка при обработке запроса отчета за сегодня: {e}")
                query.edit_message_text(f"Произошла ошибка: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        elif callback_data == "report_date_yesterday":
            # Отчет за вчера
            yesterday = (datetime.now(MOSCOW_TZ) - timedelta(days=1)).strftime('%Y-%m-%d')
            logger.info(f"Обработка запроса отчета за вчера ({yesterday})")
            
            # Сохраняем выбранную дату в контекст
            context.user_data['selected_report_date'] = yesterday
            logger.info(f"Сохранена дата в контекст: {yesterday}")
            
            try:
                # Показываем список пользователей, используя готовую функцию
                from user_management import get_admin_user_selector
                
                # Используем префикс report_user_date_ для callback данных
                user_selector = get_admin_user_selector("report_user_date")
                logger.info("Получена клавиатура с пользователями через get_admin_user_selector")
                
                # Добавляем кнопку Назад
                keyboard_buttons = user_selector.inline_keyboard
                keyboard_buttons.append([InlineKeyboardButton("🔙 Назад к выбору даты", callback_data="admin_report")])
                
                message_text = f"Выберите пользователя для отчета за {yesterday}:"
                logger.info(f"Отправка сообщения: {message_text}")
                
                query.edit_message_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard_buttons)
                )
                logger.info("Сообщение с клавиатурой отправлено успешно")
            except Exception as e:
                logger.error(f"Ошибка при обработке запроса отчета за вчера: {e}")
                query.edit_message_text(f"Произошла ошибка: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        elif callback_data == "report_date_week":
            # Отчет за последние 7 дней
            today = datetime.now(MOSCOW_TZ)
            week_ago = today - timedelta(days=6)  # 7 дней включая сегодня
            
            today_str = today.strftime('%Y-%m-%d')
            week_ago_str = week_ago.strftime('%Y-%m-%d')
            
            logger.info(f"Обработка запроса недельного отчета ({week_ago_str} - {today_str})")
            
            # Сохраняем даты в контекст
            context.user_data['report_period_start'] = week_ago_str
            context.user_data['report_period_end'] = today_str
            context.user_data['report_type'] = 'week'
            
            try:
                # Показываем список пользователей, используя готовую функцию
                from user_management import get_admin_user_selector
                
                # Используем префикс report_user_week_ для callback данных
                user_selector = get_admin_user_selector("report_user_week")
                logger.info("Получена клавиатура с пользователями через get_admin_user_selector")
                
                # Добавляем кнопку Назад
                keyboard_buttons = user_selector.inline_keyboard
                keyboard_buttons.append([InlineKeyboardButton("🔙 Назад к выбору периода", callback_data="admin_report")])
                
                message_text = f"Выберите пользователя для отчета за период {week_ago_str} - {today_str}:"
                logger.info(f"Отправка сообщения: {message_text}")
                
                query.edit_message_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard_buttons)
                )
                logger.info("Сообщение с клавиатурой отправлено успешно")
            except Exception as e:
                logger.error(f"Ошибка при обработке запроса недельного отчета: {e}")
                query.edit_message_text(f"Произошла ошибка: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        elif callback_data == "report_date_custom":
            # Запрос конкретной даты
            # В Telegram нет встроенного календаря, поэтому попросим ввести дату вручную
            query.edit_message_text(
                "Для генерации отчета за определенную дату, пожалуйста, используйте команду:\n"
                "/report ГГГГ-ММ-ДД\n\n"
                "Пример: /report 2025-05-01",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_report")]])
            )
            
        elif callback_data == "admin_daily_reports":
            # Показываем меню выбора пользователя для генерации сегодняшнего отчета
            logger.info("Обработка запроса ежедневных отчетов")
            
            try:
                # Показываем список пользователей, используя готовую функцию
                from user_management import get_admin_user_selector
                
                # Используем префикс daily_report_user_ для callback данных
                user_selector = get_admin_user_selector("daily_report_user")
                logger.info("Получена клавиатура с пользователями через get_admin_user_selector")
                
                message_text = "Выберите пользователя для генерации отчета за сегодня:"
                logger.info(f"Отправка сообщения: {message_text}")
                
                query.edit_message_text(
                    message_text,
                    reply_markup=user_selector
                )
                logger.info("Сообщение с клавиатурой отправлено успешно")
            except Exception as e:
                logger.error(f"Ошибка при обработке запроса ежедневных отчетов: {e}")
                query.edit_message_text(f"Произошла ошибка: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        elif callback_data == "admin_shifts":
            # Manage night shifts
            query.edit_message_text(
                "Управление ночными сменами - функция в разработке"
            )
        elif callback_data == "admin_timeoff_stats":
            # Статистика отгулов для всех пользователей
            keyboard = []
            
            from models import get_all_users, get_timeoff_stats_for_user
            users = get_all_users()
            
            if not users:
                query.edit_message_text("Нет доступных пользователей для просмотра статистики отгулов.")
                return
            
            # Формируем сообщение со статистикой запросов на отгул для всех пользователей
            message = "📊 *Статистика запросов на отгул*\n\n"
            
            # Периоды для отображения статистики
            periods = [
                ("7 дней", 7),
                ("30 дней", 30),
                ("90 дней", 90),
                ("Все записи", 365)
            ]
            
            # Создаем клавиатуру с кнопками выбора периода
            for period_name, days in periods:
                button_text = f"За последние {period_name}" if period_name != "Все записи" else "Все записи"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"timeoff_stats_period_{days}")])
            
            # Добавляем кнопку возврата в главное меню
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])
            
            query.edit_message_text(
                "Выберите период для просмотра статистики отгулов:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        elif callback_data == "admin_users":
            # Управление пользователями
            from user_management import handle_users_management
            handle_users_management(update, context)
        
        elif callback_data == "admin_delete_user":
            # Удаление пользователя
            from user_management import handle_delete_user_selection
            handle_delete_user_selection(update, context)
            
        elif callback_data == "admin_change_rights":
            # Изменение прав пользователя
            from user_management import handle_change_rights_selection
            handle_change_rights_selection(update, context)
            
        elif callback_data == "admin_back":
            # Возврат в основное меню администратора
            from utils import get_admin_keyboard
            query.edit_message_text(
                "🔐 Панель администратора\n\n"
                "Выберите действие:",
                reply_markup=get_admin_keyboard()
            )
        elif callback_data.startswith("timeoff_stats_period_"):
            # Обработка выбора периода для статистики отгулов
            try:
                # Извлекаем количество дней из callback_data
                days = int(callback_data.split("_")[-1])
                
                from models import get_all_users, get_timeoff_stats_for_user
                users = get_all_users()
                
                if not users:
                    query.edit_message_text("Нет доступных пользователей для просмотра статистики отгулов.")
                    return
                
                # Формируем сообщение со статистикой запросов на отгул для всех пользователей
                period_text = f"за последние {days} дней" if days < 365 else "за всё время"
                message = f"📊 *Статистика запросов на отгул {period_text}*\n\n"
                
                # Собираем статистику по каждому пользователю
                total_stats = {"total": 0, "approved": 0, "rejected": 0, "pending": 0}
                user_stats = []
                
                # Логирование для отладки
                logger.info(f"Собираем статистику по {len(users)} пользователям за {days} дней")
                
                for user_id, user_name, is_admin in users:
                    # Логирование каждого пользователя
                    logger.info(f"Получаем статистику для пользователя: {user_name} (ID: {user_id})")
                    
                    try:
                        stats = get_timeoff_stats_for_user(user_id, days=days)
                        
                        # Логирование статистики
                        logger.info(f"Статистика для {user_name}: {stats}")
                        
                        # Если у пользователя есть запросы, добавляем его в статистику
                        if stats['total'] > 0:
                            user_stats.append((user_name, stats))
                            
                            # Обновляем общую статистику
                            total_stats['total'] += stats['total']
                            total_stats['approved'] += stats['approved']
                            total_stats['rejected'] += stats['rejected']
                            total_stats['pending'] += stats['pending']
                    except Exception as e:
                        logger.error(f"Ошибка при получении статистики отгулов для {user_name}: {e}")
                
                # Логирование общей статистики
                logger.info(f"Общая статистика: {total_stats}")
                
                # Добавляем общую статистику
                message += f"*Общая статистика:*\n"
                message += f"📑 Всего запросов: {total_stats['total']}\n"
                message += f"✅ Одобрено: {total_stats['approved']}\n"
                message += f"❌ Отклонено: {total_stats['rejected']}\n"
                message += f"⏳ Ожидает рассмотрения: {total_stats['pending']}\n\n"
                
                # Добавляем статистику по каждому пользователю
                if user_stats:
                    message += f"*Статистика по пользователям:*\n"
                    for user_name, stats in user_stats:
                        message += f"👤 {user_name}:\n"
                        message += f"  - Всего: {stats['total']}, "
                        message += f"Одобрено: {stats['approved']}, "
                        message += f"Отклонено: {stats['rejected']}, "
                        message += f"Ожидает: {stats['pending']}\n"
                else:
                    message += "Нет запросов на отгул за указанный период."
                
                # Создаем клавиатуру для возврата назад
                keyboard = [
                    [InlineKeyboardButton("🔙 Назад к выбору периода", callback_data="admin_timeoff_stats")],
                    [InlineKeyboardButton("🔙 Главное меню", callback_data="admin_back")]
                ]
                
                query.edit_message_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Ошибка при формировании статистики отгулов: {e}")
                query.edit_message_text(f"Ошибка при формировании статистики отгулов: {str(e)}")
        else:
            logger.warning(f"Неизвестная команда callback: {callback_data}")
            query.edit_message_text("Неизвестная команда. Пожалуйста, повторите действие.")
    except Exception as e:
        logger.error(f"Ошибка при обработке callback: {e}")
        try:
            query.edit_message_text("Произошла ошибка при обработке запроса. Пожалуйста, повторите действие.")
        except Exception as e2:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e2}")

def handle_locate_user_callback(update: Update, context: CallbackContext):
    """Handle callback when admin selects a user to locate"""
    if not update.callback_query:
        logger.error("Некорректный формат запроса callback")
        return
        
    query = update.callback_query
    query.answer()
    
    if not hasattr(query, 'from_user') or query.from_user is None:
        logger.error("Объект from_user отсутствует в callback_query")
        return
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этого действия.")
        return
    
    try:
        # Извлекаем ID пользователя из данных callback
        callback_data = query.data
        logger.info(f"Обработка запроса местоположения пользователя: {callback_data}")
        
        # Данные должны быть в формате locate_user_USERID
        parts = callback_data.split("_")
        if len(parts) != 3 or not parts[2].isdigit():
            logger.error(f"Некорректный формат callback для местоположения: {callback_data}")
            query.edit_message_text("Ошибка: некорректный формат ID пользователя")
            return
        
        user_id = int(parts[2])
        user_name = get_user_name_by_id(user_id)
        
        if not user_name:
            user_name = f"Пользователь {user_id}"
        
        # Получаем последние координаты пользователя
        from database import get_user_locations
        locations = get_user_locations(user_id, hours_limit=24)
        
        if not locations:
            query.edit_message_text(f"Нет данных о местоположении для {user_name} за последние 24 часа.")
            return
        
        # Получаем самое последнее местоположение
        latest_location = locations[-1]
        
        # Обрабатываем разные форматы данных из get_user_locations
        if len(latest_location) >= 3:  # Минимум нужны lat, lon, timestamp
            if len(latest_location) >= 5:  # Полный формат с 5 полями (id, lat, lon, timestamp, loc_type)
                loc_id, lat, lon, timestamp, loc_type = latest_location
            elif len(latest_location) >= 4:  # Формат с 4 полями
                loc_id, lat, lon, timestamp = latest_location
                loc_type = 'intermediate'
            else:
                lat, lon, timestamp = latest_location[:3]
                loc_type = 'intermediate'
            
            # Преобразуем в числовой формат, если нужно
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
                        logger.error(f"Не удалось распарсить timestamp: {e}")
                        timestamp = datetime.now(MOSCOW_TZ)
            
            # Преобразуем в московское время, если не оно
            if hasattr(timestamp, 'astimezone'):
                timestamp = timestamp.astimezone(MOSCOW_TZ)
            
            time_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            
            # Создаем сообщение с местоположением
            message = f"📍 Последнее местоположение для {user_name}:\n"
            message += f"• Широта: {lat:.6f}\n"
            message += f"• Долгота: {lon:.6f}\n"
            message += f"• Время: {time_str}\n"
            message += f"• Тип: {loc_type}\n"
            message += f"\n<a href='https://maps.google.com/maps?q={lat},{lon}'>Смотреть на Google Maps</a>"
            
            # Отправляем сообщение с кнопкой для запроса отчета
            keyboard = [
                [InlineKeyboardButton("📊 Сгенерировать отчет", callback_data=f"report_user_{user_id}")],
                [InlineKeyboardButton("🗺️ Сгенерировать карту", callback_data=f"daily_report_user_{user_id}")]
            ]
            
            query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            
            logger.info(f"Отправлено местоположение пользователя {user_name} [{lat}, {lon}]")
        else:
            query.edit_message_text(f"Данные о местоположении для {user_name} некорректные.")
            logger.error(f"Некорректный формат данных локации: {latest_location}")
    except Exception as e:
        logger.error(f"Ошибка при обработке местоположения пользователя: {e}")
        query.edit_message_text(f"Произошла ошибка при получении данных о местоположении: {str(e)}")

def handle_report_callback(update: Update, context: CallbackContext):
    """Handle report generation for a selected user"""
    if not update.callback_query:
        logger.error("Некорректный формат запроса callback")
        return
        
    query = update.callback_query
    query.answer()
    
    # Проверка наличия поля from_user в callback_query
    if not hasattr(query, 'from_user') or query.from_user is None:
        logger.error("Объект from_user отсутствует в callback_query")
        return
    
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этого действия.")
        return
    
    try:
        # Отладочная информация
        callback_data = query.data
        logger.info(f"Received callback data: {callback_data}")
        
        # Для отчетов с выбранной датой (report_user_date_XXX)
        if callback_data.startswith("report_user_date_"):
            # Пытаемся получить ID пользователя
            prefix = "report_user_date_"
            user_id_str = callback_data[len(prefix):]
            try:
                user_id = int(user_id_str)
                # Получаем выбранную дату из контекста пользователя
                selected_date = context.user_data.get('selected_report_date')
                if not selected_date:
                    # Если дата не найдена, используем сегодняшнюю
                    selected_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
                is_daily_report = False
                logger.info(f"Успешно извлечен ID пользователя для отчета с датой: {user_id}, дата: {selected_date}")
            except ValueError:
                logger.error(f"Не удается преобразовать ID пользователя '{user_id_str}' в число")
                query.edit_message_text(f"Ошибка: некорректный ID пользователя ({user_id_str})")
                return
        # Для недельных отчетов (report_user_week_XXX)
        elif callback_data.startswith("report_user_week_"):
            # Пытаемся получить ID пользователя
            prefix = "report_user_week_"
            user_id_str = callback_data[len(prefix):]
            try:
                user_id = int(user_id_str)
                # Получаем выбранные даты из контекста пользователя
                start_date = context.user_data.get('report_period_start')
                end_date = context.user_data.get('report_period_end')
                
                if not start_date or not end_date:
                    # Если даты не найдены, используем 7 дней включая сегодняшний
                    today = datetime.now(MOSCOW_TZ)
                    week_ago = today - timedelta(days=6)
                    end_date = today.strftime('%Y-%m-%d')
                    start_date = week_ago.strftime('%Y-%m-%d')
                
                is_daily_report = False
                is_weekly_report = True
                logger.info(f"Успешно извлечен ID пользователя для недельного отчета: {user_id}, период: {start_date} - {end_date}")
            except ValueError:
                logger.error(f"Не удается преобразовать ID пользователя '{user_id_str}' в число")
                query.edit_message_text(f"Ошибка: некорректный ID пользователя ({user_id_str})")
                return
        # Для отчетов за сегодня (daily_report_user_XXX)
        elif callback_data.startswith("daily_report_user_"):
            # Пытаемся получить ID пользователя
            prefix = "daily_report_user_"
            user_id_str = callback_data[len(prefix):]
            try:
                user_id = int(user_id_str)
                selected_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')  # Сегодняшняя дата
                is_daily_report = True
                is_weekly_report = False
                logger.info(f"Успешно извлечен ID пользователя для daily_report: {user_id}")
            except ValueError:
                logger.error(f"Не удается преобразовать ID пользователя '{user_id_str}' в число")
                query.edit_message_text(f"Ошибка: некорректный ID пользователя ({user_id_str})")
                return
        # Для обычных отчетов (report_user_XXX)
        elif callback_data.startswith("report_user_"):
            # Пытаемся получить ID пользователя
            prefix = "report_user_"
            user_id_str = callback_data[len(prefix):]
            try:
                user_id = int(user_id_str)
                selected_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')  # Сегодняшняя дата
                is_daily_report = False
                logger.info(f"Успешно извлечен ID пользователя для обычного отчета: {user_id}")
            except ValueError:
                logger.error(f"Не удается преобразовать ID пользователя '{user_id_str}' в число")
                query.edit_message_text(f"Ошибка: некорректный ID пользователя ({user_id_str})")
                return
        else:
            logger.error(f"Неизвестный формат callback для отчетов: {callback_data}")
            query.edit_message_text("Ошибка: неизвестный формат запроса")
            return
            
        user_name = get_user_name_by_id(user_id)
        
        if not user_name:
            user_name = f"Пользователь {user_id}"
        
        query.edit_message_text(f"Генерация отчета для {user_name}...")
        
        # Инициализируем переменные по умолчанию
        is_weekly_report = False
        report_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')  # Текущая дата по умолчанию
        report_file = None
        
        # В зависимости от типа отчета используем соответствующие даты и методы
        if callback_data.startswith("report_user_week_"):
            # Недельный отчет
            is_weekly_report = True
            if 'report_period_start' in context.user_data and 'report_period_end' in context.user_data:
                start_date = context.user_data['report_period_start']
                end_date = context.user_data['report_period_end']
            else:
                # Если даты не сохранены в контексте, используем значения по умолчанию
                today = datetime.now(MOSCOW_TZ)
                week_ago = today - timedelta(days=6)
                end_date = today.strftime('%Y-%m-%d')
                start_date = week_ago.strftime('%Y-%m-%d')
                
            period_str = f"{start_date} - {end_date}"
            query.edit_message_text(f"Генерация недельного отчета для {user_name} за период {period_str}...")
            
            # TODO: В будущем реализовать генерацию отчетов за период
            # Пока просто используем дату конца периода (сегодняшний день)
            report_date = end_date
            report_file = generate_csv_report(user_id, date=report_date)
            logger.info(f"Сгенерирован недельный отчет (пока только за дату {report_date}): {report_file}")
        elif callback_data.startswith("report_user_date_") and 'selected_report_date' in context.user_data:
            # Обычный отчет за один день из выбранной даты
            report_date = context.user_data['selected_report_date']
            
            # Информационное сообщение о генерации отчета
            query.edit_message_text(f"Генерация отчета для {user_name} за {report_date}...")
            
            # Генерируем отчет (всегда используем CSV-формат)
            report_file = generate_csv_report(user_id, date=report_date)
        else:
            # Резервный вариант - используем сегодняшнюю дату
            report_date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
            logger.warning(f"Не найдена выбранная дата, используем текущую: {report_date}")
            
            # Информационное сообщение о генерации отчета
            query.edit_message_text(f"Генерация отчета для {user_name} за {report_date}...")
            
            # Генерируем отчет (всегда используем CSV-формат)
            report_file = generate_csv_report(user_id, date=report_date)
        
        is_html = False
        
        if os.path.exists(report_file):
            # Определяем расширение файла и MIME-тип
            file_ext = "html" if is_html else "csv"
            mime_type = "text/html" if is_html else "text/csv"
            
            # Send report
            with open(report_file, 'rb') as f:
                context.bot.send_document(
                    chat_id=query.from_user.id,
                    document=f,
                    filename=f"report_{user_name}_{report_date}.{file_ext}",
                    caption=f"📊 Отчет для {user_name} ({report_date})"
                )
            
            
            # Карта будет создана ниже после обработки всех точек

# Clean up
            os.remove(report_file)
            
            # Also generate map if locations available
            # Завершаем все активные сессии, чтобы получить самые актуальные данные
            try:
                from database import get_active_location_sessions, mark_session_ended
                active_sessions = get_active_location_sessions(user_id)
                if active_sessions:
                    for session_id in active_sessions:
                        mark_session_ended(session_id, user_id)
                        logger.info(f"Завершена активная сессия {session_id} для отчета пользователя {user_name}")
            except Exception as e:
                logger.error(f"Ошибка при закрытии активных сессий: {e}")
                # Продолжаем выполнение, даже если возникла ошибка с сессиями
            
            # Получаем местоположения за выбранную дату
            from database import get_today_locations_for_user
            locations = get_today_locations_for_user(user_id, date=report_date)
            
            if locations:
                # Format locations for map
                map_locations = []
                logger.info(f"Получено {len(locations)} точек для карты пользователя {user_name} за {report_date}")
                
                for loc in locations:
                    try:
                        # Обрабатываем разные форматы данных из get_user_locations
                        if len(loc) >= 5:  # Полный формат с 5 полями (id, lat, lon, timestamp, loc_type)
                            loc_id, lat, lon, timestamp, loc_type = loc
                        elif len(loc) >= 4:  # Формат с 4 полями
                            loc_id, lat, lon, timestamp = loc
                            loc_type = 'intermediate'
                        elif len(loc) >= 3:  # Минимальный формат
                            lat, lon, timestamp = loc[:3]
                            loc_type = 'intermediate'
                        else:
                            logger.warning(f"Недостаточно данных в локации: {loc}")
                            continue
                        
                        # Проверяем корректность координат
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
                        logger.error(f"Ошибка при обработке координат для карты: {e}, данные: {loc}")
                        continue
                
                # Создаем карту с помощью улучшенного метода create_direct_map, который работает даже при отсутствии точек
                logger.info(f"Создание карты через create_direct_map для пользователя {user_id} за {report_date}")
                map_file = create_direct_map(user_id, report_date)
                
                if map_file and os.path.exists(map_file):
                    with open(map_file, 'rb') as f:
                        context.bot.send_document(
                            chat_id=query.from_user.id,
                            document=f,
                            filename=os.path.basename(map_file),
                            caption=f"🗺️ Карта перемещений {user_name} ({report_date})"
                        )
                    logger.info(f"Карта успешно отправлена для {user_name}: {map_file}")
                else:
                    logger.warning(f"Не удалось создать карту для {user_name}")
                    context.bot.send_message(
                        chat_id=query.from_user.id,
                        text=f"⚠️ Не удалось создать карту перемещений для {user_name}"
                    )
            
            query.edit_message_text(f"Отчет для {user_name} сгенерирован и отправлен.")
        else:
            query.edit_message_text(f"Не удалось сгенерировать отчет для {user_name}. Возможно, нет данных за сегодня.")
    except Exception as e:
        logger.error(f"Ошибка при генерации отчета: {e}")
        try:
            query.edit_message_text(f"Ошибка при генерации отчета: {str(e)}")
        except Exception as e2:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e2}")

def setup_bot():
    """Set up and configure the bot"""
    # Initialize the database
    init_db()
    
    # Load user mappings from file, but don't update the database
    # Это позволит сохранить изменения, внесенные через веб-интерфейс
    load_user_mappings_from_file(update_db=False)
    
    # Create the Updater
    updater = Updater(TOKEN)
    
    # Get the dispatcher
    dispatcher = updater.dispatcher
    
    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("status", status_command))
    dispatcher.add_handler(CommandHandler("timeoff_stats", timeoff_stats_command))
    
    # Command to manually generate and send reports
    def generate_reports_command(update: Update, context: CallbackContext):
        """Handle the /generate_reports command - manually generate and send reports"""
        user_id = update.effective_user.id
        
        # Check if user is admin
        if not is_admin(user_id):
            update.message.reply_text("У вас нет прав для выполнения этого действия.")
            return
        
        update.message.reply_text("Запущена генерация ежедневных отчетов...")
        
        try:
            from scheduled_tasks import daily_report_task
            daily_report_task(context, force=True)
            update.message.reply_text("✅ Отчеты сгенерированы и отправлены.")
        except Exception as e:
            logger.error(f"Ошибка при генерации отчетов: {e}")
            update.message.reply_text(f"❌ Ошибка при генерации отчетов: {str(e)}")
    
    dispatcher.add_handler(CommandHandler("generate_reports", generate_reports_command))
    
    # Обработчик команды /report с датой
    def report_command(update: Update, context: CallbackContext):
        """Handle the /report YYYY-MM-DD command - generate report for a specific date"""
        user_id = update.effective_user.id
        
        # Check if user is admin
        if not is_admin(user_id):
            update.message.reply_text("У вас нет прав для выполнения этого действия.")
            return
        
        # Проверяем, есть ли аргументы (дата)
        if not context.args or len(context.args) < 1:
            update.message.reply_text(
                "Пожалуйста, укажите дату в формате:\n"
                "/report ГГГГ-ММ-ДД\n\n"
                "Пример: /report 2025-05-01"
            )
            return
        
        # Получаем дату из аргументов
        report_date = context.args[0]
        logger.info(f"Команда /report с датой: {report_date}")
        
        # Проверяем формат даты
        try:
            datetime.strptime(report_date, '%Y-%m-%d')
        except ValueError:
            update.message.reply_text(
                "Некорректный формат даты. Используйте формат ГГГГ-ММ-ДД.\n"
                "Пример: /report 2025-05-01"
            )
            return
        
        # Сохраняем дату в контекст пользователя
        context.user_data['selected_report_date'] = report_date
        
        # Показываем список пользователей для выбора
        try:
            from user_management import get_admin_user_selector
            
            # Создаем клавиатуру выбора пользователя
            user_selector = get_admin_user_selector("report_user_date")
            logger.info(f"Создана клавиатура выбора пользователя для отчета за {report_date}")
            
            # Отправляем сообщение с клавиатурой
            update.message.reply_text(
                f"Выберите пользователя для отчета за {report_date}:",
                reply_markup=user_selector
            )
            logger.info("Отправлено сообщение с клавиатурой выбора пользователя")
        except Exception as e:
            logger.error(f"Ошибка при обработке команды /report: {e}")
            update.message.reply_text(f"Произошла ошибка: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    dispatcher.add_handler(CommandHandler("report", report_command))
    
    # Admin commands from user_management
    from user_management import register_admin_handlers
    register_admin_handlers(dispatcher)
    
    # Time-off request handlers
    register_timeoff_handlers(dispatcher)
    
    # Handle locations
    dispatcher.add_handler(MessageHandler(Filters.location, handle_location))
    
    # Handle status messages from keyboard
    dispatcher.add_handler(MessageHandler(
        Filters.text & ~Filters.command & Filters.regex(f"^({'|'.join(STATUS_OPTIONS.values())})$"), 
        handle_status_message
    ))
    
    # Handle admin panel button
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex("^👤 Панель администратора$"),
        handle_admin_panel
    ))
    
    # Callback handlers
    # Обрабатываем все callback запросы, выводим для отладки их содержимое
    def debug_callback_handler(update: Update, context: CallbackContext):
        """Временный обработчик для отладки callback данных"""
        query = update.callback_query
        callback_data = query.data if query else "No callback data"
        logger.info(f"DEBUG - Получен callback: {callback_data}")
        
        # Передаем обработку дальше соответствующим обработчикам
        if callback_data.startswith("admin_"):
            # Обработка команд админ-панели
            handle_admin_callback(update, context)
        elif callback_data.startswith("report_date_"):
            # Обработка выбора даты для отчетов
            logger.info(f"Обработка выбора даты для отчетов: {callback_data}")
            handle_admin_callback(update, context)
        elif callback_data.startswith("timeoff_stats_period_"):
            # Обработка выбора периода для статистики отгулов
            logger.info(f"Обработка выбора периода для статистики отгулов: {callback_data}")
            handle_admin_callback(update, context)
        elif callback_data.startswith("report_user_") or callback_data.startswith("daily_report_user_") or callback_data.startswith("report_user_date_") or callback_data.startswith("report_user_week_"):
            # Дополнительная проверка данных
            parts = callback_data.split("_")
            logger.info(f"DEBUG - Части callback: {parts}")
            
            if len(parts) >= 3 and parts[-1].isdigit():
                logger.info(f"Передаю callback {callback_data} в handle_report_callback")
                handle_report_callback(update, context)
            else:
                query.answer()
                query.edit_message_text(f"Ошибка: некорректный формат ID пользователя в callback: {callback_data}")
                logger.error(f"Некорректный формат callback данных: {callback_data}")
        elif callback_data.startswith("locate_user_"):
            # Обработка выбора пользователя для просмотра местоположения
            handle_locate_user_callback(update, context)
        elif callback_data.startswith("delete_user_") or callback_data.startswith("confirm_delete_"):
            # Обработка запросов на удаление пользователя
            from user_management import handle_delete_user_callback, handle_confirm_delete_user
            if callback_data.startswith("delete_user_"):
                handle_delete_user_callback(update, context)
            else:
                handle_confirm_delete_user(update, context)
        elif callback_data.startswith("grant_admin_") or callback_data.startswith("revoke_admin_"):
            # Обработка запросов на изменение прав администратора
            from user_management import handle_admin_rights_change
            handle_admin_rights_change(update, context)
    
    # Используем один обработчик для отладки
    dispatcher.add_handler(CallbackQueryHandler(debug_callback_handler))
    
    # Set up scheduled tasks
    job_queue = updater.job_queue
    
    # Morning check job (runs every 10 minutes)
    job_queue.run_repeating(morning_check_task, interval=600, first=0)
    
    # Reset morning checks job (runs daily at 00:01)
    from datetime import time as dt_time
    job_queue.run_daily(reset_morning_checks_task, time=dt_time(0, 1))
    
    # Daily report job (runs daily at 17:30)
    from config import DAILY_REPORT_TIME
    report_time = dt_time(DAILY_REPORT_TIME[0], DAILY_REPORT_TIME[1])
    job_queue.run_daily(daily_report_task, time=report_time)
    logger.info(f"Scheduled daily report task at {report_time}")
    
    # Interval location tracking job (runs every 5 minutes)
    from scheduled_tasks import location_interval_task, check_user_activity
    job_queue.run_repeating(location_interval_task, interval=300, first=60)
    logger.info("Scheduled location interval task every 5 minutes")
    
    # User activity monitoring job (runs every 5 minutes, with a delay to not overlap with location task)
    job_queue.run_repeating(check_user_activity, interval=300, first=120)
    logger.info("Scheduled user activity monitoring task every 5 minutes")
    
    return updater

def run_polling():
    """Run the bot in polling mode"""
    updater = setup_bot()
    
    # Start the Bot in polling mode
    updater.start_polling()
    
    # Run the bot until you press Ctrl-C
    updater.idle()

def run_webhook():
    """Run the bot in webhook mode"""
    updater = setup_bot()
    
    # Set the webhook
    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook" if WEBHOOK_URL else None
    )
    
    # Run the bot until you press Ctrl-C
    updater.idle()

def main():
    """Main function to run the bot"""
    logger.info(f"Starting WorkerTracker bot in {BOT_MODE} mode")
    
    if BOT_MODE.lower() == "webhook":
        run_webhook()
    else:
        run_polling()

if __name__ == "__main__":
    main()
