import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from app.database import get_db
from app.models import ManaPool
from app.services.logs import (
    get_last_log_line,
    get_log_line_count,
    get_last_processed_count,
    set_last_processed_count,
    LogEntry,
    LogState,
)
from app.services.cards import (
    fetch_current_deck_cards,
    build_card_count_map,
    find_matching_decks,
    enrich_decks_with_cards,
    update_current_deck_cards,
)
from app.utils.cards import fetch_missing_cards_from_17lands
from app.utils.mana import enrich_decks_with_playability
from app.templates import templates

BASIC_MANA_ABILITY_MAP = {1001: "W", 1002: "U", 1003: "B", 1004: "R", 1005: "G"}
ANNOTATION_MANA_MAP = {1: "W", 2: "U", 4: "B", 8: "R", 16: "G"}

router = APIRouter()

logger = logging.getLogger(__name__)


def parse_log_entry(log_entry: LogEntry, last_log_entry: str) -> None:
    if "cards" in last_log_entry:
        log_entry.parse_cards_log_line(last_log_entry)
    elif "actions" in last_log_entry:
        log_entry.parse_actions_log_line(last_log_entry)
    elif "annotations" in last_log_entry:
        log_entry.parse_annotations_log_line(last_log_entry)


async def process_missing_cards(conn, cursor, arena_ids: list[str]) -> tuple[list[dict], list[str]]:
    current_deck_cards, missing_ids = fetch_current_deck_cards(cursor, arena_ids)

    if not missing_ids:
        return current_deck_cards, missing_ids

    logger.info("Fetching missing cards", extra={"count": len(missing_ids), "ids": missing_ids})
    found_cards, found_ids = await fetch_missing_cards_from_17lands(missing_ids)
    missing_ids = list(set(missing_ids) - set(found_ids))

    if found_cards:
        await update_current_deck_cards(conn, found_cards)

    return current_deck_cards, missing_ids


def compute_deck_type_counts(decks: list[dict]) -> None:
    for deck in decks:
        type_counts = {}
        for card in deck.get("cards", []):
            card_types = card.get("types")
            if card_types:
                normalized_type = card_types.strip().lower()
                type_counts[normalized_type] = type_counts.get(normalized_type, 0) + 1
        deck["type_counts"] = type_counts


def build_opponent_mana_from_actions(actions_log: list[dict]) -> dict[str, int]:
    mana_dict = defaultdict(int)

    if not actions_log:
        return dict(mana_dict)

    logger.debug("Updating opponent mana from actions")
    for action in actions_log:
        if action.get("actionType") != "ActionType_Activate_Mana":
            continue
        ability_id = action.get("abilityGrpId")
        if ability_id in BASIC_MANA_ABILITY_MAP:
            mana_dict[BASIC_MANA_ABILITY_MAP[ability_id]] += 1

    return dict(mana_dict)


def update_mana_from_annotations(mana_dict: dict[str, int], annotations_log: list[dict]) -> dict[str, int]:
    if not annotations_log:
        return mana_dict

    logger.debug("Updating mana from annotations")
    result = defaultdict(int, mana_dict)

    for annotation in annotations_log:
        for value in annotation.get("values", []):
            if value in ANNOTATION_MANA_MAP:
                result[ANNOTATION_MANA_MAP[value]] += 1

    return dict(result)


def build_mana_tags(mana_pool: ManaPool) -> list[tuple[str, int]]:
    tags = []
    for color, count in mana_pool.to_list_tuple():
        tag = f'<i class="ms ms-{color.lower()} ms-cost ms-shadow"></i>'
        tags.append((tag, count))
    return tags


def render_log_update_html(
        current_deck_cards: list[dict],
        matching_decks: list[dict],
        opponent_mana_tags: list[tuple[str, int]],
        missing_ids: list[str],
) -> str:
    html_content = templates.get_template("list_cards.html").render(
        cards=current_deck_cards,
        matching_decks=matching_decks,
        opponent_mana=opponent_mana_tags,
        missing_ids=missing_ids,
    )
    return html_content.replace("\n", " ")


async def process_cards(conn, cursor, state: LogState) -> tuple[list[dict], list[dict], list[str]]:
    if not state.has_cards():
        return [], [], []

    logger.debug("Processing current deck cards")
    current_deck_cards, missing_ids = await process_missing_cards(conn, cursor, state.cards_log)
    card_count_by_name = build_card_count_map(state.cards_log, current_deck_cards)
    matching_decks = find_matching_decks(cursor, current_deck_cards)
    enrich_decks_with_cards(cursor, matching_decks, card_count_by_name)
    compute_deck_type_counts(matching_decks)

    return current_deck_cards, matching_decks, missing_ids


def process_mana(state: LogState) -> ManaPool:
    opponent_mana_dict = build_opponent_mana_from_actions(state.actions_log)
    opponent_mana_dict = update_mana_from_annotations(opponent_mana_dict, state.annotations_log)
    return ManaPool(**opponent_mana_dict)


async def process_log_update(conn, cursor, state: LogState) -> dict | None:
    if not state.has_cards():
        return None

    current_deck_cards, matching_decks, missing_ids = await process_cards(conn, cursor, state)
    opponent_mana = process_mana(state)
    enrich_decks_with_playability(matching_decks, opponent_mana)
    opponent_mana_tags = build_mana_tags(opponent_mana)

    return {
        "current_deck_cards": current_deck_cards,
        "matching_decks": matching_decks,
        "opponent_mana_tags": opponent_mana_tags,
        "missing_ids": missing_ids,
    }


def is_relevant_log_entry(log_entry: str) -> bool:
    return any(key in log_entry for key in ("cards", "actions", "annotations"))


@router.get("/check-logs")
async def check_logs_stream(request: Request):
    conn = get_db()

    async def event_generator():
        logger.info("SSE stream started")
        cursor = conn.cursor()
        log_entry = LogEntry()

        try:
            while True:
                if await request.is_disconnected():
                    logger.info("Client disconnected from SSE stream")
                    break

                last_log_entry = await get_last_log_line()
                log_line_count = await get_log_line_count()
                last_processed = await get_last_processed_count()

                if log_line_count == last_processed:
                    await asyncio.sleep(0.5)
                    continue

                await set_last_processed_count(log_line_count)

                if not is_relevant_log_entry(last_log_entry):
                    await asyncio.sleep(0.5)
                    continue

                parse_log_entry(log_entry, last_log_entry)

                state = log_entry.get_current_state()
                result = await process_log_update(conn, cursor, state)

                if result is None:
                    await asyncio.sleep(0.5)
                    continue

                html_content = render_log_update_html(
                    result["current_deck_cards"],
                    result["matching_decks"],
                    result["opponent_mana_tags"],
                    result["missing_ids"],
                )

                logger.debug(
                    "Sending log update",
                    extra={
                        "deck_count": len(result["matching_decks"]),
                        "card_count": len(result["current_deck_cards"]),
                    },
                )
                yield {"event": "log-update", "data": html_content}

                await asyncio.sleep(0.5)
        finally:
            logger.info("SSE stream closed")
            conn.close()

    return EventSourceResponse(event_generator())
