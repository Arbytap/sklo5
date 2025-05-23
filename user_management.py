import logging
import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import CallbackContext, ConversationHandler
from models import (
    add_or_update_user_mapping, get_user_name_by_id, get_user_id_by_name, 
    get_all_users, delete_user, set_user_admin_status
)
from database import get_user_locations, DATABASE_FILE
from config import ADMIN_ID, ADMIN_IDS, MOSCOW_TZ

# Состояния для диалога добавления пользователя
ADD_USER_ID, ADD_USER_NAME, ADD_USER_ADMIN_STATUS = range(3)

logger = logging.getLogger(__name__)

def is_admin(user_id):
    """Check if a user is an admin"""
    return user_id == ADMIN_ID

def load_user_mappings_from_file(filename=None, update_db=False):
    """Load user ID to name mappings from the database
    
    Args:
        filename: Ignored parameter for backward compatibility
        update_db: Ignored parameter for backward compatibility
    """
    mappings = {}
    try:
        # Получаем всех пользователей напрямую из базы данных
        users = get_all_users()
        for user in users:
            user_id, full_name = user[0], user[1]
            mappings[user_id] = full_name
        
        logger.info(f"Loaded {len(mappings)} user mappings from database")
        return mappings
    except Exception as e:
        logger.error(f"Error loading user mappings from database: {e}")
        return {}

def get_admin_user_selector(callback_prefix="locate_user"):
    """Create an inline keyboard with all users for admin selection"""
    users = get_all_users()
    
    # Добавляем отладочную информацию
    logger.info(f"Создание клавиатуры выбора пользователя с префиксом '{callback_prefix}'")
    logger.info(f"Получено {len(users)} пользователей из базы данных")
    
    # Create a list of buttons, each row contains 1 user
    keyboard = []
    for user in users:
        if len(user) >= 2:  # Убедимся, что есть хотя бы user_id и full_name
            user_id, full_name = user[0], user[1]
            callback = f"{callback_prefix}_{user_id}"
            logger.info(f"Добавляем кнопку: '{full_name}' -> '{callback}'")
            keyboard.append([InlineKeyboardButton(
                full_name, callback_data=callback
            )])
    
    return InlineKeyboardMarkup(keyboard)

def get_formatted_user_info(user_id):
    """Get formatted user information including name"""
    user_name = get_user_name_by_id(user_id)
    if user_name:
        return f"{user_name} (ID: {user_id})"
    else:
        return f"Пользователь ID: {user_id}"

def find_user_location(user_id, context: CallbackContext):
    """Find the most recent location of a user and format it for display"""
    locations = get_user_locations(user_id, hours_limit=24)
    
    if not locations:
        return "Данные о местоположении пользователя за последние 24 часа не найдены."
    
    # Get the most recent location
    most_recent = locations[-1]
    
    # Обрабатываем разные форматы данных из get_user_locations
    if len(most_recent) >= 5:  # Полный формат с 5 полями (id, lat, lon, timestamp, loc_type)
        location_id, lat, lon, timestamp, loc_type = most_recent
    elif len(most_recent) >= 4:  # Формат с 4 полями
        location_id, lat, lon, timestamp = most_recent
        loc_type = 'промежуточная'
    elif len(most_recent) >= 3:  # Минимальный формат
        lat, lon, timestamp = most_recent[:3]
        loc_type = 'промежуточная'
    else:
        return "Некорректный формат данных о местоположении."
    
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
                return f"Ошибка преобразования времени: {e}"
    
    # Преобразуем в московское время, если не оно
    if hasattr(timestamp, 'astimezone'):
        try:
            # Преобразуем timestamp в московское время
            timestamp = timestamp.astimezone(MOSCOW_TZ)
        except Exception as e:
            logger.error(f"Ошибка при преобразовании в московское время: {e}")
    
    user_name = get_user_name_by_id(user_id) or f"Пользователь ID: {user_id}"
    
    # Получаем статус пользователя - используем новую функцию get_user_latest_status
    from database import get_user_latest_status
    status_data = get_user_latest_status(user_id)
    current_status = "Неизвестно"
    
    if status_data:
        current_status = status_data[0]  # Берем текущий статус из кортежа (status, timestamp)
        # Проверяем, если статус на английском, переводим его
        if current_status == "home":
            current_status = "Домой"
        elif current_status == "office":
            current_status = "В офисе"
        elif current_status == "sick":
            current_status = "Болею"
        elif current_status == "vacation":
            current_status = "В отпуске"
        elif current_status == "night_shift":
            current_status = "В ночь"
        elif current_status == "after_night":
            current_status = "С ночи"
        elif current_status.lower() == "stationary":
            current_status = "На месте"
        elif current_status.lower() == "moving":
            current_status = "В движении"
    
    # Определяем иконку для статуса
    status_icon = "🔵"  # По умолчанию
    if current_status == "В офисе":
        status_icon = "🏢"
    elif current_status == "Домой":
        status_icon = "🏠"
    elif current_status == "Болею":
        status_icon = "🤒"
    elif current_status == "В отпуске":
        status_icon = "🏖️"
    elif current_status == "В ночь":
        status_icon = "🌙"
    elif current_status == "С ночи":
        status_icon = "🌅"
    
    # Format the message
    message = f"📍 Последнее местоположение {user_name}:\n"
    message += f"• Статус: {status_icon} {current_status}\n"
    message += f"• Широта: {lat:.6f}\n"
    message += f"• Долгота: {lon:.6f}\n"
    message += f"• Время: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
    message += f"• Тип: {loc_type}\n"
    message += f"\n<a href='https://maps.google.com/maps?q={lat},{lon}'>Посмотреть на Google Maps</a>"
    
    return message

def handle_admin_command(update: Update, context: CallbackContext):
    """Handle admin commands"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id != ADMIN_ID:
        update.message.reply_text("У вас нет прав для выполнения этого действия.")
        return
    
    from utils import get_admin_keyboard
    
    # Send admin panel
    update.message.reply_text(
        "🔐 Панель администратора\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard()
    )

def handle_locate_command(update: Update, context: CallbackContext):
    """Handle locate command to find users"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id != ADMIN_ID:
        update.message.reply_text("У вас нет прав для выполнения этого действия.")
        return
    
    # Send user selector
    update.message.reply_text(
        "Выберите пользователя для просмотра местоположения:",
        reply_markup=get_admin_user_selector("locate_user")
    )

def handle_locate_callback(update: Update, context: CallbackContext):
    """Handle callback when admin selects a user to locate"""
    query = update.callback_query
    query.answer()
    
    # Extract user ID from callback data
    user_id = int(query.data.split('_')[2])
    
    # Get location information
    location_message = find_user_location(user_id, context)
    
    # Send message with location info
    query.edit_message_text(
        text=location_message,
        parse_mode='HTML'
    )

def start_add_user_flow(update: Update, context: CallbackContext):
    """Начать процесс добавления нового пользователя"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return ConversationHandler.END
    
    # Отображаем инструкцию по добавлению пользователя
    query.edit_message_text(
        "👤 *Добавление нового пользователя*\n\n"
        "Введите ID пользователя Telegram (числовой):",
        parse_mode="Markdown"
    )
    
    return ADD_USER_ID

def handle_user_id_input(update: Update, context: CallbackContext):
    """Обработать ввод ID пользователя"""
    logger.info("Получено сообщение с ID пользователя")
    
    if not update.message:
        logger.error("Отсутствует сообщение в обработчике handle_user_id_input")
        return ConversationHandler.END
    
    user_id_text = update.message.text.strip()
    logger.info(f"Получен ID пользователя: {user_id_text}")
    
    # Проверяем, что введён числовой ID
    try:
        user_id = int(user_id_text)
        context.user_data['new_user_id'] = user_id
        logger.info(f"ID пользователя успешно преобразован в число: {user_id}")
        
        # Проверяем, существует ли пользователь с таким ID
        existing_name = get_user_name_by_id(user_id)
        if existing_name:
            logger.info(f"Пользователь с ID {user_id} уже существует: {existing_name}")
            update.message.reply_text(
                f"⚠️ Пользователь с ID {user_id} уже существует в системе.\n"
                f"Имя: {existing_name}\n\n"
                "Хотите обновить данные этого пользователя? Введите новое полное имя "
                "или /cancel для отмены."
            )
        else:
            logger.info(f"Новый пользователь с ID {user_id}, запрашиваем имя")
            update.message.reply_text(
                f"ID {user_id} принят. Теперь введите полное имя пользователя (ФИО):"
            )
        
        return ADD_USER_NAME
    except ValueError as e:
        logger.error(f"Ошибка при преобразовании ID пользователя: {e}")
        update.message.reply_text(
            "❌ Ошибка: ID пользователя должен быть числовым.\n"
            "Пожалуйста, введите корректный ID (только цифры) или /cancel для отмены."
        )
        return ADD_USER_ID

def handle_user_name_input(update: Update, context: CallbackContext):
    """Обработать ввод имени пользователя"""
    logger.info("Получено сообщение с именем пользователя")
    
    if not update.message:
        logger.error("Отсутствует сообщение в обработчике handle_user_name_input")
        return ConversationHandler.END
    
    full_name = update.message.text.strip()
    logger.info(f"Получено имя пользователя: {full_name}")
    
    # Проверяем, что имя не пустое и не команда
    if not full_name or full_name.startswith('/'):
        logger.warning(f"Получено некорректное имя: {full_name}")
        update.message.reply_text(
            "❌ Имя не может быть пустым или командой.\n"
            "Введите полное имя (ФИО) или /cancel для отмены."
        )
        return ADD_USER_NAME
    
    # Сохраняем имя в контексте
    context.user_data['new_user_name'] = full_name
    logger.info(f"Имя {full_name} сохранено в контексте")
    
    # Спрашиваем о правах администратора
    keyboard = ReplyKeyboardMarkup(
        [["Да", "Нет"]], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    
    update.message.reply_text(
        f"Имя принято: {full_name}\n\n"
        "Сделать пользователя администратором?",
        reply_markup=keyboard
    )
    logger.info("Отправлен запрос на назначение прав администратора")
    
    return ADD_USER_ADMIN_STATUS

def handle_admin_status_input(update: Update, context: CallbackContext):
    """Обработать выбор статуса администратора"""
    logger.info("Получено сообщение с выбором статуса администратора")
    
    if not update.message:
        logger.error("Отсутствует сообщение в обработчике handle_admin_status_input")
        return ConversationHandler.END
    
    admin_choice = update.message.text.strip().lower()
    logger.info(f"Получен выбор статуса администратора: {admin_choice}")
    
    user_id = context.user_data.get('new_user_id')
    full_name = context.user_data.get('new_user_name')
    
    logger.info(f"Данные из контекста: user_id={user_id}, full_name={full_name}")
    
    if not user_id or not full_name:
        logger.error("Отсутствуют данные пользователя в контексте")
        update.message.reply_text(
            "❌ Произошла ошибка: не удалось получить данные пользователя.\n"
            "Пожалуйста, начните процесс заново.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    # Определяем статус администратора
    is_admin_status = True if admin_choice == "да" else False
    logger.info(f"Установлен статус администратора: {is_admin_status}")
    
    try:
        # Сохраняем пользователя в базе данных
        success = add_or_update_user_mapping(user_id, full_name, is_admin=is_admin_status)
        
        if success:
            logger.info(f"Пользователь {full_name} (ID: {user_id}) успешно добавлен в БД")
            admin_text = "с правами администратора" if is_admin_status else "без прав администратора"
            update.message.reply_text(
                f"✅ Пользователь успешно добавлен!\n\n"
                f"ID: {user_id}\n"
                f"Имя: {full_name}\n"
                f"Статус: {admin_text}",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            logger.error(f"Ошибка при сохранении пользователя {full_name} (ID: {user_id}) в БД")
            update.message.reply_text(
                "❌ Произошла ошибка при сохранении пользователя.\n"
                "Пожалуйста, попробуйте позже.",
                reply_markup=ReplyKeyboardRemove()
            )
    except Exception as e:
        logger.error(f"Исключение при сохранении пользователя: {e}")
        update.message.reply_text(
            "❌ Произошла ошибка при сохранении пользователя.\n"
            "Пожалуйста, попробуйте позже.",
            reply_markup=ReplyKeyboardRemove()
        )
    
    return ConversationHandler.END

def cancel_add_user(update: Update, context: CallbackContext):
    """Отмена процесса добавления пользователя"""
    logger.info("Получена команда отмены добавления пользователя")
    
    if not update.message:
        logger.error("Отсутствует сообщение в обработчике cancel_add_user")
        return ConversationHandler.END
    
    update.message.reply_text(
        "❌ Операция добавления пользователя отменена.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Очищаем данные
    cleaned_keys = []
    if 'new_user_id' in context.user_data:
        del context.user_data['new_user_id']
        cleaned_keys.append('new_user_id')
    if 'new_user_name' in context.user_data:
        del context.user_data['new_user_name']
        cleaned_keys.append('new_user_name')
    
    logger.info(f"Очищены данные из контекста: {', '.join(cleaned_keys)}")
    
    return ConversationHandler.END

def get_users_management_keyboard():
    """Создать клавиатуру для управления пользователями"""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user")],
        [InlineKeyboardButton("🗑️ Удалить пользователя", callback_data="admin_delete_user")],
        [InlineKeyboardButton("🔄 Изменить права", callback_data="admin_change_rights")],
        [InlineKeyboardButton("👁️ Просмотреть всех пользователей", callback_data="admin_view_users")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def handle_users_management(update: Update, context: CallbackContext):
    """Обработать запрос на управление пользователями"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    query.edit_message_text(
        "👥 *Управление пользователями*\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=get_users_management_keyboard()
    )

def handle_view_users(update: Update, context: CallbackContext):
    """Показать список всех пользователей"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    # Получаем список пользователей
    users = get_all_users()
    
    if not users:
        query.edit_message_text(
            "📋 *Список пользователей*\n\n"
            "Пользователи не найдены.",
            parse_mode="Markdown",
            reply_markup=get_users_management_keyboard()
        )
        return
    
    # Формируем сообщение со списком пользователей
    message = "📋 *Список пользователей*\n\n"
    
    for i, user in enumerate(users, 1):
        if len(user) >= 3:  # ID, имя, статус админа
            user_id, full_name, is_admin_status = user[0], user[1], user[2]
            admin_text = "✓" if is_admin_status else "✗"
            message += f"{i}. {full_name} (ID: {user_id}) - Админ: {admin_text}\n"
        elif len(user) >= 2:  # ID, имя
            user_id, full_name = user[0], user[1]
            message += f"{i}. {full_name} (ID: {user_id})\n"
    
    # Добавляем кнопку возврата
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_users")]]
    
    query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_delete_user_selection(update: Update, context: CallbackContext):
    """Показать список пользователей для удаления"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    query.edit_message_text(
        "🗑️ *Удаление пользователя*\n\n"
        "Выберите пользователя для удаления:",
        parse_mode="Markdown",
        reply_markup=get_admin_user_selector("delete_user")
    )

def handle_delete_user_callback(update: Update, context: CallbackContext):
    """Обработать выбор пользователя для удаления"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    # Получаем ID пользователя из callback_data
    callback_data = query.data
    user_id = int(callback_data.split('_')[-1])
    
    # Получаем имя пользователя
    user_name = get_user_name_by_id(user_id)
    
    if not user_name:
        query.edit_message_text(
            "⚠️ Пользователь не найден.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
            ]])
        )
        return
    
    # Спрашиваем подтверждение на удаление
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{user_id}"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data="admin_users")
        ]
    ]
    
    query.edit_message_text(
        f"⚠️ *Подтверждение удаления*\n\n"
        f"Вы действительно хотите удалить пользователя:\n"
        f"*{user_name}* (ID: {user_id})?\n\n"
        f"⚠️ Это действие также удалит все связанные данные пользователя!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_confirm_delete_user(update: Update, context: CallbackContext):
    """Обработать подтверждение удаления пользователя"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    # Получаем ID пользователя из callback_data
    callback_data = query.data
    user_id = int(callback_data.split('_')[-1])
    
    # Получаем имя пользователя перед удалением
    user_name = get_user_name_by_id(user_id)
    
    if not user_name:
        query.edit_message_text(
            "⚠️ Пользователь не найден.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
            ]])
        )
        return
    
    # Удаляем пользователя
    try:
        success = delete_user(user_id)
        
        if success:
            query.edit_message_text(
                f"✅ Пользователь *{user_name}* (ID: {user_id}) успешно удален.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
                ]])
            )
            logger.info(f"Удален пользователь: {user_name} (ID: {user_id})")
        else:
            query.edit_message_text(
                f"❌ Ошибка при удалении пользователя.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
                ]])
            )
            logger.error(f"Ошибка при удалении пользователя с ID: {user_id}")
    except Exception as e:
        query.edit_message_text(
            f"❌ Ошибка при удалении пользователя: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
            ]])
        )
        logger.error(f"Исключение при удалении пользователя с ID {user_id}: {e}")

def handle_change_rights_selection(update: Update, context: CallbackContext):
    """Показать список пользователей для изменения прав"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    query.edit_message_text(
        "🔄 *Изменение прав пользователя*\n\n"
        "Выберите пользователя для изменения прав:",
        parse_mode="Markdown",
        reply_markup=get_admin_user_selector("change_rights")
    )

def handle_change_rights_callback(update: Update, context: CallbackContext):
    """Обработать выбор пользователя для изменения прав"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    # Получаем ID пользователя из callback_data
    callback_data = query.data
    user_id = int(callback_data.split('_')[-1])
    
    # Получаем данные пользователя
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        cursor.execute('SELECT full_name, is_admin FROM user_mapping WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            query.edit_message_text(
                "⚠️ Пользователь не найден.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
                ]])
            )
            return
        
        full_name, is_admin_status = result
        
        # Создаем кнопки в зависимости от текущего статуса
        if is_admin_status:
            action_text = "Отменить права администратора"
            action_callback = f"revoke_admin_{user_id}"
            current_status = "Администратор ✓"
        else:
            action_text = "Назначить администратором"
            action_callback = f"grant_admin_{user_id}"
            current_status = "Обычный пользователь ✗"
        
        keyboard = [
            [InlineKeyboardButton(action_text, callback_data=action_callback)],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_users")]
        ]
        
        query.edit_message_text(
            f"🔄 *Изменение прав пользователя*\n\n"
            f"Пользователь: *{full_name}* (ID: {user_id})\n"
            f"Текущий статус: {current_status}\n\n"
            f"Выберите действие:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        query.edit_message_text(
            f"❌ Ошибка при получении данных пользователя: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
            ]])
        )
        logger.error(f"Исключение при получении данных пользователя с ID {user_id}: {e}")

def handle_admin_rights_change(update: Update, context: CallbackContext):
    """Обработать изменение прав администратора"""
    query = update.callback_query
    query.answer()
    
    # Проверяем права администратора
    if not is_admin(query.from_user.id):
        query.edit_message_text("У вас нет прав для выполнения этой операции.")
        return
    
    # Получаем данные из callback_data
    callback_data = query.data
    action_type, user_id = callback_data.split('_')[0], int(callback_data.split('_')[-1])
    
    # Определяем новый статус
    is_admin_status = True if action_type == "grant" else False
    
    # Получаем имя пользователя
    user_name = get_user_name_by_id(user_id)
    
    if not user_name:
        query.edit_message_text(
            "⚠️ Пользователь не найден.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
            ]])
        )
        return
    
    # Обновляем права пользователя
    try:
        success = set_user_admin_status(user_id, is_admin_status)
        
        if success:
            status_text = "назначен администратором" if is_admin_status else "лишен прав администратора"
            query.edit_message_text(
                f"✅ Пользователь *{user_name}* (ID: {user_id}) успешно {status_text}.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
                ]])
            )
            logger.info(f"Изменены права пользователя {user_name} (ID: {user_id}): админ={is_admin_status}")
        else:
            query.edit_message_text(
                f"❌ Ошибка при изменении прав пользователя.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
                ]])
            )
            logger.error(f"Ошибка при изменении прав пользователя с ID: {user_id}")
    except Exception as e:
        query.edit_message_text(
            f"❌ Ошибка при изменении прав пользователя: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="admin_users")
            ]])
        )
        logger.error(f"Исключение при изменении прав пользователя с ID {user_id}: {e}")

def register_admin_handlers(dispatcher):
    """Register all admin command handlers"""
    from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, Filters
    
    # Базовые обработчики команд
    dispatcher.add_handler(CommandHandler("admin", handle_admin_command))
    dispatcher.add_handler(CommandHandler("locate", handle_locate_command))
    dispatcher.add_handler(CallbackQueryHandler(handle_locate_callback, pattern="^locate_user_"))
    
    # Обработчики для управления пользователями
    dispatcher.add_handler(CallbackQueryHandler(handle_users_management, pattern="^admin_users$"))
    dispatcher.add_handler(CallbackQueryHandler(handle_view_users, pattern="^admin_view_users$"))
    
    # Обработчики для удаления пользователей
    dispatcher.add_handler(CallbackQueryHandler(handle_delete_user_selection, pattern="^admin_delete_user$"))
    dispatcher.add_handler(CallbackQueryHandler(handle_delete_user_callback, pattern="^delete_user_"))
    dispatcher.add_handler(CallbackQueryHandler(handle_confirm_delete_user, pattern="^confirm_delete_"))
    
    # Обработчики для изменения прав пользователей
    dispatcher.add_handler(CallbackQueryHandler(handle_change_rights_selection, pattern="^admin_change_rights$"))
    dispatcher.add_handler(CallbackQueryHandler(handle_change_rights_callback, pattern="^change_rights_"))
    dispatcher.add_handler(CallbackQueryHandler(handle_admin_rights_change, pattern="^grant_admin_"))
    dispatcher.add_handler(CallbackQueryHandler(handle_admin_rights_change, pattern="^revoke_admin_"))
    
    # Добавляем обработчик для диалога добавления пользователя
    add_user_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_user_flow, pattern="^admin_add_user$")],
        states={
            ADD_USER_ID: [MessageHandler(Filters.text & ~Filters.command, handle_user_id_input)],
            ADD_USER_NAME: [MessageHandler(Filters.text & ~Filters.command, handle_user_name_input)],
            ADD_USER_ADMIN_STATUS: [MessageHandler(Filters.text & ~Filters.command, handle_admin_status_input)]
        },
        fallbacks=[CommandHandler("cancel", cancel_add_user)],
        # Не используем per_message=True, чтобы избежать конфликта с MessageHandler
        allow_reentry=True  # Разрешить повторный вход в диалог
    )
    
    # Важно: обработчик диалога должен быть добавлен раньше, чем другие обработчики
    dispatcher.add_handler(add_user_conv_handler)
