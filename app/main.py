import sqlite3
from collections import defaultdict, namedtuple
from contextlib import asynccontextmanager
from typing import Annotated, DefaultDict

from pydantic import BaseModel, Field

from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pathlib import Path
from datetime import datetime


##############################################################################

def find_project_root(marker=".git"):
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    return current.parent


project_root = find_project_root()
db_path = project_root / "database.db"
schema_path = project_root / "app/schema.sql"
template_path = project_root / "app/templates"


##############################################################################

class DeckBase(BaseModel):
    name: str


class Deck(DeckBase):
    id: int | None = None
    source: str | None = None
    added_at: datetime = Field(default_factory=datetime.now)


class CardBase(BaseModel):
    name: str
    manaCost: str | None = None
    manaValue: float | None = None
    power: str | None = None
    originalText: str | None = None
    type: str | None = None
    types: str | None = None
    mtgArenaId: str | None = None
    scryfallId: str | None = None
    availability: str | None = None
    colors: str | None = None
    keywords: str | None = None


class Card(CardBase):
    id: int | None = None
    name: str | None = None


class DeckCardBase(BaseModel):
    deck_id: int
    card_id: int
    quantity: int


class DeckCard(DeckCardBase):
    id: int | None = None


##############################################################################

def get_db():
    conn = sqlite3.connect(db_path)
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

def add_cors_middleware(fastapi_app):
    return CORSMiddleware(
        app=fastapi_app,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


##############################################################################

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield
    print("shutting down")


app = FastAPI(lifespan=lifespan)
app.add_middleware(add_cors_middleware)
templates = Jinja2Templates(directory=template_path)


@app.middleware("http")
async def add_logging_middleware(request: Request, call_next):
    print(f"Request path: {request.url.path}")
    response: Response = await call_next(request)
    print(f"Response status: {response.status_code}")
    return response


##############################################################################
# Routes
##############################################################################
@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request, name="base.html"
    )


@app.post("/todos", response_class=HTMLResponse)
async def create_todo(request: Request, todo: Annotated[str, Form()]):
    print(todo)


@app.get("/untapped", response_class=HTMLResponse)
async def untapped(request: Request):
    return templates.TemplateResponse(
        request=request, name="untapped.html"
    )


@app.post("/add/untapped-decks")
async def add_untapped_decks_route(request: Request, conn: DBConnDep, html_doc: Annotated[str, Form(...)]):
    # 1 parse html_doc
    data = await parse_untapped_html(html_doc)

    # 2 fetch deck lists
    # 3 add decks to db
    new_decks = await add_decks_to_db(data)

    # print(html_str)

    return templates.TemplateResponse(
        request=request, name="untapped.html", context={"decks": []}
    )


async def fetch_decks(data: dict):
    import httpx
    import jsonpickle

    # 2. set cookies
    cookies = data["cookies"]
    params = {
        "format": "json"
    }

    # 1. build api urls 
    base_api_url = "https://api.mtga.untapped.gg/api/v1/decks/pricing/cardkingdom/"

    UntappedDeck = namedtuple("Deck", ["name", "url"])
    _api_urls = []
    for deck_url in data["deck_urls"]:
        _api_urls.append(UntappedDeck(deck_url.split("/")[-2], base_api_url + deck_url.split("/")[-1]))

    # 3. fetch deck lists
    # decks = {}
    # async with httpx.AsyncClient() as client:
    #     for name, url in _api_urls:
    #         response = await client.get(url, cookies=cookies, params=params)
    #         response.raise_for_status()
    #         decks[name] = {
    #             "name": name,
    #             "url": url,
    #             "cards": response.json()
    #         }
    decks = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, url in _api_urls:
            try:
                response = await client.get(url, cookies=cookies, params=params)
                response.raise_for_status()

                decks[name] = {
                    "name": name,
                    "url": url,
                    "cards": response.json()
                }
                return decks
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


# 
# async def add_decks_to_db(data: dict):
#     decks = await fetch_decks(data)
# 
#     conn = get_db()
#     cursor = conn.cursor()
# 
#     try:
#         for deck in decks.values():
#             cursor.execute("INSERT INTO decks (name, source, added_at) VALUES (?, ?, ?)",
#                            (deck["name"], "untapped", datetime.now()))
#             deck_id = cursor.lastrowid
#             for card in deck["cards"]:
#                 
#                 # TODO: logic for getting card id from card name
#                 # cursor.execute("INSERT INTO deck_cards (deck_id, card_id, quantity) VALUES (?, ?, ?)",
#                 #                (deck_id, card["id"], card["quantity"]))
# 
#         conn.commit()
#     finally:
#         conn.close()
#         
#     return decks

async def add_decks_to_db(data: dict):
    decks = await fetch_decks(data)

    conn = get_db()
    cursor = conn.cursor()

    try:
        for deck in decks.values():
            cursor.execute("INSERT INTO decks (name, source, added_at) VALUES (?, ?, ?)",
                           (deck["name"], "untapped", datetime.now()))
            deck_id = cursor.lastrowid

            for card in deck["cards"]:
                unique_id = card.get("scryfallId") or card.get("mtgArenaId")

                if unique_id:
                    cursor.execute("SELECT id FROM cards WHERE scryfallId = ? OR mtgArenaId = ?",
                                   (card.get("scryfallId"), card.get("mtgArenaId")))
                else:
                    cursor.execute("SELECT id FROM cards WHERE name = ? AND manaCost = ? AND type = ?",
                                   (card["name"], card.get("manaCost"), card.get("type")))

                result = cursor.fetchone()

                if result:
                    card_id = result[0]
                else:
                    cursor.execute(
                        "INSERT INTO cards (name, manaCost, manaValue, power, originalText, type, types, mtgArenaId, scryfallId, availability, colors, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (card["name"], card.get("manaCost"), card.get("manaValue"), card.get("power"),
                         card.get("originalText"), card.get("type"), card.get("types"), card.get("mtgArenaId"),
                         card.get("scryfallId"), card.get("availability"), card.get("colors"), card.get("keywords"))
                    )
                    card_id = cursor.lastrowid

                cursor.execute("INSERT INTO deck_cards (deck_id, card_id, quantity) VALUES (?, ?, ?)",
                               (deck_id, card_id, card.get("qty", 1)))

        conn.commit()
    finally:
        conn.close()


async def parse_untapped_html(html_doc: str):
    """get cookies and deck urls"""
    from bs4 import BeautifulSoup
    import jsonpickle
    result = {}
    soup = BeautifulSoup(html_doc, 'html.parser')

    _next_data_raw = soup.find("script", type="application/json", id="__NEXT_DATA__")
    _next_data_dict = jsonpickle.decode(_next_data_raw.string)

    # get cookies for api requests
    _cookie_header = _next_data_dict["props"]["cookieHeader"].split(";")
    result["cookies"] = {}
    for cookie in _cookie_header:
        if "sessionid" in cookie:
            result["cookies"]["session_id"] = cookie.split("=")[1]
        if "csrftoken" in cookie:
            result["cookies"]["csrf_token"] = cookie.split("=")[1]

    # get deck urls
    _deck_tags = soup.find_all("a", class_="sc-bf50840f-1 ptaNk")
    result["deck_urls"] = list(set([dt.get("href") for dt in _deck_tags]))
    print(result)

    return result


##############################################################################
# API
##############################################################################


@app.get("/decks")
def get_decks(conn: DBConnDep):
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, added_at FROM decks")
    return [dict(row) for row in cursor.fetchall()]


@app.get("/cards")
def get_cards(conn: DBConnDep):
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM cards limit 100")
    return [dict(row) for row in cursor.fetchall()]
