-- drop Table IF EXISTS decks;
-- drop Table IF EXISTS cards;
-- drop Table IF EXISTS deck_cards;
-- DROP TABLE IF EXISTS decks;
-- DROP TABLE IF EXISTS deck_cards;

CREATE TABLE IF NOT EXISTS user_info
(
    id         INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    added_at   TEXT NOT NULL
);


-- 
-- CREATE TABLE IF NOT EXISTS cards
-- (
--     id            INTEGER PRIMARY KEY,
--     name          TEXT NOT NULL,
--     printed_name  TEXT,
--     flavor_name   TEXT,
--     face_name     TEXT,
--     mana_cost     TEXT,
--     mana_value    REAL,
--     power         TEXT,
--     original_text TEXT,
--     type          TEXT,
--     types         TEXT,
--     mtg_arena_id  TEXT,
--     scryfall_id   TEXT,
--     availability  TEXT,
--     colors        TEXT,
--     keywords      TEXT
-- );

CREATE TABLE IF NOT EXISTS scryfall_all_cards
(
    object              TEXT,
    id                  TEXT,
    name                TEXT,
    parent_id           TEXT,
    component           TEXT,
    arena_id            TEXT,
    mtgo_id             TEXT,
    mtgo_foil_id        TEXT,
    multiverse_ids      TEXT,
    resource_id         TEXT,
    oracle_id           TEXT,
    illustration_id     TEXT,
    layout              TEXT,
    color_identity      TEXT,
    colors              TEXT,
    mana_cost           TEXT,
    type_line           TEXT,
    oracle_text         TEXT,
    booster             TEXT,
    rarity              TEXT,
    variation           TEXT,
    games               TEXT,
    promo_types         TEXT,
    keywords            TEXT,
    uri                 TEXT,
    power               TEXT,
    toughness           TEXT,
    flavor_text         TEXT,
    artist              TEXT,
    artist_id           TEXT,
    image_uri_large     TEXT,
    printed_name        TEXT,
    printed_type_line   TEXT,
    printed_text        TEXT,
    color_indicator     TEXT,
    watermark           TEXT,
    defense             TEXT,
    loyalty             TEXT,
    flavor_name         TEXT,
    card_type           TEXT,
    printed_flavor_text TEXT,
    face_name           TEXT
);


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



CREATE TABLE IF NOT EXISTS deck_base64_strings
(
    id            INTEGER PRIMARY KEY,
    deck_id       INTEGER NOT NULL,
    base64_string TEXT    NOT NULL,
    FOREIGN KEY (deck_id) REFERENCES decks (id) ON DELETE CASCADE,
    UNIQUE (deck_id)
)








--------------------------------------------------------------------------------
--------------------------------------------------------------------------------
--------------------------------------------------------------------------------
-- 
-- ATTACH DATABASE 'AllPrintings.sqlite' AS ap;
-- 
-- INSERT OR IGNORE INTO cards (name, printed_name, flavor_name, mana_cost, mana_value, power, original_text, type, types,
--                              mtg_arena_id, scryfall_id, availability, colors, keywords)
-- SELECT c.name,
--        c.printedName,
--        c.flavorName,
--        c.manaCost,
--        c.manaValue,
--        c.power,
--        c.originalText,
--        c.type,
--        c.types,
--        ci.mtgArenaId,
--        ci.scryfallId,
--        c.availability,
--        c.colors,
--        c.keywords
-- FROM ap.cards c
--          INNER JOIN ap.cardIdentifiers ci ON c.uuid = ci.uuid
-- WHERE c.availability LIKE '%arena%';