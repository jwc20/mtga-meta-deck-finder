CREATE TABLE IF NOT EXISTS user_info
(
    id         INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    added_at   TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS scryfall_all_cards (object TEXT, id TEXT, name TEXT, parent_id TEXT, component TEXT, arena_id TEXT, mtgo_id TEXT, mtgo_foil_id TEXT, multiverse_ids TEXT, resource_id TEXT, oracle_id TEXT, illustration_id TEXT, layout TEXT, color_identity TEXT, colors TEXT, mana_cost TEXT, type_line TEXT, oracle_text TEXT, booster TEXT, rarity TEXT, variation TEXT, games TEXT, promo_types TEXT, keywords TEXT, uri TEXT, power TEXT, toughness TEXT, flavor_text TEXT, artist TEXT, artist_id TEXT, image_uri_large TEXT, printed_name TEXT, printed_type_line TEXT, printed_text TEXT, color_indicator TEXT, watermark TEXT, defense TEXT, loyalty TEXT, flavor_name TEXT, card_type TEXT, printed_flavor_text TEXT, face_name TEXT, produced_mana TEXT);

CREATE TABLE IF NOT EXISTS decks
(
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    source   TEXT NOT NULL,
    author   TEXT,
    format   TEXT,
    url      TEXT NOT NULL,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deck_cards
(
    id       INTEGER PRIMARY KEY,
    deck_id  INTEGER NOT NULL,
    card_id  TEXT, 
    name     TEXT NOT NULL,
    section  TEXT,
    quantity INTEGER NOT NULL,
    FOREIGN KEY (deck_id) REFERENCES decks (id) ON DELETE CASCADE,
    FOREIGN KEY (card_id) REFERENCES cards (id),
    UNIQUE (deck_id, card_id)
);


CREATE TABLE IF NOT EXISTS "17lands"
(
    id             integer,
    expansion      text,
    name           text,
    rarity         text,
    color_identity text,
    mana_value     integer,
    types          text,
    is_booster     text
);

CREATE TABLE IF NOT EXISTS "17lands_abilities" (
	id INTEGER,
	"text" VARCHAR(128)
);


