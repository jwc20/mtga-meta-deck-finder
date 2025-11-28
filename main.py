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
from sse_starlette import EventSourceResponse

log_line_count = 0
last_processed_log_line_count = 0


##############################################################################

def find_project_root(marker=".git"):
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    return current.parent


def get_last_log_line():
    """Read the last line from fake_seventeenlands.log"""
    global log_line_count
    try:
        if not log_file_path.exists():
            return None

        with open(log_file_path, 'rb') as file:
            log_line_count = sum(1 for _ in file)

            file.seek(0, os.SEEK_END)
            file_size = file.tell()

            if file_size == 0:
                return None

            file.seek(-2, os.SEEK_END)
            while file.read(1) != b'\n':
                if file.tell() == 1:
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
schema_path = project_root / "schema.sql"
template_path = project_root / "templates"


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
# Routes #####################################################################
##############################################################################


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


@app.get("/check-logs")
async def check_logs_stream(request: Request):
    conn = get_db()

    async def event_generator():
        global log_line_count, last_processed_log_line_count
        cursor = conn.cursor()

        try:
            while True:
                if await request.is_disconnected():
                    break

                last_log_entry = get_last_log_line()

                if log_line_count != last_processed_log_line_count:
                    last_processed_log_line_count = log_line_count

                    arena_ids = parse_arena_ids_from_log(last_log_entry)

                    if arena_ids:
                        current_deck_cards = fetch_current_deck_cards(cursor, arena_ids)
                        card_count_by_name = build_card_count_map(arena_ids, current_deck_cards)
                        matching_decks = find_matching_decks(cursor, current_deck_cards)
                        enrich_decks_with_cards(cursor, matching_decks, card_count_by_name)
                        
                        # Add type counts to each matching deck
                        for deck in matching_decks:
                            type_counts = {}
                            for card in deck.get('cards', []):
                                if 'types' in card:
                                    # Handle basic card types (Creature, Instant, etc.)
                                    if card["types"]:
                                        card_types = card['types'].strip().lower()
                                        type_counts[card_types] = type_counts.get(card_types, 0) + 1
                            deck['type_counts'] = type_counts
                    else:
                        current_deck_cards = []
                        matching_decks = []
                    
                    html_content = templates.get_template("list_cards.html").render(
                        cards=current_deck_cards,
                        matching_decks=matching_decks
                    )

                    yield {
                        "event": "log-update",
                        "data": html_content.replace("\n", " ")
                    }

                await asyncio.sleep(1)
        finally:
            conn.close()

    return EventSourceResponse(event_generator())



@app.post("/add/untapped-decks-urls")
async def add_untapped_decks_url_list_route(request: Request, conn: DBConnDep, url_list: Annotated[str, Form(...)]):
    try:
        print(url_list)
        urls = url_list.split("\n")
        data = await build_untapped_decks_api_urls(urls)

        try:
            decks = await fetch_untapped_decks_from_api(conn=conn, cookies=None, untapped_decks=data)
        except Exception as e:
            decks = []

        cursor = conn.cursor()
        
        await add_decks_to_db(conn, decks)


        added_decks = get_decks(cursor)
        # await add_decks_to_db(conn, decks)

        return templates.TemplateResponse(
            request=request, name="untapped.html", context={"decks": added_decks}
        )


    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing decks: {str(e)}")


@app.post("/add/untapped-decks-html")
async def add_untapped_decks_html_route(request: Request, conn: DBConnDep, html_doc: Annotated[str, Form(...)]):
    try:
        data = await parse_untapped_html(html_doc)
        await add_decks_by_html(conn, data)
        cursor = conn.cursor()
        decks = get_decks(cursor)
        return templates.TemplateResponse(
            request=request, name="untapped.html", context={"decks": decks}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing decks: {str(e)}")


##############################################################################
# Utils ######################################################################
##############################################################################


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


def parse_arena_ids_from_log(log_entry: str) -> list[str]:
    try:
        log_segments = log_entry.split("::")
        if len(log_segments) < 3:
            return []

        cards_section = log_segments[2].split(": ")
        if len(cards_section) < 2:
            return []

        arena_ids_str = cards_section[1].strip("[]")
        return [id.strip() for id in arena_ids_str.split(", ") if id.strip()]
    except (IndexError, AttributeError):
        return []


def fetch_current_deck_cards(cursor, arena_ids: list[str]) -> list[dict]:
    if not arena_ids:
        return []
    
    # distinct_arena_ids = list(set(arena_ids))

    placeholders = ", ".join("?" * len(arena_ids))
    query = f"""
        SELECT DISTINCT name, manaCost, types, mtgArenaId, scryfallId, printedName, flavorName
        FROM cards 
        WHERE mtgArenaId IN ({placeholders})
    """
    cursor.execute(query, arena_ids)

    cards = [dict(row) for row in cursor.fetchall()]
    
    found_ids = list(set([card["mtgArenaId"] for card in cards]))
    
    missing_ids = list(set(arena_ids) - set(found_ids))
    
    if missing_ids:
        missing_cards = []
        print(f"Missing {len(missing_ids)} cards: {missing_ids}")
        _placeholders = ", ".join("?" * len(missing_ids))
        _query = f"""
            SELECT DISTINCT name, CAST(id as VARCHAR(20)) as mtgArenaId from cards_from_17_lands_2
            WHERE id IN ({_placeholders})
        """
        cursor.execute(_query, missing_ids)
        missing_cards = [dict(row) for row in cursor.fetchall()]
        
        for card in missing_cards:
            # search for the cards by name, get the first card and get manaCost, types, scryfallId 
            __query = "Select name, manaCost, types, scryfallId, printedName, flavorName from cards where name = ? limit 1"
            cursor.execute(__query, (card["name"],))
            result = cursor.fetchone()
            if not result:
                __query = "Select name, manaCost, types, scryfallId, printedName, flavorName from cards where printedName = ? or flavorName = ? limit 1"
                cursor.execute(__query, (card["name"], card["name"]))
                result = cursor.fetchone()
            
            # if result:
            card["name"] = result["name"]
            card["manaCost"] = result["manaCost"]
            card["types"] = result["types"]
            card["scryfallId"] = result["scryfallId"]
            card["printedName"] = result["printedName"]
            card["flavorName"] = result["flavorName"]

        cards.extend(missing_cards)
    # cards.extend([dict(row) for row in cursor.fetchall()])
    

    id_counts = Counter(arena_ids)
    for card in cards:
        card["count"] = id_counts.get(card["mtgArenaId"], 0)

    return cards


def build_card_count_map(arena_ids: list[str], cards: list[dict]) -> dict[str, int]:
    id_counts = Counter(arena_ids)
    card_count_map = {}

    for card in cards:
        card_count_map[card["name"]] = id_counts.get(card["mtgArenaId"], 0)

    return card_count_map


def find_matching_decks(cursor, current_cards: list[dict]) -> list[dict]:
    if not current_cards:
        return []

    unique_card_names = list(set(card['name'] for card in current_cards))
    placeholders = ", ".join("?" * len(unique_card_names))

    query = f"""
        SELECT DISTINCT 
            d.id, 
            d.name, 
            d.source, 
            d.url,
            COUNT(DISTINCT dc.card_id) as matched_cards,
            (SELECT COUNT(*) FROM deck_cards WHERE deck_id = d.id) as total_deck_cards
        FROM decks d
        JOIN deck_cards dc ON d.id = dc.deck_id
        JOIN cards c ON dc.card_id = c.id
        WHERE c.name IN ({placeholders})
        GROUP BY d.id
        ORDER BY matched_cards DESC
    """

    cursor.execute(query, unique_card_names)
    return [dict(row) for row in cursor.fetchall()]


def enrich_decks_with_cards(cursor, decks: list[dict], card_count_map: dict[str, int]):
    for deck in decks:
        deck_cards_query = """
            SELECT c.name, dc.quantity, c.manaCost, c.types, c.mtgArenaId, c.scryfallId
            FROM deck_cards dc
            JOIN cards c ON dc.card_id = c.id
            WHERE dc.deck_id = ?
            ORDER BY c.manaValue, c.name
        """
        cursor.execute(deck_cards_query, (deck['id'],))
        deck['cards'] = [dict(row) for row in cursor.fetchall()]

        for card in deck['cards']:
            card['current_count'] = card_count_map.get(card['name'], 0)


async def build_untapped_decks_api_urls(deck_urls: list):
    base_api_url = "https://api.mtga.untapped.gg/api/v1/decks/pricing/cardkingdom/"
    UntappedDeck = namedtuple("Deck", ["name", "url", "api_url"])
    untapped_decks = []
    for deck_url in deck_urls:
        deck_parts = deck_url.split("/")
        if len(deck_parts) >= 2:
            untapped_decks.append(UntappedDeck(deck_parts[-2], deck_url, base_api_url + deck_parts[-1]))

    return untapped_decks


async def fetch_untapped_decks_from_api(conn: DBConnDep, cookies: dict | None, untapped_decks: list):
    import httpx

    if not cookies:
        cursor = conn.cursor()
        cursor.execute("SELECT sessionid, csrfToken FROM user_info ORDER BY added_at DESC LIMIT 1")
        cookies_row = cursor.fetchone()
        cookies = {
            "sessionid": cookies_row[0],
            "csrfToken": cookies_row[1]
        }

    params = {
        "format": "json"
    }

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


async def fetch_untapped_decks_from_html(conn, data: dict):
    cookies = data.get("cookies", {})
    if not cookies:
        raise ValueError("No cookies provided for API requests")

    untapped_decks = await build_untapped_decks_api_urls(data["deck_urls"])

    cookies = {
        "session_id": data["cookies"]["session_id"],
        "csrf_token": data["cookies"]["csrf_token"],
    }

    # decks = await fetch_untapped_decks_from_api(untapped_decks)
    try:
        decks = await fetch_untapped_decks_from_api(conn, cookies, untapped_decks)
    except Exception as e:
        decks = []

    return decks



async def add_decks_to_db(conn: sqlite3.Connection, decks: list):
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


async def add_decks_by_html(conn: sqlite3.Connection, data: dict):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO user_info (sessionid, csrfToken, added_at) VALUES (?, ?, ?)",
        (data["cookies"]["session_id"], data["cookies"]["csrf_token"], datetime.now())
    )
    conn.commit()

    decks = await fetch_untapped_decks_from_html(conn, data)
    
    await add_decks_to_db(conn, decks)



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
