import logging
from typing import Tuple, List, Set

import httpx

logger = logging.getLogger(__name__)

MULTI_WORD_SUB_TYPES: Set[str] = {"Time Lord"}
SUPER_TYPES: Set[str] = {"Basic", "Host", "Legendary", "Ongoing", "Snow", "World"}


def parse_card_types(card_type: str) -> Tuple[List[str], str, List[str]]:
    if not card_type:
        return [], "", []
    sub_types: List[str] = []
    super_types: List[str] = []
    types: List[str] = []

    supertypes_and_types: str
    if "—" not in card_type:
        supertypes_and_types = card_type
    else:
        split_type: List[str] = card_type.split("—")
        supertypes_and_types = split_type[0]
        subtypes: str = split_type[1]

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

    return super_types, " ".join(types), sub_types


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


async def fetch_missing_cards_from_17lands(ids: list[str]) -> tuple[list[dict], list[str]] | None:
    missing_ids_str = ",".join(ids)
    url = f"https://www.17lands.com/data/cards?ids={missing_ids_str}"

    logger.debug("Fetching cards from 17lands", extra={"count": len(ids)})

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            response_json = response.json()
            cards = response_json.get("cards", [])
            found_ids = [str(c["id"]) for c in cards]
            logger.info(
                "Fetched cards from 17lands",
                extra={"requested": len(ids), "found": len(found_ids)},
            )
            return cards, found_ids
        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error from 17lands",
                extra={"status_code": e.response.status_code, "url": url},
            )
        except httpx.RequestError as e:
            logger.error("Request to 17lands failed", extra={"error": str(e)})
        except ValueError as e:
            logger.error("JSON decode failed for 17lands response", extra={"error": str(e)})

    return None