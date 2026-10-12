-- kartinkomet v2. All timestamps are unix seconds (UTC).

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pics (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    file_unique_id TEXT NOT NULL UNIQUE,
    added_by INTEGER,
    added_at INTEGER,
    visual_hash TEXT,
    status TEXT NOT NULL DEFAULT 'alive' CHECK (status IN ('alive', 'executed', 'deleted')),
    removed_at INTEGER,
    removed_reason TEXT,
    rating REAL NOT NULL DEFAULT 1000,
    games INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    loss_streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    shown_count INTEGER NOT NULL DEFAULT 0,
    last_shown_at INTEGER,
    likes INTEGER NOT NULL DEFAULT 0,
    dislikes INTEGER NOT NULL DEFAULT 0,
    immune_until INTEGER
);

CREATE INDEX IF NOT EXISTS idx_pics_status_rating ON pics(status, rating);
CREATE INDEX IF NOT EXISTS idx_pics_status_added ON pics(status, added_at);
CREATE INDEX IF NOT EXISTS idx_pics_added_by ON pics(added_by);
CREATE INDEX IF NOT EXISTS idx_pics_removed ON pics(status, removed_at);

CREATE TABLE IF NOT EXISTS reactions (
    pic_id TEXT NOT NULL REFERENCES pics(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    value INTEGER NOT NULL CHECK (value IN (-1, 1)),
    at INTEGER NOT NULL,
    PRIMARY KEY (pic_id, user_id)
) WITHOUT ROWID;

-- Pics already shown in a scope during the current deck cycle.
-- Scope is "pic:<chat_id>" for random drops and "arena:<chat_id>" for battles.
CREATE TABLE IF NOT EXISTS deck_seen (
    scope TEXT NOT NULL,
    pic_id TEXT NOT NULL REFERENCES pics(id) ON DELETE CASCADE,
    PRIMARY KEY (scope, pic_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS battles (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('duel', 'tournament')),
    message_id INTEGER,
    started_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'done')),
    streak INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    winner_slot INTEGER,
    result_streak INTEGER,
    card_is_photo INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_battles_active ON battles(status, chat_id, kind);

CREATE TABLE IF NOT EXISTS battle_entries (
    battle_id TEXT NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    slot INTEGER NOT NULL,
    pic_id TEXT NOT NULL REFERENCES pics(id),
    PRIMARY KEY (battle_id, slot)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS battle_votes (
    battle_id TEXT NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    PRIMARY KEY (battle_id, user_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS courts (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    pic_id TEXT NOT NULL REFERENCES pics(id),
    message_id INTEGER,
    reason TEXT NOT NULL CHECK (reason IN ('dislikes', 'bottom')),
    started_by INTEGER,
    started_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'executed', 'pardoned')),
    title TEXT NOT NULL DEFAULT '',
    pic_message_id INTEGER,
    last_word TEXT
);

CREATE INDEX IF NOT EXISTS idx_courts_active ON courts(status, pic_id);

CREATE TABLE IF NOT EXISTS court_votes (
    court_id TEXT NOT NULL REFERENCES courts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    vote TEXT NOT NULL CHECK (vote IN ('kill', 'spare')),
    PRIMARY KEY (court_id, user_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    earned_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, code)
) WITHOUT ROWID;

-- One live control panel per chat.
CREATE TABLE IF NOT EXISTS panels (
    chat_id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL
);
