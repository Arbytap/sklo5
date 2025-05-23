import sqlite3
import logging
from datetime import datetime, timedelta
from config import DATABASE_FILE, MOSCOW_TZ, MAX_LOCATION_AGE_HOURS

logger = logging.getLogger(__name__)

def init_db():
    """Initialize the database with required tables if they don't exist"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # User information table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_mapping (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Status history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user_mapping(user_id)
        )
    ''')
    
    # Location tracking table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS location_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            latitude REAL,
            longitude REAL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            location_type TEXT DEFAULT 'intermediate',  -- 'start', 'intermediate', 'end'
            FOREIGN KEY (user_id) REFERENCES user_mapping(user_id)
        )
    ''')
    
    # Morning check table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS morning_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            check_date TEXT,
            checked_in BOOLEAN DEFAULT 0,
            notified BOOLEAN DEFAULT 0,
            admin_notified BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES user_mapping(user_id),
            UNIQUE(user_id, check_date)
        )
    ''')
    
    # Night shift schedule table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS night_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            FOREIGN KEY (user_id) REFERENCES user_mapping(user_id)
        )
    ''')
    
    # Time-off requests table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timeoff_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_time TIMESTAMP,
            admin_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES user_mapping(user_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    
    logger.info("Database initialized")

def get_user_locations(user_id, hours_limit=MAX_LOCATION_AGE_HOURS, session_id=None, date=None):
    """Get location history for a specific user
    
    Args:
        user_id: Telegram user ID
        hours_limit: How many hours back to look for locations
        session_id: If provided, only return locations from this session
        date: Если указана дата в формате 'YYYY-MM-DD', возвращать данные только за этот день
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    if session_id:
        # Get locations from a specific session
        cursor.execute('''
            SELECT id, latitude, longitude, timestamp, location_type
            FROM location_history 
            WHERE user_id = ? AND session_id = ? 
            ORDER BY timestamp
        ''', (user_id, session_id))
    elif date:
        # Get locations for a specific date
        date_start = f"{date} 00:00:00"
        date_end = f"{date} 23:59:59"
        
        cursor.execute('''
            SELECT id, latitude, longitude, timestamp, location_type
            FROM location_history 
            WHERE user_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
        ''', (user_id, date_start, date_end))
    else:
        # Get all recent locations
        # Calculate the time limit
        time_limit = datetime.now(MOSCOW_TZ) - timedelta(hours=hours_limit)
        time_limit_str = time_limit.strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            SELECT id, latitude, longitude, timestamp, location_type
            FROM location_history 
            WHERE user_id = ? AND timestamp > ? 
            ORDER BY timestamp
        ''', (user_id, time_limit_str))
    
    locations = cursor.fetchall()
    
    # Convert timestamp strings to datetime objects if they are strings
    processed_locations = []
    for loc in locations:
        loc_id, lat, lon, ts, loc_type = loc
        if isinstance(ts, str):
            try:
                ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
                except Exception as e:
                    logger.error(f"Error parsing timestamp: {e}, timestamp: {ts}")
                    continue
        processed_locations.append((loc_id, lat, lon, ts, loc_type))
    
    conn.close()
    return processed_locations

def save_location(user_id, latitude, longitude, session_id=None, location_type='intermediate'):
    """Save a new location for a user
    
    Args:
        user_id: Telegram user ID
        latitude: Location latitude
        longitude: Location longitude
        session_id: Session ID for tracking a sequence of locations (optional)
        location_type: One of 'start', 'intermediate', 'end' (default: 'intermediate')
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # If session_id not provided, generate one
    if not session_id:
        # Check if there's an active session from today
        today = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT session_id FROM location_history 
            WHERE user_id = ? AND timestamp LIKE ? AND location_type != 'end' 
            ORDER BY timestamp DESC LIMIT 1
        ''', (user_id, f"{today}%"))
        
        result = cursor.fetchone()
        if result:
            session_id = result[0]
        else:
            # Create new session ID based on timestamp
            session_id = f"session_{user_id}_{int(datetime.now().timestamp())}"
    
    cursor.execute('''
        INSERT INTO location_history (user_id, latitude, longitude, session_id, location_type)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, latitude, longitude, session_id, location_type))
    
    conn.commit()
    conn.close()
    return session_id

def save_status(user_id, status):
    """Save a new status for a user"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO status_history (user_id, status)
        VALUES (?, ?)
    ''', (user_id, status))
    
    conn.commit()
    conn.close()
    return True

def get_user_status_history(user_id, date=None, days=1):
    """Get status history for a specific user
    
    Args:
        user_id: ID пользователя
        date: Дата в формате строки 'YYYY-MM-DD', если нужны данные за конкретный день
        days: Количество дней, за которые нужны данные (если date не указан)
    
    Returns:
        Список кортежей (status, timestamp) в порядке возрастания времени (сначала старые)
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    if date:
        # Get status updates for a specific date
        # The date parameter should be a string in the format 'YYYY-MM-DD'
        date_start = f"{date} 00:00:00"
        date_end = f"{date} 23:59:59"
        
        cursor.execute('''
            SELECT status, timestamp
            FROM status_history
            WHERE user_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        ''', (user_id, date_start, date_end))
    else:
        # Get status updates from the last X days
        time_limit = datetime.now(MOSCOW_TZ) - timedelta(days=days)
        time_limit_str = time_limit.strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            SELECT status, timestamp 
            FROM status_history 
            WHERE user_id = ? AND timestamp > ? 
            ORDER BY timestamp ASC
        ''', (user_id, time_limit_str))
    
    status_history = cursor.fetchall()
    conn.close()
    return status_history

def get_user_latest_status(user_id):
    """Получить самый последний статус пользователя
    
    Args:
        user_id: ID пользователя
    
    Returns:
        Кортеж (status, timestamp) или None, если статус не найден
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT status, timestamp 
        FROM status_history 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 1
    ''', (user_id,))
    
    status = cursor.fetchone()
    conn.close()
    
    return status

def get_all_users_with_latest_status():
    """Get all users with their latest status"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT um.user_id, um.full_name, sh.status, sh.timestamp
        FROM user_mapping um
        LEFT JOIN (
            SELECT user_id, status, timestamp,
                  ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY timestamp DESC) as rn
            FROM status_history
        ) sh ON um.user_id = sh.user_id AND sh.rn = 1
        ORDER BY um.full_name
    ''')
    
    users = cursor.fetchall()
    conn.close()
    return users

def get_today_locations_for_user(user_id, date=None):
    """Get all locations for a user from a specific date
    
    Args:
        user_id: ID пользователя
        date: Дата в формате строки 'YYYY-MM-DD', если None - используется сегодняшняя дата
        
    Returns:
        Список кортежей (latitude, longitude, timestamp, session_id, location_type)
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Get date in Moscow timezone
    if date is None:
        date = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT latitude, longitude, timestamp, session_id, location_type
        FROM location_history 
        WHERE user_id = ? AND timestamp LIKE ? 
        ORDER BY timestamp
    ''', (user_id, f"{date}%"))
    
    locations = cursor.fetchall()
    conn.close()
    return locations

def get_active_location_sessions(user_id):
    """Get all active location sessions for a user"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Get today's date in Moscow timezone
    today = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT DISTINCT session_id
        FROM location_history 
        WHERE user_id = ? AND timestamp LIKE ? AND location_type != 'end'
        ORDER BY timestamp DESC
    ''', (user_id, f"{today}%"))
    
    sessions = cursor.fetchall()
    conn.close()
    return [s[0] for s in sessions]

def mark_session_ended(session_id, user_id, latitude=None, longitude=None):
    """Mark a location session as ended
    
    If latitude and longitude are provided, adds a final location point
    with location_type='end'. Otherwise, just marks the last point as 'end'.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    try:
        if latitude and longitude:
            # Add a final location point
            cursor.execute('''
                INSERT INTO location_history (user_id, latitude, longitude, session_id, location_type)
                VALUES (?, ?, ?, ?, 'end')
            ''', (user_id, latitude, longitude, session_id))
            logger.info(f"Added end location point for session {session_id}")
        else:
            # Check if the session exists
            cursor.execute('''
                SELECT COUNT(*) FROM location_history
                WHERE user_id = ? AND session_id = ?
            ''', (user_id, session_id))
            
            count = cursor.fetchone()[0]
            
            if count > 0:
                # Update the most recent location in this session to be an end point
                cursor.execute('''
                    UPDATE location_history
                    SET location_type = 'end'
                    WHERE id = (
                        SELECT id FROM location_history
                        WHERE user_id = ? AND session_id = ?
                        ORDER BY timestamp DESC LIMIT 1
                    )
                ''', (user_id, session_id))
                logger.info(f"Marked last point as end for session {session_id}")
            else:
                logger.warning(f"No locations found for session {session_id}, user {user_id}")
        
        conn.commit()
    except Exception as e:
        logger.error(f"Error marking session {session_id} as ended: {e}")
    finally:
        conn.close()
    return True
