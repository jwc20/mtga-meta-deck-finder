import sqlite3
from collections import Counter, namedtuple

from app.utils.cards import parse_card_types, calculate_mana_cost_value


def fetch_current_deck_cards(cursor: sqlite3.Cursor, arena_ids: list[str]) -> tuple[list[dict], list[str]]:
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


def find_matching_decks(cursor: sqlite3.Cursor, current_cards: list[dict]) -> list[dict]:
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
        cards.extend([dict(row) for row in cursor.fetchall()])

    return cards


def enrich_decks_with_cards(cursor: sqlite3.Cursor, decks: list[dict], card_count_map: dict[str, int]) -> None:
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

        for card in deck['cards']:
            card['mana_cost_value'], card['mana_cost_tags'] = calculate_mana_cost_value(card['mana_cost'])

        for card in deck['cards']:
            card['super_types'], card['types'], card['sub_types'] = parse_card_types(card['type_line'])

        for card in deck['cards']:
            card['current_count'] = card_count_map.get(card['name'], 0)
            
            
            
            
async def update_current_deck_cards(conn: sqlite3.Connection, cards: list[dict]) -> None:
    import re
    cursor = conn.cursor()
    cards_to_update = []
    for card in cards:
        match = re.search(r'/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.', card["image_url"])
        if match:
            scryfall_id = match.group(1)
        else:
            scryfall_id = ""
        card_to_update = {
            "name": card["name"],
            "arena_id": card["id"],
            "image_url": card["image_url"],
            "scryfall_id": scryfall_id
        }
        cards_to_update.append(card_to_update)
    
    # search by scryfall_id and update arena_id
    for card in cards_to_update:
        cursor.execute("SELECT name, arena_id FROM scryfall_all_cards WHERE id = ?", (card['scryfall_id'],))
        result = cursor.fetchone()
        if result and result['arena_id'] != card['arena_id']:
            print(f"Update card {result['name']} with arena_id {card['arena_id']} and scryfall_id {card['scryfall_id']}")
            cursor.execute("UPDATE scryfall_all_cards SET arena_id = ? WHERE id = ?", (card['arena_id'], card['scryfall_id']))
    conn.commit()
        