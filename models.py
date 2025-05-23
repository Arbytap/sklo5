import sqlite3
import logging
from datetime import datetime
from config import DATABASE_FILE, MOSCOW_TZ

logger = logging.getLogger(__name__)

def add_or_update_user_mapping(user_id, full_name, is_admin=None):
    """Add or update user mapping in the database
    
    Args:
        user_id: Telegram user ID
        full_name: User's full name
        is_admin: Boolean flag for admin status, None to keep current value
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        # Проверим, существует ли пользователь
        cursor.execute('SELECT is_admin FROM user_mapping WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result:
            # Пользователь существует, обновляем информацию
            logger.info(f"Пользователь с ID {user_id} существует, обновляем данные")
            
            if is_admin is None:
                # Сохраняем текущий статус администратора
                cursor.execute('''
                    UPDATE user_mapping 
                    SET full_name = ? 
                    WHERE user_id = ?
                ''', (full_name, user_id))
                logger.info(f"Обновили имя для пользователя {user_id}, сохранили права администратора")
            else:
                # Обновляем статус администратора
                cursor.execute('''
                    UPDATE user_mapping 
                    SET full_name = ?, is_admin = ? 
                    WHERE user_id = ?
                ''', (full_name, int(is_admin), user_id))
                logger.info(f"Обновили имя и права администратора для пользователя {user_id}")
        else:
            # Пользователь не существует, добавляем нового
            logger.info(f"Пользователь с ID {user_id} не существует, создаем нового")
            
            if is_admin is None:
                # По умолчанию не админ
                cursor.execute('''
                    INSERT INTO user_mapping (user_id, full_name, is_admin)
                    VALUES (?, ?, 0)
                ''', (user_id, full_name))
                logger.info(f"Создан новый пользователь {user_id} без прав администратора")
            else:
                # Устанавливаем явно указанный статус администратора
                cursor.execute('''
                    INSERT INTO user_mapping (user_id, full_name, is_admin)
                    VALUES (?, ?, ?)
                ''', (user_id, full_name, int(is_admin)))
                logger.info(f"Создан новый пользователь {user_id} с правами администратора: {is_admin}")
        
        conn.commit()
        logger.info(f"User mapping updated for user ID {user_id}, name: {full_name}, admin: {is_admin}")
        return True
    except Exception as e:
        logger.error(f"Error updating user mapping: {e}")
        conn.rollback()  # Выполняем откат изменений при ошибке
        return False
    finally:
        conn.close()

def get_user_name_by_id(user_id):
    """Get user's full name by user ID"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT full_name FROM user_mapping WHERE user_id = ?
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

def get_user_id_by_name(full_name):
    """Get user ID by full name"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id FROM user_mapping WHERE full_name = ?
    ''', (full_name,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

def get_all_users():
    """Get all users from the mapping table"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, full_name, is_admin FROM user_mapping ORDER BY full_name
    ''')
    
    users = cursor.fetchall()
    conn.close()
    
    return users

def delete_user(user_id):
    """Delete a user from the mapping table
    
    Note: This also deletes related data due to foreign key constraints.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    # Enable foreign key support
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли пользователь
        cursor.execute('SELECT 1 FROM user_mapping WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            logger.warning(f"Попытка удалить несуществующего пользователя с ID {user_id}")
            return False
        
        # Сначала удаляем все связанные записи вручную, т.к. внешние ключи могут быть не включены
        # Удаляем записи из status_history
        cursor.execute('DELETE FROM status_history WHERE user_id = ?', (user_id,))
        logger.info(f"Удалено записей из status_history: {cursor.rowcount}")
        
        # Удаляем записи из location_history
        cursor.execute('DELETE FROM location_history WHERE user_id = ?', (user_id,))
        logger.info(f"Удалено записей из location_history: {cursor.rowcount}")
        
        # Удаляем записи из morning_checks
        cursor.execute('DELETE FROM morning_checks WHERE user_id = ?', (user_id,))
        logger.info(f"Удалено записей из morning_checks: {cursor.rowcount}")
        
        # Удаляем записи из night_shifts
        cursor.execute('DELETE FROM night_shifts WHERE user_id = ?', (user_id,))
        logger.info(f"Удалено записей из night_shifts: {cursor.rowcount}")
        
        # Удаляем записи из timeoff_requests
        cursor.execute('DELETE FROM timeoff_requests WHERE user_id = ?', (user_id,))
        logger.info(f"Удалено записей из timeoff_requests: {cursor.rowcount}")
        
        # Теперь удаляем самого пользователя
        cursor.execute('''
            DELETE FROM user_mapping WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        rows_affected = cursor.rowcount
        logger.info(f"User ID {user_id} deleted. Rows affected: {rows_affected}")
        return rows_affected > 0
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        conn.rollback()  # Откатываем изменения при ошибке
        return False
    finally:
        conn.close()

def set_user_admin_status(user_id, is_admin):
    """Set or remove admin status for a user
    
    Args:
        user_id: Telegram user ID
        is_admin: Boolean flag for admin status
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли пользователь
        cursor.execute('SELECT 1 FROM user_mapping WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            logger.warning(f"Попытка изменить права администратора для несуществующего пользователя с ID {user_id}")
            return False
            
        cursor.execute('''
            UPDATE user_mapping SET is_admin = ? WHERE user_id = ?
        ''', (1 if is_admin else 0, user_id))
        
        conn.commit()
        logger.info(f"Admin status for user ID {user_id} set to {is_admin}")
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error setting admin status for user {user_id}: {e}")
        conn.rollback()  # Откатываем изменения при ошибке
        return False
    finally:
        conn.close()

def record_morning_check(user_id, check_date, checked_in=False):
    """Record morning check for a user"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO morning_checks (user_id, date, checked_in, notified, admin_notified)
            VALUES (?, ?, ?, 0, 0)
        ''', (user_id, check_date, checked_in))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error recording morning check: {e}")
        return False
    finally:
        conn.close()

def update_morning_check(user_id, check_date, checked_in=True):
    """Update morning check status for a user"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли запись
        cursor.execute('''
            SELECT id FROM morning_checks 
            WHERE user_id = ? AND date = ?
        ''', (user_id, check_date))
        
        if cursor.fetchone():
            # Обновляем существующую запись
            cursor.execute('''
                UPDATE morning_checks 
                SET checked_in = ? 
                WHERE user_id = ? AND date = ?
            ''', (checked_in, user_id, check_date))
        else:
            # Создаем новую запись
            cursor.execute('''
                INSERT INTO morning_checks (user_id, date, checked_in)
                VALUES (?, ?, ?)
            ''', (user_id, check_date, checked_in))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating morning check: {e}")
        return False
    finally:
        conn.close()

def update_morning_check_notification(user_id, check_date, notified=False, admin_notified=False):
    """Update notification status for morning check"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли запись
        cursor.execute('''
            SELECT id FROM morning_checks 
            WHERE user_id = ? AND date = ?
        ''', (user_id, check_date))
        
        if cursor.fetchone():
            # Обновляем существующую запись
            cursor.execute('''
                UPDATE morning_checks 
                SET notified = ?, admin_notified = ? 
                WHERE user_id = ? AND date = ?
            ''', (notified, admin_notified, user_id, check_date))
        else:
            # Создаем новую запись
            cursor.execute('''
                INSERT INTO morning_checks (user_id, date, notified, admin_notified)
                VALUES (?, ?, ?, ?)
            ''', (user_id, check_date, notified, admin_notified))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating morning check notification: {e}")
        return False
    finally:
        conn.close()

def get_unchecked_users_for_morning(check_date):
    """Get users who haven't checked in for morning"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        # First ensure all users have a record for today
        cursor.execute('''
            SELECT user_id FROM user_mapping
        ''')
        all_users = cursor.fetchall()
        
        for (user_id,) in all_users:
            cursor.execute('''
                INSERT OR IGNORE INTO morning_checks (user_id, date, checked_in)
                VALUES (?, ?, 0)
            ''', (user_id, check_date))
        
        conn.commit()
        
        # Then get all unchecked users
        cursor.execute('''
            SELECT mc.user_id, um.full_name, mc.notified, mc.admin_notified
            FROM morning_checks mc
            JOIN user_mapping um ON mc.user_id = um.user_id
            WHERE mc.date = ? AND mc.checked_in = 0
            ORDER BY um.full_name
        ''', (check_date,))
        
        unchecked_users = cursor.fetchall()
        return unchecked_users
    except Exception as e:
        logger.error(f"Error getting unchecked users: {e}")
        return []
    finally:
        conn.close()

def is_user_in_night_shift(user_id):
    """Check if a user is currently in night shift"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    today = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
    
    try:
        cursor.execute('''
            SELECT COUNT(*) FROM night_shifts
            WHERE user_id = ? AND start_time <= ? AND end_time >= ?
        ''', (user_id, today, today))
        
        count = cursor.fetchone()[0]
        return count > 0
    except Exception as e:
        logger.error(f"Error checking night shift: {e}")
        return False
    finally:
        conn.close()

def add_night_shift(user_id, start_date, end_date):
    """Add a night shift schedule for a user"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO night_shifts (user_id, start_time, end_time)
            VALUES (?, ?, ?)
        ''', (user_id, start_date, end_date))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding night shift: {e}")
        return False
    finally:
        conn.close()

def create_timeoff_request(user_id, username, reason):
    """Create a new time-off request"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        # Добавляем расширенное логирование для отладки
        logger.info(f"Создание запроса на отгул: пользователь={user_id} ({username}), причина='{reason}'")
        
        # Автоматически добавляем текущее время
        from datetime import datetime
        from config import MOSCOW_TZ
        now = datetime.now(MOSCOW_TZ).isoformat()
        
        cursor.execute('''
            INSERT INTO timeoff_requests (user_id, username, reason, request_time)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, reason, now))
        
        conn.commit()
        request_id = cursor.lastrowid
        logger.info(f"Запрос на отгул успешно создан: ID={request_id}")
        return request_id
    except Exception as e:
        logger.error(f"Ошибка при создании запроса на отгул: {e}")
        # Добавляем полный трейс для отладки
        import traceback
        logger.error(f"Трейс ошибки: {traceback.format_exc()}")
        return None
    finally:
        conn.close()

def get_pending_timeoff_requests():
    """Get all pending time-off requests"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id, user_id, username, reason, request_time
            FROM timeoff_requests
            WHERE status = 'pending'
            ORDER BY request_time
        ''')
        
        requests = cursor.fetchall()
        return requests
    except Exception as e:
        logger.error(f"Error getting pending time-off requests: {e}")
        return []
    finally:
        conn.close()

def get_timeoff_requests_for_user(user_id):
    """Get all time-off requests for a specific user"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id, reason, request_time, status, response_time
            FROM timeoff_requests
            WHERE user_id = ?
            ORDER BY request_time DESC
        ''', (user_id,))
        
        requests = cursor.fetchall()
        return requests
    except Exception as e:
        logger.error(f"Error getting user time-off requests: {e}")
        return []
    finally:
        conn.close()
        
def get_timeoff_stats_for_user(user_id, date=None, days=30):
    """Получить статистику запросов на отгул для пользователя
    
    Args:
        user_id: ID пользователя
        date: Дата в формате строки 'YYYY-MM-DD', если нужны данные за определенный период
        days: Количество дней назад для фильтрации (если date не указана)
    
    Returns:
        Словарь со статистикой: {
            'total': общее количество запросов,
            'approved': количество одобренных запросов,
            'rejected': количество отклоненных запросов,
            'pending': количество ожидающих рассмотрения
        }
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Логирование входных параметров для отладки
    logger.info(f"get_timeoff_stats_for_user: user_id={user_id}, date={date}, days={days}")
    
    # Создаем фильтр по дате
    date_filter = ""
    params = [user_id]
    
    if date:
        # Фильтр по конкретной дате
        date_start = f"{date} 00:00:00"
        date_end = f"{date} 23:59:59"
        date_filter = "AND request_time BETWEEN ? AND ?"
        params.extend([date_start, date_end])
    elif days > 0:
        # Фильтр по количеству дней
        import datetime
        
        today = datetime.datetime.now(MOSCOW_TZ)
        past_date = today - datetime.timedelta(days=days)
        past_date_str = past_date.strftime('%Y-%m-%d %H:%M:%S')
        
        date_filter = "AND request_time >= ?"
        params.append(past_date_str)
        
        # Логирование для отладки
        logger.info(f"Фильтр по дате: с {past_date_str} до сегодня ({today})")
    
    try:
        # Получаем общую статистику
        query = f"""
            SELECT status, COUNT(*) FROM timeoff_requests 
            WHERE user_id = ? {date_filter} 
            GROUP BY status
        """
        
        # Логирование для отладки
        logger.info(f"SQL запрос: {query}, параметры: {params}")
        
        cursor.execute(query, params)
        
        # Инициализируем статистику
        stats = {
            'total': 0,
            'approved': 0,
            'rejected': 0,
            'pending': 0
        }
        
        # Заполняем статистику из результатов запроса
        results = cursor.fetchall()
        logger.info(f"Результаты запроса: {results}")
        
        for status, count in results:
            if status == 'approved':
                stats['approved'] = count
            elif status == 'rejected':
                stats['rejected'] = count
            elif status == 'pending':
                stats['pending'] = count
            
            stats['total'] += count
        
        return stats
    except Exception as e:
        logger.error(f"Error getting time-off stats for user {user_id}: {e}")
        # Печатаем полный trace для отладки
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {'total': 0, 'approved': 0, 'rejected': 0, 'pending': 0}
    finally:
        conn.close()

def update_timeoff_request(request_id, status, admin_id):
    """Update the status of a time-off request"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        # Добавляем расширенное логирование
        logger.info(f"Обновление запроса на отгул: ID={request_id}, статус={status}, admin_id={admin_id}")
        
        # Get the user_id and username for this request
        cursor.execute('''
            SELECT user_id, username FROM timeoff_requests
            WHERE id = ?
        ''', (request_id,))
        
        user_data = cursor.fetchone()
        if not user_data:
            logger.error(f"Запрос с ID={request_id} не найден в базе данных")
            return None, None
        
        user_id, username = user_data
        logger.info(f"Данные запроса: user_id={user_id}, username={username}")
        
        # Update the request
        now = datetime.now(MOSCOW_TZ).isoformat()
        cursor.execute('''
            UPDATE timeoff_requests
            SET status = ?, admin_id = ?, response_time = ?
            WHERE id = ?
        ''', (status, admin_id, now, request_id))
        
        conn.commit()
        logger.info(f"Статус запроса ID={request_id} успешно обновлен на '{status}'")
        return user_id, username
    except Exception as e:
        logger.error(f"Ошибка при обновлении запроса на отгул: {e}")
        # Добавляем трейс ошибки для отладки
        import traceback
        logger.error(f"Трейс ошибки: {traceback.format_exc()}")
        return None, None
    finally:
        conn.close()
