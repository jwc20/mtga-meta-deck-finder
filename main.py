import sqlite3
import asyncio
from collections import namedtuple, Counter
from contextlib import asynccontextmanager
from typing import Annotated, Tuple, List, Set

from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pathlib import Path
from datetime import datetime
import os
from sse_starlette import EventSourceResponse

import re
from dataclasses import dataclass

log_line_count = 0
last_processed_log_line_count = 0


##############################################################################

def find_project_root(marker=".git"):
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    return current.parent


def get_last_log_line() -> str | None:
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





@dataclass
class ManaPool:
    W: int = 0
    U: int = 0
    B: int = 0
    R: int = 0
    G: int = 0
    C: int = 0

    @property
    def total(self) -> int:
        return self.W + self.U + self.B + self.R + self.G + self.C

    def can_pay(self, cost: "ManaCost") -> bool:
        remaining = self.total

        for color in ["W", "U", "B", "R", "G"]:
            required = getattr(cost, color)
            available = getattr(self, color)
            if available < required:
                return False
            remaining -= required

        if self.C < cost.C:
            return False
        remaining -= cost.C

        return remaining >= cost.generic


@dataclass
class ManaCost:
    W: int = 0
    U: int = 0
    B: int = 0
    R: int = 0
    G: int = 0
    C: int = 0
    generic: int = 0

    @classmethod
    def from_string(cls, mana_cost: str) -> "ManaCost":
        if not mana_cost:
            return cls()

        cost = cls()
        symbols = re.findall(r"\{([^}]+)}", mana_cost)

        for symbol in symbols:
            if symbol.isdigit():
                cost.generic += int(symbol)
            elif symbol == "W":
                cost.W += 1
            elif symbol == "U":
                cost.U += 1
            elif symbol == "B":
                cost.B += 1
            elif symbol == "R":
                cost.R += 1
            elif symbol == "G":
                cost.G += 1
            elif symbol == "C":
                cost.C += 1
            elif symbol == "X":
                pass
            elif "/" in symbol:
                colors = symbol.split("/")
                if "P" in colors:
                    color = [c for c in colors if c != "P"][0]
                    setattr(cost, color, getattr(cost, color) + 1)
                else:
                    # setattr(cost, colors[0], getattr(cost, colors[0]) + 1)
                    # if its a number, then it is a generic cost
                    if colors[0].isdigit():
                        cost.generic += int(colors[0])
                    else:
                        setattr(cost, colors[0], getattr(cost, colors[0]) + 1)

        return cost


def is_card_playable(card_mana_cost: str, opponent_mana: ManaPool) -> bool:
    cost = ManaCost.from_string(card_mana_cost)
    return opponent_mana.can_pay(cost)


def enrich_cards_with_playability(cards: list[dict], opponent_mana: ManaPool) -> None:
    for card in cards:
        card["is_playable"] = is_card_playable(card.get("mana_cost", ""), opponent_mana)


def enrich_decks_with_playability(decks: list[dict], opponent_mana: ManaPool) -> None:
    for deck in decks:
        enrich_cards_with_playability(deck.get("cards", []), opponent_mana)


##############################################################################
# Routes #####################################################################
##############################################################################


@app.get("/", response_class=HTMLResponse)
async def list_follow(request: Request, conn: DBConnDep):
    cursor = conn.cursor()
    decks = await get_decks(cursor)
    return templates.TemplateResponse(
        request=request, name="follow.html", context={"decks": decks}
    )


@app.get("/untapped", response_class=HTMLResponse)
async def list_untapped(request: Request, conn: DBConnDep):
    cursor = conn.cursor()
    decks = await get_decks(cursor)
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
                        current_deck_cards, missing_ids = fetch_current_deck_cards(cursor, arena_ids)
                        card_count_by_name = build_card_count_map(arena_ids, current_deck_cards)
                        matching_decks = find_matching_decks(cursor, current_deck_cards)
                        enrich_decks_with_cards(cursor, matching_decks, card_count_by_name)

                        for deck in matching_decks:
                            type_counts = {}
                            for card in deck.get('cards', []):
                                if 'types' in card:
                                    if card["types"]:
                                        card_types = card['types'].strip().lower()
                                        type_counts[card_types] = type_counts.get(card_types, 0) + 1
                            deck['type_counts'] = type_counts
                    else:
                        current_deck_cards = []
                        matching_decks = []

                    # get opponent mana from current_deck_cards lands using produced_mana, mana can be gained only one
                    lands_dict = {}
                    for card in current_deck_cards:
                        if card['types'] == 'Land':
                            if card['produced_mana']:
                                for color in card['produced_mana'].split(','):
                                    lands_dict[color] = 1

                    opponent_mana = ManaPool(**lands_dict)

                    # opponent_mana = ManaPool(W=2, U=1, B=0, R=0, G=1, C=1)

                    enrich_decks_with_playability(matching_decks, opponent_mana)

                    html_content = templates.get_template("list_cards.html").render(
                        cards=current_deck_cards,
                        matching_decks=matching_decks,
                        opponent_mana=opponent_mana,
                        missing_ids=missing_ids
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
        urls = list(set(urls))
        data = await build_untapped_decks_api_urls(urls)

        try:
            decks = await fetch_untapped_decks_from_api(conn=conn, cookies=None, untapped_decks=data)
        except Exception as e:
            decks = []

        cursor = conn.cursor()
        await add_decks_to_db(conn, decks)
        added_decks = await get_decks(cursor)

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

    # print(f"Found {len(result['deck_urls'])} deck URLs")
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


def fetch_current_deck_cards(cursor, arena_ids: list[str]) -> tuple[list[dict], list[str]]:
    if not arena_ids:
        return [], []

    placeholders = ", ".join("?" * len(arena_ids))
    query = f"""
        SELECT DISTINCT name, mana_cost, type_line, arena_id, id, printed_name, flavor_name, produced_mana
        FROM scryfall_all_cards 
        WHERE arena_id IN ({placeholders})
    """
    cursor.execute(query, arena_ids)

    cards = [dict(row) for row in cursor.fetchall()]

    found_ids = list(set([card["arena_id"] for card in cards]))

    missing_ids = list(set(arena_ids) - set(found_ids))

    if missing_ids:
        # print(f"Missing {len(missing_ids)} cards: {missing_ids}")
        _placeholders = ", ".join("?" * len(missing_ids))
        _query = f"""
            SELECT DISTINCT name, CAST(id as VARCHAR(20)) as arena_id FROM '17lands'
            WHERE id IN ({_placeholders})
        """
        cursor.execute(_query, missing_ids)
        missing_cards = [dict(row) for row in cursor.fetchall()]

        for card in missing_cards:
            __query = "SELECT name, mana_cost, type_line, arena_id, id, printed_name, flavor_name, produced_mana FROM scryfall_all_cards WHERE name = ? LIMIT 1"
            cursor.execute(__query, (card["name"],))
            result = cursor.fetchone()
            if not result:
                __query = "SELECT name, mana_cost, type_line, arena_id, id, printed_name, flavor_name, produced_mana FROM scryfall_all_cards WHERE printed_name = ? OR flavor_name = ? LIMIT 1"
                cursor.execute(__query, (card["name"], card["name"]))
                result = cursor.fetchone()

            if result:
                card["name"] = result["name"]
                card["mana_cost"] = result["mana_cost"]
                card["type_line"] = result["type_line"]
                card["id"] = result["id"]
                card["printed_name"] = result["printed_name"]
                card["flavor_name"] = result["flavor_name"]
                card["produced_mana"] = result["produced_mana"]
                card["arena_id"] = result["arena_id"]

            missing_ids = list(set(missing_ids) - set([card["arena_id"] for card in missing_cards]))

        if missing_ids:
            print(f"Missing {len(missing_ids)} cards: {missing_ids}")

        cards.extend(missing_cards)

    id_counts = Counter(arena_ids)
    for card in cards:
        card["count"] = id_counts.get(card["arena_id"], 0)
        card['super_types'], card['types'], card['sub_types'] = parse_card_types(card['type_line'])
        card['mana_cost_value'], card['mana_cost_tags'] = calculate_mana_cost_value(card['mana_cost'])

    return cards, missing_ids


def build_card_count_map(arena_ids: list[str], cards: list[dict]) -> dict[str, int]:
    id_counts = Counter(arena_ids)
    card_count_map = {}

    for card in cards:
        card_count_map[card["name"]] = id_counts.get(card["arena_id"], 1)

    return card_count_map


def find_matching_decks(cursor, current_cards: list[dict]) -> list[dict]:
    if not current_cards:
        return []

    unique_card_names = list(set(card['name'] for card in current_cards))
    placeholders = ", ".join("?" * len(unique_card_names))

    query_2 = f"""
        SELECT DISTINCT 
            d.id, 
            d.name, 
            d.source, 
            d.url,
            COUNT(DISTINCT dc.card_id) as matched_cards,
            (SELECT COUNT(*) FROM deck_cards WHERE deck_id = d.id) as total_deck_cards
        FROM decks d
        inner JOIN deck_cards dc ON d.id = dc.deck_id
        inner JOIN scryfall_all_cards c ON dc.card_id = c.id
        WHERE c.name IN ({placeholders}) 
        GROUP BY d.id
        ORDER BY matched_cards DESC
        limit 3
    """
    cursor.execute(query_2, unique_card_names)
    cards = [dict(row) for row in cursor.fetchall()]

    if len(cards) < 3:
        query_2 = f"""
        SELECT DISTINCT d.id,
                        d.name,
                        d.source,
                        d.url,
                        COUNT(DISTINCT dc.name)                                as matched_cards,
                        (SELECT COUNT(*) FROM deck_cards WHERE deck_id = d.id) as total_deck_cards
        FROM decks d
                 inner JOIN deck_cards dc ON d.id = dc.deck_id
                 inner JOIN scryfall_all_cards c ON dc.name = c.name
        WHERE c.name IN ({placeholders}) and d.format = 'standard' and total_deck_cards <= 100 and source in ('17lands.com', 'mtgazone.com')
        GROUP BY d.id
        ORDER BY matched_cards DESC
        limit 3
        """
        cursor.execute(query_2, unique_card_names)
        # cards = [dict(row) for row in cursor.fetchall()]
        cards.extend([dict(row) for row in cursor.fetchall()])

    # cards = [card for card in cards if card["component"] != "combo_piece"]
    return cards


def calculate_mana_cost_value(mana_cost: str) -> tuple[int, str]:
    value = 0
    mana_tags = ""
    if not mana_cost:
        return value, mana_tags

    for i in range(len(mana_cost)):
        if mana_cost[i] == '{' and not mana_cost[i + 1].isdigit():
            value += 1
            mana_tags += '<i class="ms ms-' + mana_cost[i + 1].lower() + ' ms-cost ms-shadow"></i> '
        if mana_cost[i].isdigit():
            value += int(mana_cost[i])
            mana_tags += '<i class="ms ms-' + mana_cost[i].lower() + ' ms-cost ms-shadow"></i> '

    return value, mana_tags.strip()


def enrich_decks_with_cards(cursor, decks: list[dict], card_count_map: dict[str, int]) -> None:
    for deck in decks:
        deck_cards_query = """
            SELECT c.name, dc.quantity, c.mana_cost, c.type_line, c.arena_id, c.id, c.component
            FROM deck_cards dc
            JOIN scryfall_all_cards c ON dc.card_id = c.id
            WHERE dc.deck_id = ?
            ORDER BY c.name
        """
        cursor.execute(deck_cards_query, (deck['id'],))
        deck['cards'] = [dict(row) for row in cursor.fetchall()]
        deck['cards'] = [card for card in deck['cards'] if card['component'] != "combo_piece"]

        if len(deck["cards"]) == 0:
            deck_cards_query = """
                SELECT c.name, dc.quantity, c.mana_cost, c.type_line, c.arena_id, c.id, c.component
                FROM deck_cards dc
                JOIN scryfall_all_cards c ON dc.name = c.name
                WHERE dc.deck_id = ?
                GROUP BY c.name
                ORDER BY c.name
            """
            cursor.execute(deck_cards_query, (deck['id'],))
            deck['cards'] = [dict(row) for row in cursor.fetchall()]
            deck['cards'] = [card for card in deck['cards'] if card['component'] != "combo_piece"]

        # calculate mana_cost_value
        for card in deck['cards']:
            card['mana_cost_value'], card['mana_cost_tags'] = calculate_mana_cost_value(card['mana_cost'])

        # use parse_card_types to get the super, type, and sub types
        for card in deck['cards']:
            card['super_types'], card['types'], card['sub_types'] = parse_card_types(card['type_line'])

        for card in deck['cards']:
            card['current_count'] = card_count_map.get(card['name'], 0)


def parse_card_types(card_type: str) -> Tuple[List[str], str, List[str]]:
    """
    https://github.com/mtgjson/mtgjson/blob/793b6b0fd1d591d77463684c52627e2963c3fd33/mtgjson5/set_builder.py#L138
    """
    if not card_type:
        return [], "", []
    sub_types: List[str] = []
    super_types: List[str] = []
    types: List[str] = []
    MULTI_WORD_SUB_TYPES: Set[str] = {"Time Lord"}
    SUPER_TYPES: Set[str] = {"Basic", "Host", "Legendary", "Ongoing", "Snow", "World"}
    # BASIC_LAND_NAMES: Set[str] = {"Plains", "Island", "Swamp", "Mountain", "Forest"}
    supertypes_and_types: str
    if "—" not in card_type:
        supertypes_and_types = card_type
    else:
        split_type: List[str] = card_type.split("—")
        supertypes_and_types = split_type[0]
        subtypes: str = split_type[1]

        # Planes are an entire sub-type, whereas normal cards
        # are split by spaces... until they aren't #WHO
        if card_type.startswith("Plane"):
            sub_types = [subtypes.strip()]
        else:
            special_case_found = False
            for special_case in MULTI_WORD_SUB_TYPES:
                if special_case in subtypes:
                    subtypes = subtypes.replace(
                        special_case, special_case.replace(" ", "!")
                    )
                    special_case_found = True

            sub_types = [x.strip() for x in subtypes.split() if x]
            if special_case_found:
                for i, sub_type in enumerate(sub_types):
                    sub_types[i] = sub_type.replace("!", " ")

    for value in supertypes_and_types.split():
        if value in SUPER_TYPES:
            super_types.append(value)
        elif value:
            types.append(value)

    # return types as string 
    return super_types, " ".join(types), sub_types


async def build_untapped_decks_api_urls(deck_urls: list) -> list[tuple[str, str, str]]:
    base_api_url = "https://api.mtga.untapped.gg/api/v1/decks/pricing/cardkingdom/"
    UntappedDeck = namedtuple("Deck", ["name", "url", "api_url"])
    untapped_decks = []
    for deck_url in deck_urls:
        deck_parts = deck_url.split("/")
        if len(deck_parts) >= 2:
            untapped_decks.append(UntappedDeck(deck_parts[-2], deck_url, base_api_url + deck_parts[-1]))

    return untapped_decks


async def fetch_untapped_decks_from_api(conn: DBConnDep, cookies: dict | None, untapped_decks: list) -> list[dict]:
    import httpx

    if not cookies:
        cursor = conn.cursor()
        cursor.execute("SELECT session_id, csrf_token FROM user_info ORDER BY added_at DESC LIMIT 1")
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
                decks.append({"name": name, "url": url, "cards": [], "error": str(e)})
            except httpx.RequestError as e:
                print(f"Request failed for {name}: {e}")
                decks.append({"name": name, "url": url, "cards": [], "error": str(e)})
            except ValueError as e:
                print(f"JSON decode failed for {name}: {e}")
                decks.append({"name": name, "url": url, "cards": [], "error": "Invalid JSON"})

    return decks


async def fetch_untapped_decks_from_html(conn, data: dict) -> list[dict]:
    cookies = data.get("cookies", {})
    if not cookies:
        raise ValueError("No cookies provided for API requests")

    untapped_decks = await build_untapped_decks_api_urls(data["deck_urls"])

    cookies = {
        "session_id": data["cookies"]["session_id"],
        "csrf_token": data["cookies"]["csrf_token"],
    }

    try:
        decks = await fetch_untapped_decks_from_api(conn, cookies, untapped_decks)
    except Exception as e:
        decks = []

    return decks


async def add_decks_to_db(conn: sqlite3.Connection, decks: list) -> None:
    cursor = conn.cursor()

    for deck in decks:
        if deck.get("error"):
            print(f"Skipping deck {deck['name']} due to error: {deck['error']}")
            continue

        # TODO
        # base_64_decklist

        try:
            cursor.execute(
                "INSERT INTO decks (name, source, url, added_at) VALUES (?, ?, ?, ?)",
                (deck["name"], "untapped", deck["url"], datetime.now())
            )
        except sqlite3.IntegrityError:
            print(f"Deck {deck['name']} already exists in database")
            continue
        except Exception as e:
            print(f"Error adding deck {deck['name']} to database: {e}")
            continue

        deck_id = cursor.lastrowid

        for card in deck.get("cards", []):
            cursor.execute(
                "SELECT id FROM scryfall_all_cards WHERE name = ?",
                (card["name"],)
            )
            result = cursor.fetchone()

            if not result:
                print(f"Card {card['name']} not found in database")
                # use like query to search in printed_name, flavor_name
                cursor.execute("SELECT id FROM scryfall_all_cards WHERE printed_name LIKE ? OR flavor_name LIKE ?",
                               (card["name"], card["name"]))
                result = cursor.fetchone()

            card_id = result[0]
            cursor.execute(
                "INSERT OR IGNORE INTO deck_cards (deck_id, card_id, quantity, name, section) VALUES (?, ?, ?, ?, ?)",
                (deck_id, card_id, card.get("qty", 1), card["name"], "main")
            )
            conn.commit()


async def add_decks_by_html(conn: sqlite3.Connection, data: dict) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO user_info (sessionid, csrfToken, added_at) VALUES (?, ?, ?)",
        (data["cookies"]["session_id"], data["cookies"]["csrf_token"], datetime.now())
    )
    conn.commit()

    decks = await fetch_untapped_decks_from_html(conn, data)

    await add_decks_to_db(conn, decks)


async def get_decks(cursor: sqlite3.Cursor) -> list[dict]:
    cursor.execute("""
    SELECT d.id        as deck_id,
           d.name      as deck_name,
           d.source    as deck_source,
           d.url       as deck_url,
           c.name      as name,
           dc.quantity as quantity,
           c.mana_cost as mana_cost,
           c.type_line as type_line,
           c.component as component
    FROM decks d
             INNER JOIN deck_cards dc
                        ON d.id = dc.deck_id
             Inner JOIN scryfall_all_cards c
                       ON dc.card_id = c.id
    ORDER BY added_at DESC;
    """)
    rows = cursor.fetchall()

    cards = [dict(row) for row in rows]
    decks = {}

    # remove cards with the same names and has component = combo_piece
    cards = [card for card in cards if card["component"] != "combo_piece"]

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
            "mana_cost": card["mana_cost"],
            "type_line": card["type_line"]
        }
        decks[deck_id]["cards"].append(card_info)

    return list(decks.values())
