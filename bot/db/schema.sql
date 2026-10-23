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
    card_is_photo INTEGER NOT NULL DEFAULT 0,
    extended INTEGER NOT NULL DEFAULT 0
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

-- Economy: coins balance and lifetime earnings (level), plus a ledger for weekly crowns.
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    coins INTEGER NOT NULL DEFAULT 0,
    earned INTEGER NOT NULL DEFAULT 0,
    level_seen INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ledger (
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_at ON ledger(at, reason);

-- Per-user counters for achievements and statuses (guess streaks, spins, activity days…).
CREATE TABLE IF NOT EXISTS counters (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, key)
) WITHOUT ROWID;

-- Mini-games. "Caption this pic": collect captions as replies, then vote anonymously.
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    pic_id TEXT NOT NULL REFERENCES pics(id),
    message_id INTEGER,
    phase TEXT NOT NULL DEFAULT 'collect' CHECK (phase IN ('collect', 'vote', 'done')),
    phase_ends_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_active ON games(phase, chat_id);

CREATE TABLE IF NOT EXISTS game_entries (
    game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    at INTEGER NOT NULL,
    PRIMARY KEY (game_id, user_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS game_votes (
    game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    PRIMARY KEY (game_id, user_id)
) WITHOUT ROWID;

-- Golden pics: the first one to press "grab" wins.
CREATE TABLE IF NOT EXISTS gold (
    token TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    pic_id TEXT NOT NULL,
    claimed_by INTEGER,
    created_at INTEGER NOT NULL
);

-- Group chats the bot lives in, for scheduled events (pic of the day, auto court, weekly digest).
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    events INTEGER NOT NULL DEFAULT 1,
    last_seen INTEGER NOT NULL
);

-- One live control panel per chat.
CREATE TABLE IF NOT EXISTS panels (
    chat_id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL
);

-- ── v4 ─────────────────────────────────────────────────────────────────

-- Parimutuel bets on battles: one slot per player per battle, raised in BET_STEP increments.
CREATE TABLE IF NOT EXISTS battle_bets (
    battle_id TEXT NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    PRIMARY KEY (battle_id, user_id)
) WITHOUT ROWID;

-- Player vs player duels for coins. The battle itself lives in battles (mode = 'challenge').
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER,
    from_user INTEGER NOT NULL,
    to_user INTEGER,
    stake INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'declined', 'expired', 'cancelled')),
    battle_id TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

-- Bounties on pics: paid to whoever kills the pic.
CREATE TABLE IF NOT EXISTS bounties (
    pic_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bounties_pic ON bounties(pic_id);

CREATE TABLE IF NOT EXISTS bosses (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    pic_id TEXT NOT NULL,
    message_id INTEGER,
    title TEXT NOT NULL,
    hp INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    loot INTEGER NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'won', 'lost')),
    last_hit_by INTEGER,
    started_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bosses_active ON bosses(status, chat_id);

CREATE TABLE IF NOT EXISTS boss_hits (
    boss_id TEXT NOT NULL REFERENCES bosses(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    damage INTEGER NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (boss_id, user_id)
) WITHOUT ROWID;

-- Marriages: one row per spouse, so lookups go both ways.
CREATE TABLE IF NOT EXISTS marriages (
    user_id INTEGER PRIMARY KEY,
    spouse_id INTEGER NOT NULL,
    since INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    from_user INTEGER NOT NULL,
    to_user INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'declined', 'expired')),
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS titles (
    user_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL
);

-- ── v5 ─────────────────────────────────────────────────────────────────

-- Season podiums: the top three of every finished month keep their place forever.
CREATE TABLE IF NOT EXISTS seasons (
    season TEXT NOT NULL,
    place INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    PRIMARY KEY (season, place)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, at);
