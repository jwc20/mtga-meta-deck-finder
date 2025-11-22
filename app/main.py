import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated

from pydantic import BaseModel, Field

from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response

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
schema_path = Path(__file__).resolve().parent / "schema.sql"


##############################################################################

class DeckBase(BaseModel):
    name: str


class Deck(DeckBase):
    id: int | None = None
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


@app.middleware("http")
async def add_logging_middleware(request: Request, call_next):
    print(f"Request path: {request.url.path}")
    response: Response = await call_next(request)
    print(f"Response status: {response.status_code}")
    return response


##############################################################################


@app.get("/")
def root():
    return {"Hello": "World"}


@app.get("/decks")
def get_decks(conn: DBConnDep):
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, added_at FROM decks")
    return [dict(row) for row in cursor.fetchall()]


@app.get("/cards")
def get_cards(conn: DBConnDep):
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM cards limit 10")
    return [dict(row) for row in cursor.fetchall()]
