CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id TEXT NOT NULL UNIQUE,
  unique_file_id TEXT,
  added_by INTEGER,
  added_by_name TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  shown_count INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_images_active ON images(active, shown_count);
CREATE INDEX IF NOT EXISTS idx_images_added_by ON images(added_by);

CREATE TABLE IF NOT EXISTS jokes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL UNIQUE,
  added_by INTEGER,
  added_by_name TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  shown_count INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jokes_active ON jokes(active, shown_count);
CREATE INDEX IF NOT EXISTS idx_jokes_added_by ON jokes(added_by);

CREATE TABLE IF NOT EXISTS reactions (
  content_type TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  reaction TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (content_type, content_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_reactions_content ON reactions(content_type, content_id);

CREATE TABLE IF NOT EXISTS upload_sessions (
  user_id INTEGER NOT NULL,
  chat_id INTEGER NOT NULL,
  mode TEXT NOT NULL,
  added_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, mode)
);

CREATE TABLE IF NOT EXISTS random_history (
  chat_id INTEGER NOT NULL,
  content_type TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_random_history_chat ON random_history(chat_id, content_type, created_at);

CREATE TABLE IF NOT EXISTS bot_stats (
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);
