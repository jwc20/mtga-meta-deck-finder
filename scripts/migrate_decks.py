import sqlite3
from pathlib import Path


def find_project_root(marker=".git"):
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    return current.parent

project_root = find_project_root()
mtg_deck_db_path = project_root / "mtg_decks.db"
database_db_path = project_root / "database.db"


def migrate_decks(source_db: str, target_db: str):
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(target_db)

    source_cur = source.cursor()
    target_cur = target.cursor()

    source_cur.execute('SELECT id, name, format, author, date, source, url, file_path FROM decks')
    for row in source_cur.fetchall():
        id_, name, fmt, author, date, src, url, file_path = row
        print(f"Deck: {name}")
        target_cur.execute('''
            INSERT OR IGNORE INTO decks (id, name, source, author, format, url, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            id_,
            name or 'Unnamed',
            src or 'unknown',
            author,
            fmt,
            url or file_path or '',
            date or 'now'
        ))

    source_cur.execute('SELECT deck_id, section, quantity, name, set_code FROM cards')
    for row in source_cur.fetchall():
        deck_id, section, quantity, name, set_code = row
        print(f"Card: {name}")
        card_id = f"{name}|{set_code}" if set_code else name
        target_cur.execute('''
            INSERT OR IGNORE INTO deck_cards (deck_id, card_id, name, quantity, section)
            VALUES (?, ?, ?, ?, ?)
        ''', (deck_id, card_id, name, quantity, section))

    target.commit()
    source.close()
    target.close()


if __name__ == "__main__":
    migrate_decks(mtg_deck_db_path.__str__(), database_db_path.__str__())