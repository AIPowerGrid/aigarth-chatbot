"""
Database module for storing Discord conversation history per channel.
Uses SQLite for lightweight, persistent storage.
"""
import sqlite3
import datetime
import os
from typing import List, Dict, Optional

DB_PATH = "conversations.db"

def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
    return conn

def init_db():
    """Initialize the database with the messages, memory, and mood tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            author_id INTEGER,
            content TEXT NOT NULL,
            is_bot INTEGER DEFAULT 0,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Memory bank table for sticky memories (especially from admin)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL,
            source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Mood table - tracks bot's current mood state
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mood (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mood TEXT NOT NULL,
            description TEXT,
            intensity REAL DEFAULT 0.5,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Recent happenings table - bot's current awareness of recent activity
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recent_happenings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Channel status table - AI-maintained summary per channel
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channel_status (
            channel_id INTEGER PRIMARY KEY,
            channel_name TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_channel_timestamp 
        ON messages(channel_id, timestamp DESC)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_key 
        ON memory(key)
    """)
    
    # Initialize default mood if none exists
    cursor.execute("SELECT COUNT(*) as count FROM mood")
    if cursor.fetchone()['count'] == 0:
        cursor.execute("""
            INSERT INTO mood (mood, description, intensity, updated_at)
            VALUES (?, ?, ?, ?)
        """, ("chill", "Default relaxed mood", 0.5, datetime.datetime.now().isoformat()))
    
    conn.commit()
    conn.close()
    print(f"✅ Database initialized at {DB_PATH}")

def add_message(channel_id: int, author_name: str, content: str, 
                author_id: Optional[int] = None, is_bot: bool = False):
    """Add a message to the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.datetime.now().isoformat()
    
    cursor.execute("""
        INSERT INTO messages (channel_id, author_name, author_id, content, is_bot, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (channel_id, author_name, author_id, content, 1 if is_bot else 0, timestamp))
    
    conn.commit()
    conn.close()

def get_channel_messages(channel_id: int, limit: int = 25, 
                        exclude_bot: bool = False) -> List[Dict]:
    """Get recent messages for a channel."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT author_name, content, is_bot, timestamp
        FROM messages
        WHERE channel_id = ?
    """
    params = [channel_id]
    
    if exclude_bot:
        query += " AND is_bot = 0"
    
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    # Convert to list of dicts and reverse to get chronological order
    messages = []
    for row in reversed(rows):
        messages.append({
            'author': row['author_name'],
            'content': row['content'],
            'is_bot': bool(row['is_bot']),
            'timestamp': row['timestamp']
        })
    
    return messages

def get_channel_message_count(channel_id: int) -> int:
    """Get the total number of messages in a channel."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM messages WHERE channel_id = ?", (channel_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result['count'] if result else 0

def format_channel_history(channel_id: int, max_messages: int = 25, 
                          exclude_bot: bool = False) -> str:
    """Format channel history for use in prompts."""
    messages = get_channel_messages(channel_id, limit=max_messages, exclude_bot=exclude_bot)
    
    if not messages:
        return ""
    
    formatted_history = "Recent chat (last messages):\n"
    for msg in messages:
        author = msg['author']
        content = msg['content']
        formatted_history += f"{author}: {content}\n"
    
    return formatted_history

def cleanup_old_messages(days_to_keep: int = 30):
    """Remove messages older than specified days."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=days_to_keep)).isoformat()
    
    cursor.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff_date,))
    deleted_count = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return deleted_count

# Memory bank functions
def save_memory(key: str, value: str, source: Optional[str] = None):
    """Save or update a memory. If key exists, updates it."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.datetime.now().isoformat()
    
    cursor.execute("""
        INSERT INTO memory (key, value, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            source = excluded.source,
            updated_at = excluded.updated_at
    """, (key, value, source, timestamp, timestamp))
    
    conn.commit()
    conn.close()

def get_memory(key: str) -> Optional[str]:
    """Get a memory by key."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT value FROM memory WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    
    return row['value'] if row else None

def get_all_memories() -> List[Dict]:
    """Get all memories."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT key, value, source, updated_at FROM memory ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            'key': row['key'],
            'value': row['value'],
            'source': row['source'],
            'updated_at': row['updated_at']
        }
        for row in rows
    ]

def format_memories() -> str:
    """Format all memories for use in prompts."""
    memories = get_all_memories()
    
    if not memories:
        return ""
    
    formatted = "Memory Bank (important things to remember):\n"
    for mem in memories:
        source_info = f" (from {mem['source']})" if mem['source'] else ""
        formatted += f"- {mem['key']}: {mem['value']}{source_info}\n"
    
    return formatted

def delete_memory(key: str) -> bool:
    """Delete a memory by key."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM memory WHERE key = ?", (key,))
    deleted = cursor.rowcount > 0
    
    conn.commit()
    conn.close()
    
    return deleted

# Mood functions
def get_mood() -> Dict:
    """Get current mood state."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT mood, description, intensity FROM mood ORDER BY updated_at DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'mood': row['mood'],
            'description': row['description'],
            'intensity': row['intensity']
        }
    else:
        # Default mood
        return {
            'mood': 'chill',
            'description': 'Default relaxed mood',
            'intensity': 0.5
        }

def set_mood(mood: str, description: Optional[str] = None, intensity: float = 0.5):
    """Set the bot's mood."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.datetime.now().isoformat()
    
    if description is None:
        # Generate description based on mood
        mood_descriptions = {
            'chill': 'Relaxed and casual',
            'excited': 'Energetic and enthusiastic',
            'focused': 'Serious and attentive',
            'sarcastic': 'Playfully snarky',
            'helpful': 'Eager to assist',
            'curious': 'Interested and inquisitive',
            'tired': 'Low energy, less talkative',
            'happy': 'Positive and upbeat'
        }
        description = mood_descriptions.get(mood.lower(), f'Currently feeling {mood}')
    
    cursor.execute("""
        INSERT INTO mood (mood, description, intensity, updated_at)
        VALUES (?, ?, ?, ?)
    """, (mood.lower(), description, intensity, timestamp))
    
    conn.commit()
    conn.close()

def format_mood() -> str:
    """Format current mood for use in prompts."""
    mood_data = get_mood()
    return f"Current mood: {mood_data['mood']} ({mood_data['description']}, intensity: {mood_data['intensity']:.1f})"

# Recent happenings functions
def get_recent_happenings() -> str:
    """Get current recent happenings summary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT content FROM recent_happenings ORDER BY updated_at DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    return row['content'] if row else ""

def set_recent_happenings(content: str):
    """Set the recent happenings summary. Max 1000 tokens (~750 words)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.datetime.now().isoformat()
    
    # Truncate if too long (rough estimate: 1 token ≈ 0.75 words, so 1000 tokens ≈ 750 words)
    # Being conservative, limit to ~600 words or ~4500 chars
    if len(content) > 4500:
        content = content[:4500] + "..."
    
    cursor.execute("""
        INSERT INTO recent_happenings (content, updated_at)
        VALUES (?, ?)
    """, (content, timestamp))
    
    conn.commit()
    conn.close()

def format_recent_happenings() -> str:
    """Format recent happenings for use in prompts."""
    happenings = get_recent_happenings()
    if not happenings:
        return ""
    return f"Recent happenings across the server:\n{happenings}"

# Channel status functions - AI-maintained summaries per channel
def get_channel_status(channel_id: int) -> Optional[str]:
    """Get the AI-maintained status for a channel."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT status FROM channel_status WHERE channel_id = ? 
        ORDER BY updated_at DESC LIMIT 1
    """, (channel_id,))
    row = cursor.fetchone()
    conn.close()
    
    return row['status'] if row else None

def set_channel_status(channel_id: int, channel_name: str, status: str):
    """Set/update the AI-maintained status for a channel."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.datetime.now().isoformat()
    
    cursor.execute("""
        INSERT INTO channel_status (channel_id, channel_name, status, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            status = excluded.status,
            channel_name = excluded.channel_name,
            updated_at = excluded.updated_at
    """, (channel_id, channel_name, status, timestamp))
    
    conn.commit()
    conn.close()

def get_all_channel_statuses() -> List[Dict]:
    """Get all channel statuses for cross-channel awareness."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT channel_id, channel_name, status, updated_at 
        FROM channel_status 
        ORDER BY updated_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            'channel_id': row['channel_id'],
            'channel_name': row['channel_name'],
            'status': row['status'],
            'updated_at': row['updated_at']
        }
        for row in rows
    ]

def format_channel_statuses(current_channel_id: int = None) -> str:
    """Format all channel statuses for the prompt, marking current channel."""
    statuses = get_all_channel_statuses()
    
    if not statuses:
        return ""
    
    formatted = "Channel Statuses (your awareness of each channel):\n"
    for s in statuses:
        marker = " ← YOU ARE HERE" if s['channel_id'] == current_channel_id else ""
        formatted += f"  #{s['channel_name']}: {s['status']}{marker}\n"
    
    return formatted

