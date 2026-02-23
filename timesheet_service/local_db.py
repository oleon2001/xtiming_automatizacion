import sqlite3
import json
import os
from datetime import datetime
import logging

logger = logging.getLogger("LocalDB")

class LocalDB:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            # Usar la carpeta 'data' dentro del proyecto (Estándar Docker)
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            self.db_path = os.path.join(data_dir, "local_state.db")
        else:
            self.db_path = db_path
            
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Tabla de Tickets Pendientes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tabla de Tickets Procesados (Histórico)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tabla de Estado de la Aplicación (Key-Value Store)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()

    def add_pending_ticket(self, ticket_data):
        ticket_id = str(ticket_data.get('ticket_id'))
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO pending_tickets (ticket_id, data) VALUES (?, ?)",
                    (ticket_id, json.dumps(ticket_data, default=str))
                )
            return True
        except Exception as e:
            logger.error(f"Error adding pending ticket {ticket_id}: {e}")
            return False

    def get_pending_tickets(self):
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT data FROM pending_tickets ORDER BY created_at ASC")
                rows = cursor.fetchall()
                return [json.loads(row[0]) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching pending tickets: {e}")
            return []

    def remove_pending_ticket(self, ticket_id):
        try:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM pending_tickets WHERE ticket_id = ?", (str(ticket_id),))
            return True
        except Exception as e:
            logger.error(f"Error removing pending ticket {ticket_id}: {e}")
            return False

    def mark_processed(self, ticket_id):
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO processed_tickets (ticket_id) VALUES (?)",
                    (str(ticket_id),)
                )
            return True
        except Exception as e:
            logger.error(f"Error marking ticket {ticket_id} as processed: {e}")
            return False

    def is_processed(self, ticket_id):
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM processed_tickets WHERE ticket_id = ?", 
                    (str(ticket_id),)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking processed status for {ticket_id}: {e}")
            return False

    def save_state(self, key, value):
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                    (key, json.dumps(value, default=str))
                )
        except Exception as e:
            logger.error(f"Error saving state {key}: {e}")

    def load_state(self, key):
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return None
        except Exception as e:
            logger.error(f"Error loading state {key}: {e}")
            return None
