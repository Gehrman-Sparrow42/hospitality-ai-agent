import sqlite3
from typing import List, Dict, Optional, Any
from contextlib import contextmanager
import config


@contextmanager
def get_db(db_path: Optional[str] = None):
    """Context manager for SQLite connection that commits and closes cleanly."""
    target_path = db_path if db_path is not None else config.DATABASE_PATH
    conn = sqlite3.connect(target_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes tables and indexes for messages, chat status, and system settings."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_phone 
            ON messages(phone);
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_status (
                phone TEXT PRIMARY KEY,
                is_muted INTEGER DEFAULT 0,
                muted_until TEXT,
                mute_reason TEXT,
                is_reservation_lead INTEGER DEFAULT 0,
                lead_details TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                recipient_jid TEXT NOT NULL,
                message_preview TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('SENT', 'FAILED')),
                prev_hash TEXT,
                entry_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bot_audit_recipient 
            ON bot_audit_logs(recipient_jid);
            """
        )
        # Migrate existing table if columns are missing
        cursor.execute("PRAGMA table_info(bot_audit_logs);")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        if "prev_hash" not in existing_cols:
            cursor.execute("ALTER TABLE bot_audit_logs ADD COLUMN prev_hash TEXT;")
        if "entry_hash" not in existing_cols:
            cursor.execute("ALTER TABLE bot_audit_logs ADD COLUMN entry_hash TEXT;")



def save_message(phone: str, role: str, content: str, db_path: Optional[str] = None) -> None:
    """Persists a message turn (user or assistant) to SQLite."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages (phone, role, content)
            VALUES (?, ?, ?);
            """,
            (phone.strip(), role.strip(), content.strip()),
        )


def get_history(phone: str, limit: Optional[int] = None, db_path: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Retrieves the most recent message history window for a given phone number.
    Returns messages in chronological order (oldest to newest).
    """
    target_limit = limit if limit is not None else config.HISTORY_LIMIT
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content FROM messages
            WHERE phone = ?
            ORDER BY id DESC
            LIMIT ?;
            """,
            (phone.strip(), target_limit),
        )
        rows = cursor.fetchall()
        
        # Reverse to deliver chronological order for chat context.
        history = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
        return history


def clear_history(phone: str, db_path: Optional[str] = None) -> int:
    """Removes all past conversation records for a given phone number. Returns deleted rows count."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM messages
            WHERE phone = ?;
            """,
            (phone.strip(),),
        )
        deleted_count = cursor.rowcount
        return deleted_count


def clear_all_history(db_path: Optional[str] = None) -> int:
    """Purges all conversation history from database."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages;")
        deleted_count = cursor.rowcount
        return deleted_count


def cleanup_old_messages(days: int = 10, db_path: Optional[str] = None) -> int:
    """
    Deletes messages older than `days` days to comply with KVKK data minimization.
    Returns the number of pruned rows.
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM messages
            WHERE created_at < datetime('now', ?);
            """,
            (f"-{days} days",),
        )
        deleted_count = cursor.rowcount
        return deleted_count


def get_all_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves high level metrics from the SQLite memory."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total_messages FROM messages;")
        total_messages = cursor.fetchone()["total_messages"]

        cursor.execute("SELECT COUNT(DISTINCT phone) as total_users FROM messages;")
        total_users = cursor.fetchone()["total_users"]

        return {
            "total_messages": total_messages,
            "total_users": total_users,
        }


def get_all_messages(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves the most recent messages across all conversations."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, phone, role, content, created_at
            FROM messages
            ORDER BY id DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "phone": row["phone"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def get_conversations_list(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves all distinct conversations grouped by phone,
    including the last message, role, timestamp, and message count.
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                m.phone,
                m.content as last_message,
                m.role as last_role,
                m.created_at as last_time,
                counts.msg_count
            FROM messages m
            INNER JOIN (
                SELECT phone, MAX(id) as max_id, COUNT(*) as msg_count
                FROM messages
                GROUP BY phone
            ) counts ON m.phone = counts.phone AND m.id = counts.max_id
            ORDER BY m.id DESC;
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "phone": row["phone"],
                "last_message": row["last_message"],
                "last_role": row["last_role"],
                "last_time": row["last_time"],
                "msg_count": row["msg_count"],
            }
            for row in rows
        ]


def get_full_conversation(phone: str, limit: int = 100, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves chronological messages for a specific conversation."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, phone, role, content, created_at
            FROM messages
            WHERE phone = ?
            ORDER BY id ASC
            LIMIT ?;
            """,
            (phone.strip(), limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "phone": row["phone"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def mute_chat(phone: str, duration_minutes: int = 120, reason: str = "admin_intervention", db_path: Optional[str] = None) -> Dict[str, Any]:
    """Mutes the bot for a specific phone number for duration_minutes (default 120m / 2h)."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    until = now + datetime.timedelta(minutes=duration_minutes)
    until_str = until.isoformat()

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_status (phone, is_muted, muted_until, mute_reason, updated_at)
            VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
                is_muted = 1,
                muted_until = excluded.muted_until,
                mute_reason = excluded.mute_reason,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (phone.strip(), until_str, reason),
        )
        return {
            "phone": phone.strip(),
            "is_muted": True,
            "muted_until": until_str,
            "mute_reason": reason,
        }


def unmute_chat(phone: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Unmutes a chat so the AI will resume answering immediately."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_status (phone, is_muted, muted_until, mute_reason, updated_at)
            VALUES (?, 0, NULL, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
                is_muted = 0,
                muted_until = NULL,
                mute_reason = NULL,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (phone.strip(),),
        )
        return {"phone": phone.strip(), "is_muted": False}


def get_chat_status(phone: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Checks if a chat is currently muted or marked as a reservation lead.
    Automatically expires mute if muted_until has passed.
    """
    import datetime
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT is_muted, muted_until, mute_reason, is_reservation_lead, lead_details, updated_at
            FROM chat_status
            WHERE phone = ?;
            """,
            (phone.strip(),),
        )
        row = cursor.fetchone()
        if not row:
            return {
                "phone": phone.strip(),
                "is_muted": False,
                "muted_until": None,
                "mute_reason": None,
                "is_reservation_lead": False,
                "lead_details": None,
            }

        is_muted = bool(row["is_muted"])
        muted_until = row["muted_until"]
        if is_muted and muted_until:
            try:
                until_dt = datetime.datetime.fromisoformat(muted_until)
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                if now_dt >= until_dt:
                    # Expired -> auto-unmute
                    cursor.execute(
                        "UPDATE chat_status SET is_muted = 0, muted_until = NULL WHERE phone = ?;",
                        (phone.strip(),),
                    )
                    is_muted = False
                    muted_until = None
            except Exception:
                pass

        return {
            "phone": phone.strip(),
            "is_muted": is_muted,
            "muted_until": muted_until,
            "mute_reason": row["mute_reason"],
            "is_reservation_lead": bool(row["is_reservation_lead"]),
            "lead_details": row["lead_details"],
        }


def mark_reservation_lead(phone: str, lead_details: str, db_path: Optional[str] = None) -> None:
    """Marks a conversation as a reservation lead."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_status (phone, is_reservation_lead, lead_details, updated_at)
            VALUES (?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
                is_reservation_lead = 1,
                lead_details = excluded.lead_details,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (phone.strip(), lead_details),
        )


def get_all_chat_statuses(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Returns a dictionary mapping phone -> status dict for all chats."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT phone FROM chat_status;")
        rows = cursor.fetchall()
        statuses = {}
        for row in rows:
            p = row["phone"]
            statuses[p] = get_chat_status(p, db_path=db_path)
        return statuses


def get_system_settings(db_path: Optional[str] = None) -> Dict[str, str]:
    """Retrieves all key-value pairs from system_settings table."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM system_settings;")
        rows = cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}


def save_system_settings(settings: Dict[str, str], db_path: Optional[str] = None) -> None:
    """Saves or updates system settings key-value pairs."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        for key, val in settings.items():
            cursor.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (str(key), str(val)),
            )


def log_bot_audit(
    recipient_jid: str,
    message_preview: str,
    status: str = "SENT",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Logs an outgoing bot message into the bot_audit_logs SQLite table with SHA-256 hash chaining."""
    from datetime import datetime, timezone
    import hashlib
    now_iso = datetime.now(timezone.utc).isoformat()
    rec_clean = str(recipient_jid).strip()
    msg_clean = str(message_preview).strip()
    st_clean = str(status).strip().upper()
    genesis_hash = "0" * 64

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT entry_hash FROM bot_audit_logs 
            ORDER BY id DESC LIMIT 1;
            """
        )
        last_row = cursor.fetchone()
        prev_hash = last_row["entry_hash"] if (last_row and last_row["entry_hash"]) else genesis_hash

        payload = f"{prev_hash}:{now_iso}:{rec_clean}:{msg_clean}:{st_clean}"
        entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        cursor.execute(
            """
            INSERT INTO bot_audit_logs (timestamp, recipient_jid, message_preview, status, prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (now_iso, rec_clean, msg_clean, st_clean, prev_hash, entry_hash),
        )
        return {
            "timestamp": now_iso,
            "recipient_jid": rec_clean,
            "message_preview": msg_clean,
            "status": st_clean,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }


def get_bot_audit_logs(
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves audit logs of outgoing bot messages."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, recipient_jid, message_preview, status, prev_hash, entry_hash, created_at
            FROM bot_audit_logs
            ORDER BY id DESC
            LIMIT ? OFFSET ?;
            """,
            (limit, offset),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def verify_db_audit_chain(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Verifies SQLite bot_audit_logs table cryptographic SHA-256 chain integrity."""
    import hashlib
    genesis_hash = "0" * 64
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, recipient_jid, message_preview, status, prev_hash, entry_hash
            FROM bot_audit_logs
            ORDER BY id ASC;
            """
        )
        rows = cursor.fetchall()
        if not rows:
            return {
                "is_valid": True,
                "total_records": 0,
                "latest_hash": genesis_hash,
                "genesis_hash": genesis_hash,
                "failed_at_id": None,
                "error": None,
            }

        expected_prev_hash = genesis_hash
        for row in rows:
            row_id = row["id"]
            prev_h = row["prev_hash"]
            entry_h = row["entry_hash"]

            # Skip legacy unchained records if any
            if prev_h is None and entry_h is None:
                continue

            if prev_h != expected_prev_hash:
                return {
                    "is_valid": False,
                    "total_records": len(rows),
                    "latest_hash": None,
                    "genesis_hash": genesis_hash,
                    "failed_at_id": row_id,
                    "error": f"Chain broken at record #{row_id}: expected prev_hash '{expected_prev_hash}', found '{prev_h}'",
                }

            payload = f"{prev_h}:{row['timestamp']}:{row['recipient_jid']}:{row['message_preview']}:{row['status']}"
            calc_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if entry_h != calc_hash:
                return {
                    "is_valid": False,
                    "total_records": len(rows),
                    "latest_hash": None,
                    "genesis_hash": genesis_hash,
                    "failed_at_id": row_id,
                    "error": f"Tampering detected at record #{row_id}: hash signature mismatch",
                }
            expected_prev_hash = entry_h

        return {
            "is_valid": True,
            "total_records": len(rows),
            "latest_hash": expected_prev_hash,
            "genesis_hash": genesis_hash,
            "failed_at_id": None,
            "error": None,
        }



