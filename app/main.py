import sqlite3
import asyncio
from collections import namedtuple, Counter
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pathlib import Path
from datetime import datetime
import os


##############################################################################

def find_project_root(marker=".git"):
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    return current.parent


def get_last_log_line():
    """Read the last line from fake_seventeenlands.log"""
    try:
        if not log_file_path.exists():
            return None

        with open(log_file_path, 'rb') as file:
            # Seek to end of file
            file.seek(0, os.SEEK_END)
            file_size = file.tell()

            if file_size == 0:
                return None

            # Read backwards to find last newline
            file.seek(-2, os.SEEK_END)
            while file.read(1) != b'\n':
                if file.tell() == 1:  # At beginning of file
                    file.seek(0)
                    break
                file.seek(-2, os.SEEK_CUR)

            last_line = file.readline().decode('utf-8').strip()
            return last_line
    except Exception as e:
        print(f"Error reading log file: {e}")
        return None


log_file_path = Path(os.path.expanduser("~")) / ".seventeenlands" / "fake_seventeenlands.log"

project_root = find_project_root()
db_path = project_root / "database.db"
schema_path = project_root / "app/schema.sql"
template_path = project_root / "app/templates"


##############################################################################

def get_db():
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_conn():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


DBConnDep = Annotated[sqlite3.Connection, Depends(get_db_conn)]


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    try:
        with open(schema_path, "r") as f:
            cursor.executescript(f.read())
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not initialize database from schema.sql: {e}")


##############################################################################

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield
    print("shutting down")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=template_path)


@app.middleware("http")
async def add_logging_middleware(request: Request, call_next):
    print(f"Request path: {request.url.path}")
    response: Response = await call_next(request)
    print(f"Response status: {response.status_code}")
    return response


##############################################################################
# API
##############################################################################

async def fetch_decks(data: dict):
    import httpx
    cookies = data.get("cookies", {})
    if not cookies:
        raise ValueError("No cookies provided for API requests")

    params = {
        "format": "json"
    }

    base_api_url = "https://api.mtga.untapped.gg/api/v1/decks/pricing/cardkingdom/"
    UntappedDeck = namedtuple("Deck", ["name", "url", "api_url"])
    untapped_decks = []
    for deck_url in data["deck_urls"]:
        deck_parts = deck_url.split("/")
        if len(deck_parts) >= 2:
            untapped_decks.append(UntappedDeck(deck_parts[-2], deck_url, base_api_url + deck_parts[-1]))

    decks = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, url, api_url in untapped_decks:
            try:
                response = await client.get(api_url, cookies=cookies, params=params)
                response.raise_for_status()
                deck = {
                    "name": name,
                    "url": url,
                    "api_url": api_url,
                    "cards": response.json()
                }
                decks.append(deck)
                print(f"Fetched deck: {name}")
                await asyncio.sleep(2)
            except httpx.HTTPStatusError as e:
                print(f"HTTP error for {name}: {e.response.status_code}")
                decks[name] = {"name": name, "url": url, "cards": [], "error": str(e)}
            except httpx.RequestError as e:
                print(f"Request failed for {name}: {e}")
                decks[name] = {"name": name, "url": url, "cards": [], "error": str(e)}
            except ValueError as e:
                print(f"JSON decode failed for {name}: {e}")
                decks[name] = {"name": name, "url": url, "cards": [], "error": "Invalid JSON"}

    return decks


async def add_decks_to_db(conn: sqlite3.Connection, data: dict):
    decks = await fetch_decks(data)
    cursor = conn.cursor()

    for deck in decks:
        if deck.get("error"):
            print(f"Skipping deck {deck['name']} due to error: {deck['error']}")
            continue

        cursor.execute(
            "INSERT INTO decks (name, source, url, added_at) VALUES (?, ?, ?, ?)",
            (deck["name"], "untapped", deck["url"], datetime.now())
        )
        deck_id = cursor.lastrowid

        for card in deck.get("cards", []):
            unique_id = card.get("scryfallId") or card.get("mtgArenaId")

            if unique_id:
                cursor.execute(
                    "SELECT id FROM cards WHERE scryfallId = ? OR mtgArenaId = ?",
                    (card.get("scryfallId"), card.get("mtgArenaId"))
                )
            else:
                cursor.execute(
                    "SELECT id FROM cards WHERE name = ?",
                    (card["name"],)
                )

            result = cursor.fetchone()

            if result:
                card_id = result[0]
            else:
                cursor.execute(
                    """INSERT INTO cards 
                    (name, manaCost, manaValue, power, originalText, type, types, 
                     mtgArenaId, scryfallId, availability, colors, keywords) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (card.get("name"), card.get("manaCost"), card.get("manaValue"),
                     card.get("power"), card.get("originalText"), card.get("type"),
                     str(card.get("types", [])) if card.get("types") else None,
                     card.get("mtgArenaId"), card.get("scryfallId"),
                     str(card.get("availability", [])) if card.get("availability") else None,
                     str(card.get("colors", [])) if card.get("colors") else None,
                     str(card.get("keywords", [])) if card.get("keywords") else None)
                )
                card_id = cursor.lastrowid

            cursor.execute(
                "INSERT OR IGNORE INTO deck_cards (deck_id, card_id, quantity) VALUES (?, ?, ?)",
                (deck_id, card_id, card.get("qty", 1))
            )

    conn.commit()


def get_decks(cursor):
    cursor.execute("""
    SELECT d.id        as deck_id,
           d.name      as deck_name,
           d.source    as deck_source,
           d.url       as deck_url,
           c.name      as name,
           dc.quantity as quantity,
           c.manaCost  as manaCost,
           c.type      as type
    FROM decks d
             inner join deck_cards dc
                        on d.id = dc.deck_id
             left join cards c
                       on dc.card_id = c.id
    ORDER BY added_at DESC;
    """)
    rows = cursor.fetchall()

    cards = [dict(row) for row in rows]
    # print(decks)
    decks = {}
    for card in cards:
        deck_id = card["deck_id"]

        if deck_id not in decks:
            decks[deck_id] = {
                "id": card["deck_id"],
                "name": card["deck_name"],
                "source": card["deck_source"],
                "url": card["deck_url"],
                "cards": []
            }

        card_info = {
            "name": card["name"],
            "quantity": card["quantity"],
            "manaCost": card["manaCost"],
            "type": card["type"]
        }
        decks[deck_id]["cards"].append(card_info)
    return list(decks.values())


##############################################################################
# Routes
##############################################################################

@app.get("/check-logs", response_class=HTMLResponse)
async def get_last_log(request: Request, conn: DBConnDep):
    cursor = conn.cursor()
    
    last_line = get_last_log_line()
    split_line = last_line.split("::")
    cards_list = split_line[2].split(": ")[1].strip("[]").split(", ")
    qs = ", ".join("?" * len(cards_list))
    
    cursor.execute(f"select distinct name, mtgArenaId from cards where mtgArenaId in ({qs})", cards_list)
    card_names = [dict(row) for row in cursor.fetchall()]
    
    cards_counts = Counter(cards_list)

    # Create a dictionary mapping mtgArenaId to card info including count
    card_info_by_id = {}
    for card in card_names:
        card_info_by_id[card["name"]] = {
            # "name": card["name"],
            "count": cards_counts[card["mtgArenaId"]]
        }
    
    # Get all card details including mana cost and type
    cursor.execute(f"SELECT distinct name, manaCost, type, mtgArenaId FROM cards WHERE mtgArenaId IN ({qs})", cards_list)
    cards = [dict(row) for row in cursor.fetchall()]
    
    # Add count to each card
    for card in cards:
        card["count"] = card_info_by_id[card["name"]]["count"]
    
    qs_names = ", ".join("?" * len(list(set([card['name'] for card in cards]))))
    # card_ids_qs = ", ".join("?" * len(card_ids))
    cursor.execute(f"""
        SELECT DISTINCT d.id, d.name, d.source, d.url,
               COUNT(DISTINCT dc.card_id) as matched_cards,
               (SELECT COUNT(*) FROM deck_cards WHERE deck_id = d.id) as total_deck_cards
        FROM decks d
        JOIN deck_cards dc ON d.id = dc.deck_id
        JOIN cards c ON dc.card_id = c.id
        WHERE c.name IN ({qs_names}) 
        GROUP BY d.id
        ORDER BY matched_cards DESC
    """, [card['name'] for card in cards])
    matching_decks = [dict(row) for row in cursor.fetchall()]
    
    for deck in matching_decks:
        cursor.execute("""
                  SELECT c.name, dc.quantity, c.manaCost, c.type, c.mtgArenaId
                  FROM deck_cards dc
                  JOIN cards c ON dc.card_id = c.id
                  WHERE dc.deck_id = ?
                  ORDER BY c.manaValue, c.name
              """, (deck['id'],))
        deck['cards'] = [dict(row) for row in cursor.fetchall()]
        for card in deck['cards']:
            if card['name'] in card_info_by_id:
                card['current_count'] = card_info_by_id[card['name']]['count']
            else:
                card['current_count'] = 0
                
            # card['current_count'] = card_info_by_id[card['name']]['count']
            

    return templates.TemplateResponse(
        request=request, name="list_cards.html", context={"cards": cards, "matching_decks": matching_decks}
    )


@app.get("/follow", response_class=HTMLResponse)
async def list_follow(request: Request, conn: DBConnDep):
    cursor = conn.cursor()
    decks = get_decks(cursor)
    return templates.TemplateResponse(
        request=request, name="follow.html", context={"decks": decks}
    )


@app.get("/untapped", response_class=HTMLResponse)
async def list_untapped(request: Request, conn: DBConnDep):
    cursor = conn.cursor()
    decks = get_decks(cursor)
    return templates.TemplateResponse(
        request=request, name="untapped.html", context={"decks": decks}
    )


@app.post("/add/untapped-decks")
async def add_untapped_decks_route(request: Request, conn: DBConnDep, html_doc: Annotated[str, Form(...)]):
    try:
        data = await parse_untapped_html(html_doc)
        await add_decks_to_db(conn, data)
        cursor = conn.cursor()
        decks = get_decks(cursor)
        return templates.TemplateResponse(
            request=request, name="untapped.html", context={"decks": decks}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing decks: {str(e)}")


async def parse_untapped_html(html_doc: str):
    """get cookies and deck urls"""
    from bs4 import BeautifulSoup
    import jsonpickle

    result = {}
    soup = BeautifulSoup(html_doc, 'html.parser')

    _next_data_raw = soup.find("script", type="application/json", id="__NEXT_DATA__")
    if not _next_data_raw:
        raise ValueError("Could not find __NEXT_DATA__ script tag in HTML")

    _next_data_dict = jsonpickle.decode(_next_data_raw.string)

    _cookie_header = _next_data_dict.get("props", {}).get("cookieHeader", "")
    if not _cookie_header:
        raise ValueError("No cookieHeader found in __NEXT_DATA__")

    _cookie_header = _cookie_header.split(";")
    result["cookies"] = {}
    for cookie in _cookie_header:
        if "sessionid" in cookie:
            result["cookies"]["session_id"] = cookie.split("=")[1].strip()
        if "csrftoken" in cookie:
            result["cookies"]["csrf_token"] = cookie.split("=")[1].strip()

    _deck_tags = soup.find_all("a", class_="sc-bf50840f-1 ptaNk")
    result["deck_urls"] = list(set([dt.get("href") for dt in _deck_tags if dt.get("href")]))

    if not result["deck_urls"]:
        raise ValueError("No deck URLs found in HTML")

    print(f"Found {len(result['deck_urls'])} deck URLs")
    return result
