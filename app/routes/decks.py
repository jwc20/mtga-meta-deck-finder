from typing import Annotated

from fastapi import APIRouter, Request, Form, HTTPException
from starlette import status
from starlette.responses import RedirectResponse, Response

from app.database import DBConnDep
from app.services.decks import get_decks, add_decks_to_db, delete_deck
from app.services.untapped import (
    parse_untapped_html,
    build_untapped_decks_api_urls,
    fetch_untapped_decks_from_api,
    add_decks_by_html,
)
from app.templates import templates

router = APIRouter()



@router.delete("/remove/{deck_id}")
async def delete_deck_route(conn: DBConnDep, deck_id: int):
    await delete_deck(conn, deck_id)
    return Response(status_code=200)


@router.post("/add/untapped-decks-urls")
async def add_untapped_decks_url_list_route(
        request: Request,
        conn: DBConnDep,
        url_list: Annotated[str, Form(...)]
):
    try:
        print(url_list)
        urls = url_list.split("\n")
        urls = list(set(urls))
        data = await build_untapped_decks_api_urls(urls)
        cursor = await conn.cursor()

        try:
            decks = await fetch_untapped_decks_from_api(cursor=cursor, cookies=None, untapped_decks=data)
        except Exception as e:
            decks = []

        await add_decks_to_db(conn, decks)
        added_decks = await get_decks(cursor)

        return templates.TemplateResponse(
            request=request, name="untapped.html", context={"decks": added_decks}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing decks: {str(e)}")


@router.post("/add/untapped-decks-html")
async def add_untapped_decks_html_route(
        request: Request,
        conn: DBConnDep,
        html_doc: Annotated[str, Form(...)]
):
    try:
        data = await parse_untapped_html(html_doc)
        await add_decks_by_html(conn, data)
        cursor = await conn.cursor()
        decks = await get_decks(cursor)
        return templates.TemplateResponse(
            request=request, name="untapped.html", context={"decks": decks}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing decks: {str(e)}")
