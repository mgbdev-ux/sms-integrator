import sqlite3
import logging

from werkzeug.security import generate_password_hash

from .config import Config

logger = logging.getLogger(__name__)

_db_path = None  # resolved lazily, cached after first successful connection


def _try_connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Write test to make sure the location is actually usable
    conn.execute("CREATE TABLE IF NOT EXISTS _write_test (id INTEGER)")
    conn.execute("DROP TABLE _write_test")
    conn.commit()
    return conn


def get_db():
    """
    Return a SQLite connection, falling back gracefully:
    resolved path -> /tmp -> in-memory, logging each fallback.
    """
    global _db_path
    if _db_path is None:
        _db_path = Config.resolve_db_path()

    try:
        return _try_connect(_db_path)
    except Exception as e:
        logger.warning("Database at %s is not writable: %s", _db_path, e)

    if _db_path != "/tmp/sms_gateway.db":
        try:
            _db_path = "/tmp/sms_gateway.db"
            return _try_connect(_db_path)
        except Exception as e:
            logger.warning("Fallback to /tmp failed: %s", e)

    logger.warning("Falling back to in-memory SQLite database")
    _db_path = ":memory:"
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and seed default data if the DB is empty."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'coworker',
                allowed_numbers TEXT DEFAULT '*'
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                direction TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                text TEXT NOT NULL,
                time TEXT NOT NULL,
                status TEXT NOT NULL,
                owner TEXT
            )
            """
        )
        # Safe migration for DBs created before the `owner` column existed
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN owner TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Safe migration for allowed_numbers column
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN allowed_numbers TEXT DEFAULT '*'")
        except sqlite3.OperationalError:
            pass  # column already exists

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS device_status (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                battery TEXT NOT NULL,
                version TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                secret_token TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        # Delete default coworkers if they exist from previous template runs to ensure clean state
        cursor.execute("DELETE FROM users WHERE username IN ('priya', 'rahul')")

        cursor.execute("SELECT COUNT(*) FROM settings WHERE key = 'admin_password'")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('admin_password', ?)",
                (generate_password_hash(Config.ADMIN_PASSWORD_DEFAULT),),
            )

        cursor.execute("SELECT COUNT(*) FROM device_status")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                """
                INSERT INTO device_status
                    (id, name, battery, version, last_seen, secret_token, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "node1",
                    "Realme 9 Integrator Node",
                    "85%",
                    "1.1",
                    "Never",
                    Config.DEVICE_TOKEN,
                    "offline",
                ),
            )

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("Error during init_db: %s", e)
