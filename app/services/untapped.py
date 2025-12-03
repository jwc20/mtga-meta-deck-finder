import aiosqlite
import asyncio
from collections import namedtuple
from datetime import datetime

from app.services.decks import add_decks_to_db


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

    return result


async def build_untapped_decks_api_urls(deck_urls: list) -> list[tuple[str, str, str]]:
    base_api_url = "https://api.mtga.untapped.gg/api/v1/decks/pricing/cardkingdom/"
    UntappedDeck = namedtuple("Deck", ["name", "url", "api_url"])
    untapped_decks = []
    for deck_url in deck_urls:
        deck_parts = deck_url.split("/")
        if len(deck_parts) >= 2:
            untapped_decks.append(UntappedDeck(deck_parts[-2], deck_url, base_api_url + deck_parts[-1]))

    return untapped_decks


async def fetch_untapped_decks_from_api(cursor: aiosqlite.Cursor, cookies: dict | None, untapped_decks: list) -> list[dict]:
    import httpx

    if not cookies:
        await cursor.execute("SELECT session_id, csrf_token FROM user_info ORDER BY added_at DESC LIMIT 1")
        cookies_row = await cursor.fetchone()
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


            # TODO: use logger
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


async def fetch_untapped_decks_from_html(cursor: aiosqlite.Cursor, data: dict) -> list[dict]:
    cookies = data.get("cookies", {})
    if not cookies:
        raise ValueError("No cookies provided for API requests")

    untapped_decks = await build_untapped_decks_api_urls(data["deck_urls"])

    cookies = {
        "session_id": data["cookies"]["session_id"],
        "csrf_token": data["cookies"]["csrf_token"],
    }
    
    try:
        decks = await fetch_untapped_decks_from_api(cursor=cursor, cookies=cookies, untapped_decks=untapped_decks)
    except Exception as e:
        decks = []

    return decks


async def add_decks_by_html(conn: aiosqlite.Connection, data: dict) -> None:
    cursor = await conn.cursor()
    
    try:
        session_id = data["cookies"]["session_id"]
        csrf_token = data["cookies"]["csrf_token"]
        cursor.execute("SELECT id FROM user_info where session_id = ? and csrf_token = ?", (session_id, csrf_token))
        user_info = await cursor.fetchone()
        
        if not user_info:
            await cursor.execute(
                "INSERT INTO user_info (session_id, csrf_token, added_at) VALUES (?, ?, ?)",
                (session_id, csrf_token, datetime.now())
            )
            await conn.commit()
            decks = await fetch_untapped_decks_from_html(cursor=cursor, data=data)
            await add_decks_to_db(conn, decks)
    except Exception as e:
        print(f"Error adding decks: {e}")
        