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
    LogEntry
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

        ##########################################################################################
        # TODO
        ##########################################################################################
        ##########################################################################################
        try:
            log_entry = LogEntry()
            arena_ids = log_entry.arena_ids
            actions_dict = log_entry.actions_dict

            while True:
                if await request.is_disconnected():
                    break

                last_log_entry = await get_last_log_line()
                log_line_count = await get_log_line_count()
                last_processed_log_line_count = await get_last_processed_count()

                if log_line_count != last_processed_log_line_count:
                    await set_last_processed_count(log_line_count)

                    if "cards" in last_log_entry or "actions" in last_log_entry:
                        if "cards" in last_log_entry:
                            arena_ids = log_entry.parse_cards_log_line(last_log_entry)
                            actions_dict = log_entry.actions_dict
                        if "actions" in last_log_entry:
                            actions_dict = log_entry.parse_actions_log_line(last_log_entry)
                            arena_ids = log_entry.arena_ids

                    if arena_ids:
                        current_deck_cards, missing_ids = fetch_current_deck_cards(cursor, log_entry.arena_ids)

                        # handle cards with missing ids
                        print(f"Missing {len(missing_ids)} cards: {missing_ids}")
                        if missing_ids:
                            found_cards, found_ids = await fetch_missing_cards_from_17lands(missing_ids)
                            missing_ids = list(set(missing_ids) - set(found_ids))
                            if found_cards:
                                await update_current_deck_cards(conn, found_cards)

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

                    opponent_mana_actions = {}
                    if actions_dict:
                        print(log_entry.actions_dict)
                        for action in actions_dict:
                            # type: ActionType_Activate_Mana, ActionType_Activate, 
                            if action.get("actionType") == "ActionType_Activate_Mana":
                                opponent_mana_actions[action.get("abilityGrpId")] = opponent_mana_actions.get(
                                    action.get("abilityGrpId"), 0) + 1
                            else:
                                print(action)

                    ##########################################################################################
                    ##########################################################################################
                    # TODO
                    # lands_dict = {}
                    # for card in current_deck_cards:
                    #     if card['types'] == 'Land':
                    #         if card['produced_mana']:
                    #             for color in card['produced_mana'].split(','):
                    #                 lands_dict[color] = 1
                    # 
                    # opponent_mana = ManaPool(**lands_dict)

                    
                    
                    opponent_mana_dict = {}
                    for ability_id, count in opponent_mana_actions.items():
                        if ability_id == 1001:
                            opponent_mana_dict["W"] = count
                        elif ability_id == 1002:
                            opponent_mana_dict["U"] = count
                        elif ability_id == 1003:
                            opponent_mana_dict["B"] = count
                        elif ability_id == 1004:
                            opponent_mana_dict["R"] = count
                        elif ability_id == 1005:
                            opponent_mana_dict["G"] = count

                    opponent_mana_2 = ManaPool(**opponent_mana_dict)

                    ##########################################################################################
                    ##########################################################################################

                    enrich_decks_with_playability(matching_decks, opponent_mana_2)

                    opponent_mana_tags = []
                    for color, count in opponent_mana_2.to_list_tuple():
                        _tag = f'<i class="ms ms-{color.lower()} ms-cost ms-shadow"></i>'
                        opponent_mana_tags.append((_tag, count))

                    html_content = templates.get_template("list_cards.html").render(
                        cards=current_deck_cards,
                        matching_decks=matching_decks,
                        opponent_mana=opponent_mana_tags,
                        missing_ids=missing_ids
                    )

                    yield {
                        "event": "log-update",
                        "data": html_content.replace("\n", " ")
                    }

                ######################################################################
                ######################################################################
                ######################################################################
                ######################################################################

                # if log_line_count != last_processed_log_line_count:
                #     set_last_processed_count(log_line_count)
                # 
                #     arena_ids = parse_arena_ids_from_log(last_log_entry)
                # 
                #     if arena_ids:
                #         current_deck_cards, missing_ids = fetch_current_deck_cards(cursor, arena_ids)
                # 
                #         # handle cards with missing ids
                #         print(f"Missing {len(missing_ids)} cards: {missing_ids}")
                #         if missing_ids:
                #             found_cards, found_ids = await fetch_missing_cards_from_17lands(missing_ids)
                #             missing_ids = list(set(missing_ids) - set(found_ids))
                #             if found_cards:
                #                 await update_current_deck_cards(conn, found_cards)
                # 
                #         card_count_by_name = build_card_count_map(arena_ids, current_deck_cards)
                #         matching_decks = find_matching_decks(cursor, current_deck_cards)
                #         enrich_decks_with_cards(cursor, matching_decks, card_count_by_name)
                # 
                #         for deck in matching_decks:
                #             type_counts = {}
                #             for card in deck.get('cards', []):
                #                 if 'types' in card:
                #                     if card["types"]:
                #                         card_types = card['types'].strip().lower()
                #                         type_counts[card_types] = type_counts.get(card_types, 0) + 1
                #             deck['type_counts'] = type_counts
                #     else:
                #         current_deck_cards = []
                #         matching_decks = []
                #         missing_ids = []
                # 
                #     
                #     lands_dict = {}
                #     for card in current_deck_cards:
                #         if card['types'] == 'Land':
                #             if card['produced_mana']:
                #                 for color in card['produced_mana'].split(','):
                #                     lands_dict[color] = 1
                #     ######################################################################
                # 
                #     opponent_mana = ManaPool(**lands_dict)
                # 
                #     enrich_decks_with_playability(matching_decks, opponent_mana)
                # 
                #     opponent_mana_tags = []
                #     for color, count in opponent_mana.to_list_tuple():
                #         _tag = f'<i class="ms ms-{color.lower()} ms-cost ms-shadow"></i>'
                #         opponent_mana_tags.append((_tag, count))
                # 
                #     html_content = templates.get_template("list_cards.html").render(
                #         cards=current_deck_cards,
                #         matching_decks=matching_decks,
                #         opponent_mana=opponent_mana_tags,
                #         missing_ids=missing_ids
                #     )
                # 
                #     yield {
                #         "event": "log-update",
                #         "data": html_content.replace("\n", " ")
                #     }

                await asyncio.sleep(0.5)
        finally:
            conn.close()

    return EventSourceResponse(event_generator())
