from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.database import DBConnDep
from app.services.decks import get_decks
from app.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def list_follow(request: Request, conn: DBConnDep):
    cursor = conn.cursor()
    decks = await get_decks(cursor)
    return templates.TemplateResponse(
        request=request, name="follow.html", context={"decks": decks}
    )


@router.get("/untapped", response_class=HTMLResponse)
async def list_untapped(request: Request, conn: DBConnDep):
    cursor = conn.cursor()
    decks = await get_decks(cursor)
    return templates.TemplateResponse(
        request=request, name="untapped.html", context={"decks": decks}
    )
