import asyncio

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from app.database import get_db
from app.models import ManaPool
from app.services.logs import (
    get_last_log_line,
    parse_arena_ids_from_log,
    get_log_line_count,
    get_last_processed_count,
    set_last_processed_count,
)
from app.services.cards import (
    fetch_current_deck_cards,
    build_card_count_map,
    find_matching_decks,
    enrich_decks_with_cards, update_current_deck_cards,
)
from app.utils.cards import fetch_missing_cards_from_17lands
from app.utils.mana import enrich_decks_with_playability
from app.templates import templates

router = APIRouter()


@router.get("/check-logs")
async def check_logs_stream(request: Request):
    conn = get_db()

    async def event_generator():
        cursor = conn.cursor()

        try:
            while True:
                if await request.is_disconnected():
                    break

                last_log_entry = get_last_log_line()
                log_line_count = get_log_line_count()
                last_processed_log_line_count = get_last_processed_count()

                if log_line_count != last_processed_log_line_count:
                    set_last_processed_count(log_line_count)

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
                        missing_ids = []

                    lands_dict = {}
                    for card in current_deck_cards:
                        if card['types'] == 'Land':
                            if card['produced_mana']:
                                for color in card['produced_mana'].split(','):
                                    lands_dict[color] = 1

                    opponent_mana = ManaPool(**lands_dict)

                    enrich_decks_with_playability(matching_decks, opponent_mana)
                    
                    
                    # handle cards with missing ids
                    print(f"Missing {len(missing_ids)} cards: {missing_ids}")
                    if missing_ids:
                        found_cards = await fetch_missing_cards_from_17lands(missing_ids)
                        if found_cards:
                            await update_current_deck_cards(conn, found_cards)

                    html_content = templates.get_template("list_cards.html").render(
                        cards=current_deck_cards,
                        matching_decks=matching_decks,
                        opponent_mana=opponent_mana,
                    )

                    yield {
                        "event": "log-update",
                        "data": html_content.replace("\n", " ")
                    }

                await asyncio.sleep(1)
        finally:
            conn.close()

    return EventSourceResponse(event_generator())