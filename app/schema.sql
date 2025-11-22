-- drop Table IF EXISTS decks;
-- drop Table IF EXISTS cards;
-- drop Table IF EXISTS deck_cards;


-- Table for Decks
CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    added_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    manaCost TEXT,
    manaValue REAL,
    power TEXT,
    originalText TEXT,
    type TEXT,
    types TEXT,
    mtgArenaId TEXT,
    scryfallId TEXT,
    availability TEXT,
    colors TEXT,
    keywords TEXT
);

-- Junction table for Cards in Decks
CREATE TABLE IF NOT EXISTS deck_cards (
    id INTEGER PRIMARY KEY,
    deck_id INTEGER NOT NULL,
    card_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    FOREIGN KEY (deck_id) REFERENCES decks (id) ON DELETE CASCADE,
    FOREIGN KEY (card_id) REFERENCES cards (id),
    UNIQUE (deck_id, card_id)
);



--------------------------------------------------------------------------------
--------------------------------------------------------------------------------
--------------------------------------------------------------------------------


ATTACH DATABASE 'AllPrintings.sqlite' AS ap;
       

INSERT INTO cards (name, manaCost, manaValue, power, originalText, type, types, mtgArenaId, scryfallId, availability, colors, keywords)
SELECT 
    c.name,
    c.manaCost,
    c.manaValue,
    c.power,
    c.originalText,
    c.type,
    c.types,
    ci.mtgArenaId,
    ci.scryfallId,
    c.availability,
    c.colors,
    c.keywords
FROM ap.cards c
LEFT JOIN ap.cardIdentifiers ci ON c.uuid = ci.uuid
WHERE c.availability LIKE '%arena%';