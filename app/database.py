import aiosqlite
import logging
from typing import Annotated

from fastapi import Depends

from app.config import db_path, schema_path, data_path

logger = logging.getLogger(__name__)

async def get_db():
    conn = await aiosqlite.connect(db_path, check_same_thread=False)
    conn.row_factory = aiosqlite.Row
    return conn


async def get_db_conn():
    conn = await get_db()
    try:
        yield conn
    finally:
        await conn.close()


DBConnDep = Annotated[aiosqlite.Connection, Depends(get_db_conn)]


async def init_db():
    conn = await get_db()
    logger.info("Initializing database from schema.sql")
    cursor = await conn.cursor()
    try:
        with open(schema_path, "r") as f:
            await cursor.executescript(f.read())
        await conn.commit()
        logger.info("Database initialized from schema.sql")

        await seed_if_empty(conn)

        await conn.close()
    except Exception as e:
        print(f"Warning: Could not initialize database from schema.sql: {e}")


async def seed_if_empty(conn: aiosqlite.Connection):
    cursor = await conn.cursor()

    await cursor.execute("SELECT COUNT(*) FROM scryfall_all_cards")
    (scryfall_all_cards_count,) = await cursor.fetchone()
    
    await cursor.execute("SELECT COUNT(*) FROM '17lands')")
    (seventeenlands_decks_count,) = await cursor.fetchone()

    await cursor.execute("SELECT COUNT(*) FROM '17lands_abilities')")
    (seventeenlands_abilities_count,) = await cursor.fetchone()

    if scryfall_all_cards_count == 0 and seventeenlands_decks_count == 0 and seventeenlands_abilities_count == 0:
        logger.info("Tables empty, running seed scripts")
        await run_seed_scripts(conn)
    else:
        logger.info(f"Database already seeded, skipping...")


async def run_seed_scripts(conn: aiosqlite.Connection):
    seeds_dir = data_path
    cursor = await conn.cursor()

    for sql_file in sorted(seeds_dir.glob("*.sql")):
        logger.info(f"Running seed: {sql_file.name}")
        await cursor.executescript(sql_file.read_text())

    await conn.commit()