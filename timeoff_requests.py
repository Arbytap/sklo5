import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from models import (
    create_timeoff_request, get_pending_timeoff_requests,
    update_timeoff_request, get_timeoff_requests_for_user,
    get_user_name_by_id
)
from user_management import get_formatted_user_info
from config import ADMIN_ID

logger = logging.getLogger(__name__)

# States for conversation handler
TYPING_REASON = 1

def start_timeoff_request(update: Update, context: CallbackContext):
    """Start the time off request conversation"""
    user = update.effective_user
    
    # Проверка на наличие context и инициализация user_data при необходимости
    if context is None:
        logger.error("CallbackContext is None в start_timeoff_request")
        update.message.reply_text(
            "Произошла ошибка при обработке вашей заявки. Пожалуйста, попробуйте снова через бота."
        )
        return ConversationHandler.END
    
    # Инициализация пустого запроса
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    context.user_data['timeoff_request'] = {}  # Initialize an empty request
    
    update.message.reply_text(
        "Пожалуйста, напишите причину для отсутствия:"
    )
    
    return TYPING_REASON

def process_timeoff_reason(update: Update, context: CallbackContext):
    """Process the reason for time off and submit the request"""
    reason = update.message.text
    user = update.effective_user
    username = user.username or str(user.id)
    
    # Проверка на наличие context и его атрибутов
    if context is None:
        logger.error("CallbackContext is None в process_timeoff_reason")
        update.message.reply_text(
            "Произошла ошибка при обработке вашей заявки. Пожалуйста, попробуйте снова через бота."
        )
        return ConversationHandler.END
    
    try:
        # Create the request in the database
        request_id = create_timeoff_request(user.id, username, reason)
        
        # Notify the user
        update.message.reply_text(
            f"Ваша заявка на отсутствие отправлена администратору и ожидает рассмотрения.\n\n"
            f"Причина: {reason}"
        )
        
        # Notify the admin
        user_name = get_user_name_by_id(user.id) or username
        
        # Create inline keyboard for admin to approve/reject
        keyboard = [
            [
                InlineKeyboardButton("✅ Согласовать", callback_data=f"approve_timeoff_{request_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_timeoff_{request_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        admin_message = (
            f"📋 Новая заявка на отсутствие от {user_name}:\n\n"
            f"Причина: {reason}\n\n"
            f"Выберите действие:"
        )
        
        # Проверяем наличие бота в контексте
        if not hasattr(context, 'bot') or context.bot is None:
            logger.error("Объект bot отсутствует в context")
            update.message.reply_text(
                "Произошла ошибка при отправке уведомления администратору. Заявка создана, "
                "но администратор может не получить уведомление."
            )
            return ConversationHandler.END
        
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"Error processing time off reason: {e}")
        update.message.reply_text(
            "Произошла ошибка при обработке вашей заявки. Пожалуйста, попробуйте снова."
        )
        return ConversationHandler.END

def cancel_timeoff_request(update: Update, context: CallbackContext):
    """Cancel the time off request conversation"""
    update.message.reply_text("Запрос отменен.")
    return ConversationHandler.END

def handle_timeoff_response(update: Update, context: CallbackContext):
    """Handle admin response to a time off request"""
    if not update.callback_query:
        logger.error("Некорректный формат запроса callback в handle_timeoff_response")
        return
        
    query = update.callback_query
    query.answer()
    
    # Проверка наличия поля from_user в callback_query
    if not hasattr(query, 'from_user') or query.from_user is None:
        logger.error("Объект from_user отсутствует в callback_query в handle_timeoff_response")
        return
    
    admin_id = query.from_user.id
    
    # Check if the user is admin
    if admin_id != ADMIN_ID:
        query.edit_message_text(
            "У вас нет прав для выполнения этого действия."
        )
        return
    
    # Parse callback data
    if not query.data:
        logger.error("Отсутствует query.data в callback")
        query.edit_message_text("Ошибка в формате запроса.")
        return
        
    try:
        data = query.data.split('_')
        if len(data) < 3:
            logger.error(f"Некорректный формат данных callback: {query.data}")
            query.edit_message_text("Ошибка в формате запроса.")
            return
            
        action = data[0]  # "approve" or "reject"
        request_id = int(data[2])  # request_id
    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка при разборе данных callback: {e}, данные: {query.data}")
        query.edit_message_text("Ошибка в формате запроса.")
        return
    
    # Update the request in the database
    status = "approved" if action == "approve" else "rejected"
    user_id, username = update_timeoff_request(request_id, status, admin_id)
    
    if user_id is None:
        query.edit_message_text(
            "Ошибка: Заявка не найдена или уже обработана."
        )
        return
    
    # Get user's full name
    user_name = get_user_name_by_id(user_id) or username
    
    # Update the admin message
    query.edit_message_text(
        f"Заявка на отсутствие от {user_name} была {'согласована' if status == 'approved' else 'отклонена'}."
    )
    
    # Notify the user
    status_text = "согласована" if status == "approved" else "отклонена"
    user_message = f"Ваша заявка на отсутствие была {status_text} администратором."
    
    # Проверяем наличие бота в контексте
    if context is None or not hasattr(context, 'bot') or context.bot is None:
        logger.error(f"Объект bot отсутствует в context при уведомлении пользователя {user_id}")
        return
    
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=user_message
        )
    except Exception as e:
        logger.error(f"Error sending notification to user {user_id}: {e}")

def show_my_timeoff_requests(update: Update, context: CallbackContext):
    """Show all time off requests for the current user"""
    user = update.effective_user
    
    requests = get_timeoff_requests_for_user(user.id)
    
    if not requests:
        update.message.reply_text("У вас нет заявок на отсутствие.")
        return
    
    message = "📋 Ваши заявки на отсутствие:\n\n"
    
    for req_id, reason, request_time, status, response_time in requests:
        # Convert status to Russian
        status_ru = {
            "pending": "⏳ Ожидает рассмотрения",
            "approved": "✅ Согласовано",
            "rejected": "❌ Отклонено"
        }.get(status, status)
        
        # Format the message
        message += f"Заявка #{req_id}:\n"
        message += f"• Причина: {reason}\n"
        message += f"• Статус: {status_ru}\n"
        message += f"• Дата запроса: {datetime.fromisoformat(request_time).strftime('%Y-%m-%d %H:%M')}\n"
        
        if response_time and response_time != "None":
            message += f"• Дата ответа: {datetime.fromisoformat(response_time).strftime('%Y-%m-%d %H:%M')}\n"
        
        message += "\n"
    
    update.message.reply_text(message)

def show_pending_timeoff_requests(update: Update, context: CallbackContext):
    """Show all pending time off requests for admin"""
    user = update.effective_user
    
    # Check if the user is admin
    if user.id != ADMIN_ID:
        update.message.reply_text("У вас нет прав для выполнения этого действия.")
        return
    
    requests = get_pending_timeoff_requests()
    
    if not requests:
        update.message.reply_text("Нет заявок, ожидающих рассмотрения.")
        return
    
    for req_id, user_id, username, reason, request_time in requests:
        # Get user's full name
        user_name = get_user_name_by_id(user_id) or username
        
        # Create inline keyboard for admin to approve/reject
        keyboard = [
            [
                InlineKeyboardButton("✅ Согласовать", callback_data=f"approve_timeoff_{req_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_timeoff_{req_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            f"📋 Заявка #{req_id} от {user_name}:\n\n"
            f"• Причина: {reason}\n"
            f"• Дата запроса: {datetime.fromisoformat(request_time).strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Выберите действие:"
        )
        
        update.message.reply_text(
            text=message,
            reply_markup=reply_markup
        )

def register_timeoff_handlers(dispatcher):
    """Register all timeoff request related handlers"""
    from telegram.ext import CommandHandler, MessageHandler, Filters, CallbackQueryHandler
    
    # Create conversation handler for timeoff requests
    # Note: We don't register the handler for message "📝 Отпроситься" here because
    # that's handled in the main handle_status_message function which calls start_timeoff_request
    # We need to explicitly register a command handler for '/request'
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('request', start_timeoff_request)],
        states={
            TYPING_REASON: [MessageHandler(Filters.text & ~Filters.command, process_timeoff_reason)],
        },
        fallbacks=[CommandHandler('cancel', cancel_timeoff_request)]
    )
    
    # Register separate conversation handler for messages
    # This specifically handles the "📝 Отпроситься" button
    timeoff_msg_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex('^📝 Отпроситься$'), start_timeoff_request)],
        states={
            TYPING_REASON: [MessageHandler(Filters.text & ~Filters.command, process_timeoff_reason)],
        },
        fallbacks=[CommandHandler('cancel', cancel_timeoff_request)]
    )
    
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(timeoff_msg_handler)  # Add the new handler
    dispatcher.add_handler(CommandHandler('myrequests', show_my_timeoff_requests))
    dispatcher.add_handler(CommandHandler('requests', show_pending_timeoff_requests))
    dispatcher.add_handler(CallbackQueryHandler(handle_timeoff_response, pattern='^(approve|reject)_timeoff_'))
