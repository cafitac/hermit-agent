-- Platform ACL: per-key platform allow-list.
-- FK api_key_platform.api_key → api_keys(api_key) which is UNIQUE (see 001_initial.sql).

CREATE TABLE IF NOT EXISTS platforms (
  slug       TEXT     PRIMARY KEY,
  label      TEXT     NOT NULL,
  created_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS api_key_platform (
  api_key       TEXT NOT NULL,
  platform_slug TEXT NOT NULL,
  PRIMARY KEY (api_key, platform_slug),
  FOREIGN KEY (api_key)       REFERENCES api_keys(api_key)   ON DELETE CASCADE,
  FOREIGN KEY (platform_slug) REFERENCES platforms(slug)      ON DELETE CASCADE
);

INSERT OR IGNORE INTO platforms(slug, label, created_at) VALUES
  ('local',     'Local ollama',            datetime('now')),
  ('z.ai',      'z.ai (OpenAI+Anthropic)', datetime('now')),
  ('anthropic', 'Anthropic official',      datetime('now')),
  ('codex',     'GitHub Models / Codex',   datetime('now'));

-- Backfill existing api_keys with full access to preserve post-upgrade operation.
INSERT OR IGNORE INTO api_key_platform (api_key, platform_slug)
  SELECT a.api_key, p.slug FROM api_keys a CROSS JOIN platforms p;
