import aiosqlite
import json
import logging
from typing import AsyncGenerator
from app.config import settings
from app.core.passwords import hash_password

logger = logging.getLogger(__name__)

async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        yield db

async def init_db():
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        
        # 1. Admin Users Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. Bots Profiles Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                username TEXT NOT NULL,
                telegram_bot_id INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1,
                webhook_secret TEXT,
                settings JSON DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 3. Workflows / Flows Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT 'Main Flow',
                is_active INTEGER DEFAULT 1,
                version INTEGER DEFAULT 1,
                nodes JSON NOT NULL DEFAULT '[]',
                edges JSON NOT NULL DEFAULT '[]',
                viewport JSON DEFAULT '{"x": 0, "y": 0, "zoom": 1}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            );
        """)
        
        # 4. Bot Users Table (NoSQL data store inside JSON field)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                data JSON NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bot_id, telegram_id),
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            );
        """)
        
        # 5. Plugins Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS plugins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plugin_key TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                plugin_type TEXT NOT NULL, -- 'toolkit' or 'admin'
                is_active INTEGER DEFAULT 1,
                config JSON DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 6. Execution Logs Table (for live debugging like n8n)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                trigger_type TEXT NOT NULL,
                telegram_id INTEGER,
                status TEXT NOT NULL, -- 'success', 'error'
                node_steps JSON DEFAULT '[]',
                error_message TEXT,
                duration_ms REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            );
        """)

        # 7. System Settings Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value JSON NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 8. User-defined Button Identifiers (stored per bot in local studio DB)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_button_identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                identifier TEXT NOT NULL,
                button_type TEXT NOT NULL DEFAULT 'inline', -- 'inline' or 'reply'
                label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bot_id, identifier),
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            );
        """)

        # 9. User-defined Custom Variables (stored per bot in local studio DB)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_custom_variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                default_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bot_id, name),
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            );
        """)
        
        # Execution logs are read most-recent-first per bot; keep that cheap.
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_execution_logs_bot
            ON execution_logs (bot_id, id DESC)
        """)

        await db.commit()
        await _seed_admin(db)
        logger.info("Database initialized successfully with WAL mode.")


async def _seed_admin(db: aiosqlite.Connection) -> None:
    """Creates the single admin account exactly once, from env only.

    Login used to accept DEFAULT_ADMIN_PASS forever; seeding here means the
    default password works only while the account does not exist yet, and the
    operator is forced to set it explicitly (no shipped default).
    """
    cursor = await db.execute("SELECT COUNT(1) FROM admin_users")
    row = await cursor.fetchone()
    if row and row[0]:
        return
    if not settings.DEFAULT_ADMIN_PASS:
        logger.warning(
            "No administrator account exists. Start once with DEFAULT_ADMIN_USER "
            "and DEFAULT_ADMIN_PASS set to create it."
        )
        return
    await db.execute(
        "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
        (settings.DEFAULT_ADMIN_USER, hash_password(settings.DEFAULT_ADMIN_PASS)),
    )
    await db.commit()
    logger.info("Administrator account '%s' created from environment.", settings.DEFAULT_ADMIN_USER)
