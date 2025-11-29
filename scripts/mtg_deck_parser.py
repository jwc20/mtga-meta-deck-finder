#!/usr/bin/env python3
"""
MTG Deck Parser and Storage

This script parses deck files from the z33kz33k/mtg repository format
and stores them in a SQLite database.

Usage:
    python mtg_deck_parser.py                    # Clone repo and parse
    python mtg_deck_parser.py /path/to/decks     # Parse from local directory
    python mtg_deck_parser.py --db custom.db     # Use custom database path
"""
import argparse
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Card:
    quantity: int
    name: str
    set_code: Optional[str] = None


@dataclass
class DeckMetadata:
    name: Optional[str] = None
    format: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Deck:
    metadata: DeckMetadata
    main: list[Card] = field(default_factory=list)
    sideboard: list[Card] = field(default_factory=list)
    commander: list[Card] = field(default_factory=list)
    file_path: Optional[str] = None


def parse_card_line(line: str) -> Optional[Card]:
    line = line.strip()
    if not line:
        return None
    
    match = re.match(r'^(\d+)\s+(.+?)(?:\|(\w+))?$', line)
    if match:
        quantity = int(match.group(1))
        name = match.group(2).strip()
        set_code = match.group(3)
        return Card(quantity=quantity, name=name, set_code=set_code)
    
    match = re.match(r'^(\d+)\s+\[([A-Z0-9]+):?\d*\]\s*(.+)$', line)
    if match:
        quantity = int(match.group(1))
        set_code = match.group(2)
        name = match.group(3).strip()
        return Card(quantity=quantity, name=name, set_code=set_code)
    
    match = re.match(r'^(\d+)\s+(.+?)(?:\s+\(([A-Z0-9]+)\))?(?:\s+\d+)?$', line)
    if match:
        quantity = int(match.group(1))
        name = match.group(2).strip()
        set_code = match.group(3)
        return Card(quantity=quantity, name=name, set_code=set_code)
    
    return None


def parse_deck_file(file_path: Path) -> Optional[Deck]:
    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        try:
            content = file_path.read_text(encoding='latin-1')
        except Exception:
            return None
    except Exception:
        return None
    
    lines = content.splitlines()
    
    metadata = DeckMetadata()
    main_cards: list[Card] = []
    sideboard_cards: list[Card] = []
    commander_cards: list[Card] = []
    
    current_section = None
    
    for line in lines:
        line = line.strip()
        
        if not line or line.startswith('#') or line.startswith('//'):
            continue
        
        if line.startswith('[') and line.endswith(']'):
            section_name = line[1:-1].lower()
            if section_name == 'metadata':
                current_section = 'metadata'
            elif section_name in ('main', 'mainboard', 'deck', 'maindeck'):
                current_section = 'main'
            elif section_name in ('sideboard', 'side'):
                current_section = 'sideboard'
            elif section_name in ('commander', 'commanders'):
                current_section = 'commander'
            else:
                current_section = section_name
            continue
        
        if current_section == 'metadata':
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'name':
                    metadata.name = value
                elif key == 'format':
                    metadata.format = value
                elif key == 'author':
                    metadata.author = value
                elif key == 'date':
                    metadata.date = value
                elif key == 'source':
                    metadata.source = value
                elif key == 'url':
                    metadata.url = value
        
        elif current_section in ('main', 'maindeck', 'deck', None):
            card = parse_card_line(line)
            if card:
                main_cards.append(card)
        
        elif current_section in ('sideboard', 'side'):
            card = parse_card_line(line)
            if card:
                sideboard_cards.append(card)
        
        elif current_section in ('commander', 'commanders'):
            card = parse_card_line(line)
            if card:
                commander_cards.append(card)
    
    if not main_cards and not commander_cards:
        return None
    
    return Deck(
        metadata=metadata,
        main=main_cards,
        sideboard=sideboard_cards,
        commander=commander_cards,
        file_path=str(file_path)
    )


def init_database(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            format TEXT,
            author TEXT,
            date TEXT,
            source TEXT,
            url TEXT,
            file_path TEXT UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL,
            section TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            name TEXT NOT NULL,
            set_code TEXT,
            FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cards_deck_id ON cards(deck_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_decks_format ON decks(format)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_decks_author ON decks(author)')
    
    conn.commit()
    return conn


def store_deck(conn: sqlite3.Connection, deck: Deck) -> int:
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO decks (name, format, author, date, source, url, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        deck.metadata.name,
        deck.metadata.format,
        deck.metadata.author,
        deck.metadata.date,
        deck.metadata.source,
        deck.metadata.url,
        deck.file_path
    ))
    
    deck_id = cursor.lastrowid
    
    cursor.execute('DELETE FROM cards WHERE deck_id = ?', (deck_id,))
    
    for card in deck.main:
        cursor.execute('''
            INSERT INTO cards (deck_id, section, quantity, name, set_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (deck_id, 'main', card.quantity, card.name, card.set_code))
    
    for card in deck.sideboard:
        cursor.execute('''
            INSERT INTO cards (deck_id, section, quantity, name, set_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (deck_id, 'sideboard', card.quantity, card.name, card.set_code))
    
    for card in deck.commander:
        cursor.execute('''
            INSERT INTO cards (deck_id, section, quantity, name, set_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (deck_id, 'commander', card.quantity, card.name, card.set_code))
    
    conn.commit()
    return deck_id


def find_deck_files(repo_path: Path) -> list[Path]:
    deck_files = []
    extensions = {'.txt', '.dck', '.dec', '.mwDeck'}
    
    for ext in extensions:
        deck_files.extend(repo_path.rglob(f'*{ext}'))
    
    valid_files = []
    for f in deck_files:
        if any(part.startswith('.') for part in f.parts):
            continue
        if '__pycache__' in str(f) or '.git' in str(f):
            continue
        valid_files.append(f)
    
    return valid_files


def clone_repository(repo_url: str, dest_path: Path) -> bool:
    if dest_path.exists():
        print(f"Repository already exists at {dest_path}")
        return True
    
    print(f"Cloning {repo_url}...")
    try:
        subprocess.run(
            ['git', 'clone', '--depth', '1', repo_url, str(dest_path)],
            check=True,
            capture_output=True,
            text=True
        )
        print("Clone complete.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to clone repository: {e.stderr}")
        return False


def get_deck_by_id(conn: sqlite3.Connection, deck_id: int) -> Optional[Deck]:
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM decks WHERE id = ?', (deck_id,))
    row = cursor.fetchone()
    if not row:
        return None
    
    metadata = DeckMetadata(
        name=row[1],
        format=row[2],
        author=row[3],
        date=row[4],
        source=row[5],
        url=row[6]
    )
    
    cursor.execute('SELECT section, quantity, name, set_code FROM cards WHERE deck_id = ?', (deck_id,))
    
    main_cards = []
    sideboard_cards = []
    commander_cards = []
    
    for section, quantity, name, set_code in cursor.fetchall():
        card = Card(quantity=quantity, name=name, set_code=set_code)
        if section == 'main':
            main_cards.append(card)
        elif section == 'sideboard':
            sideboard_cards.append(card)
        elif section == 'commander':
            commander_cards.append(card)
    
    return Deck(
        metadata=metadata,
        main=main_cards,
        sideboard=sideboard_cards,
        commander=commander_cards,
        file_path=row[7]
    )


def search_decks(conn: sqlite3.Connection, name: str = None, format: str = None, 
                 author: str = None, card_name: str = None, limit: int = 100) -> list[dict]:
    cursor = conn.cursor()
    
    query = 'SELECT DISTINCT d.id, d.name, d.format, d.author, d.date, d.source FROM decks d'
    conditions = []
    params = []
    
    if card_name:
        query += ' JOIN cards c ON d.id = c.deck_id'
        conditions.append('c.name LIKE ?')
        params.append(f'%{card_name}%')
    
    if name:
        conditions.append('d.name LIKE ?')
        params.append(f'%{name}%')
    
    if format:
        conditions.append('d.format = ?')
        params.append(format.lower())
    
    if author:
        conditions.append('d.author LIKE ?')
        params.append(f'%{author}%')
    
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    
    query += f' LIMIT {limit}'
    
    cursor.execute(query, params)
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'name': row[1],
            'format': row[2],
            'author': row[3],
            'date': row[4],
            'source': row[5]
        })
    
    return results


def get_database_stats(conn: sqlite3.Connection) -> dict:
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM decks')
    total_decks = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM cards')
    total_cards = cursor.fetchone()[0]
    
    cursor.execute('SELECT format, COUNT(*) FROM decks GROUP BY format ORDER BY COUNT(*) DESC')
    formats = {row[0]: row[1] for row in cursor.fetchall()}
    
    cursor.execute('SELECT source, COUNT(*) FROM decks GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10')
    sources = {row[0]: row[1] for row in cursor.fetchall()}
    
    cursor.execute('SELECT name, COUNT(*) as cnt FROM cards GROUP BY name ORDER BY cnt DESC LIMIT 20')
    top_cards = [(row[0], row[1]) for row in cursor.fetchall()]
    
    return {
        'total_decks': total_decks,
        'total_card_entries': total_cards,
        'formats': formats,
        'top_sources': sources,
        'most_played_cards': top_cards
    }


def deck_to_dict(deck: Deck) -> dict:
    return {
        'metadata': {
            'name': deck.metadata.name,
            'format': deck.metadata.format,
            'author': deck.metadata.author,
            'date': deck.metadata.date,
            'source': deck.metadata.source,
            'url': deck.metadata.url
        },
        'main': [{'quantity': c.quantity, 'name': c.name, 'set_code': c.set_code} for c in deck.main],
        'sideboard': [{'quantity': c.quantity, 'name': c.name, 'set_code': c.set_code} for c in deck.sideboard],
        'commander': [{'quantity': c.quantity, 'name': c.name, 'set_code': c.set_code} for c in deck.commander],
        'file_path': deck.file_path
    }


def export_to_json(conn: sqlite3.Connection, output_path: Path, limit: int = None):
    import json
    
    cursor = conn.cursor()
    query = 'SELECT id FROM decks'
    if limit:
        query += f' LIMIT {limit}'
    
    cursor.execute(query)
    deck_ids = [row[0] for row in cursor.fetchall()]
    
    decks = []
    for deck_id in deck_ids:
        deck = get_deck_by_id(conn, deck_id)
        if deck:
            decks.append(deck_to_dict(deck))
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(decks, f, indent=2, ensure_ascii=False)
    
    print(f"Exported {len(decks)} decks to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Parse MTG deck files and store them in SQLite database'
    )
    parser.add_argument(
        'source_path',
        nargs='?',
        default=None,
        help='Path to local directory containing deck files (optional, will clone repo if not provided)'
    )
    parser.add_argument(
        '--db',
        default='mtg_decks.db',
        help='Path to SQLite database file (default: mtg_decks.db)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run with example deck to test parsing'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show database statistics'
    )
    parser.add_argument(
        '--search-name',
        help='Search decks by name'
    )
    parser.add_argument(
        '--search-format',
        help='Search decks by format (e.g., vintage, modern, commander)'
    )
    parser.add_argument(
        '--search-card',
        help='Search decks containing a specific card'
    )
    parser.add_argument(
        '--export-json',
        help='Export all decks to JSON file'
    )
    parser.add_argument(
        '--get-deck',
        type=int,
        help='Get deck by ID and display it'
    )
    
    args = parser.parse_args()
    
    db_path = Path(args.db)
    
    if args.test:
        print("Running test with example deck...")
        test_deck_content = '''[metadata]
Name=Eternal Weekend Pittsburgh 2024 Esper Lurrus
Format=vintage
Author=BoshNRoll
Date=2024-12-03
Source=moxfield.com
URL=https://www.youtube.com/watch?v=ZkH_RHwbbt0
[Main]
1 Ancestral Recall|VMA
1 Black Lotus|VMA
1 Brainstorm|DSC
1 Daze|EMA
1 Demonic Tutor|CMM
1 Dig Through Time|DSC
2 Flooded Strand|MH3
3 Force of Negation|2X2
4 Force of Will|DMR
1 Gitaxian Probe|NPH
2 Lavinia, Azorius Renegade|RVR
1 Lórien Revealed|LTR
1 Mental Misstep|NPH
2 Mishra's Bauble|2XM
1 Misty Rainforest|MH2
1 Mox Jet|VMA
1 Mox Pearl|VMA
1 Mox Sapphire|VMA
4 Orcish Bowmasters|LTR
2 Polluted Delta|MH3
4 Psychic Frog|MH3
1 Scalding Tarn|MH2
1 Soul-Guide Lantern|FDN
3 Spell Pierce|DFT
1 Strip Mine|VMA
4 Swords to Plowshares|TDC
1 Time Walk|VMA
1 Timetwister|VMA
1 Treasure Cruise|TDC
3 Tundra|VMA
4 Underground Sea|VMA
4 Wasteland|EMA
[Sideboard]
1 Annul|KHM
1 Consign to Memory|MH3
4 Containment Priest|M21
2 Fatal Push|2XM
1 Lurrus of the Dream-Den|IKO
1 Mindbreak Trap|ZEN
1 Nihil Spellbomb|A25
1 Steel Sabotage|2XM
1 Stern Scolding|LTR
1 The Tabernacle at Pendrell Vale|ME3
1 Tormod's Crypt|DMR
'''
        test_file = Path('/tmp/test_deck.txt')
        test_file.write_text(test_deck_content)
        
        deck = parse_deck_file(test_file)
        if deck:
            print(f"\nParsed deck successfully!")
            print(f"  Name: {deck.metadata.name}")
            print(f"  Format: {deck.metadata.format}")
            print(f"  Author: {deck.metadata.author}")
            print(f"  Date: {deck.metadata.date}")
            print(f"  Source: {deck.metadata.source}")
            print(f"  URL: {deck.metadata.url}")
            print(f"  Main deck cards: {len(deck.main)} ({sum(c.quantity for c in deck.main)} total)")
            print(f"  Sideboard cards: {len(deck.sideboard)} ({sum(c.quantity for c in deck.sideboard)} total)")
            
            print("\nSample cards from main deck:")
            for card in deck.main[:5]:
                print(f"    {card.quantity}x {card.name} [{card.set_code}]")
            
            conn = init_database(db_path)
            deck_id = store_deck(conn, deck)
            conn.close()
            print(f"\nStored deck with ID {deck_id} in {db_path}")
        else:
            print("Failed to parse test deck!")
            sys.exit(1)
        return
    
    if args.stats:
        if not db_path.exists():
            print(f"Database {db_path} does not exist. Run parsing first.")
            sys.exit(1)
        
        conn = sqlite3.connect(db_path)
        stats = get_database_stats(conn)
        conn.close()
        
        print(f"\n=== Database Statistics ===")
        print(f"Total decks: {stats['total_decks']}")
        print(f"Total card entries: {stats['total_card_entries']}")
        
        print(f"\nFormats:")
        for fmt, count in list(stats['formats'].items())[:15]:
            print(f"  {fmt or 'unknown'}: {count}")
        
        print(f"\nTop sources:")
        for source, count in stats['top_sources'].items():
            print(f"  {source or 'unknown'}: {count}")
        
        print(f"\nMost played cards:")
        for name, count in stats['most_played_cards'][:15]:
            print(f"  {name}: {count} appearances")
        return
    
    if args.search_name or args.search_format or args.search_card:
        if not db_path.exists():
            print(f"Database {db_path} does not exist. Run parsing first.")
            sys.exit(1)
        
        conn = sqlite3.connect(db_path)
        results = search_decks(
            conn,
            name=args.search_name,
            format=args.search_format,
            card_name=args.search_card
        )
        conn.close()
        
        print(f"\nFound {len(results)} decks:")
        for deck in results[:50]:
            print(f"  [{deck['id']}] {deck['name'] or 'Unnamed'} - {deck['format'] or 'unknown'} by {deck['author'] or 'unknown'}")
        
        if len(results) > 50:
            print(f"  ... and {len(results) - 50} more")
        return
    
    if args.get_deck:
        if not db_path.exists():
            print(f"Database {db_path} does not exist. Run parsing first.")
            sys.exit(1)
        
        conn = sqlite3.connect(db_path)
        deck = get_deck_by_id(conn, args.get_deck)
        conn.close()
        
        if not deck:
            print(f"Deck with ID {args.get_deck} not found.")
            sys.exit(1)
        
        print(f"\n=== Deck: {deck.metadata.name or 'Unnamed'} ===")
        print(f"Format: {deck.metadata.format or 'unknown'}")
        print(f"Author: {deck.metadata.author or 'unknown'}")
        print(f"Date: {deck.metadata.date or 'unknown'}")
        print(f"Source: {deck.metadata.source or 'unknown'}")
        if deck.metadata.url:
            print(f"URL: {deck.metadata.url}")
        
        if deck.commander:
            print(f"\nCommander ({len(deck.commander)}):")
            for card in deck.commander:
                print(f"  {card.quantity}x {card.name} [{card.set_code or '?'}]")
        
        print(f"\nMain Deck ({sum(c.quantity for c in deck.main)} cards):")
        for card in deck.main:
            print(f"  {card.quantity}x {card.name} [{card.set_code or '?'}]")
        
        if deck.sideboard:
            print(f"\nSideboard ({sum(c.quantity for c in deck.sideboard)} cards):")
            for card in deck.sideboard:
                print(f"  {card.quantity}x {card.name} [{card.set_code or '?'}]")
        return
    
    if args.export_json:
        if not db_path.exists():
            print(f"Database {db_path} does not exist. Run parsing first.")
            sys.exit(1)
        
        conn = sqlite3.connect(db_path)
        export_to_json(conn, Path(args.export_json))
        conn.close()
        return
    
    if args.source_path:
        repo_path = Path(args.source_path)
        if not repo_path.exists():
            print(f"Error: Path {repo_path} does not exist")
            sys.exit(1)
    else:
        repo_url = "https://github.com/z33kz33k/mtg"
        repo_path = Path("./mtg_repo")
        
        if not clone_repository(repo_url, repo_path):
            print("\nNote: If cloning fails, you can manually download the repository")
            print("and run this script with the path to the downloaded folder:")
            print(f"  python {sys.argv[0]} /path/to/mtg_repo")
            sys.exit(1)
    
    print(f"Initializing database at {db_path}...")
    conn = init_database(db_path)
    
    print("Searching for deck files...")
    deck_files = find_deck_files(repo_path)
    print(f"Found {len(deck_files)} potential deck files.")
    
    parsed_count = 0
    failed_count = 0
    
    for file_path in deck_files:
        deck = parse_deck_file(file_path)
        if deck:
            store_deck(conn, deck)
            parsed_count += 1
            if parsed_count % 100 == 0:
                print(f"Parsed {parsed_count} decks...")
        else:
            failed_count += 1
    
    conn.close()
    
    print(f"\nDone!")
    print(f"Successfully parsed and stored: {parsed_count} decks")
    print(f"Failed to parse: {failed_count} files")
    print(f"Database saved to: {db_path.absolute()}")


if __name__ == "__main__":
    main()
