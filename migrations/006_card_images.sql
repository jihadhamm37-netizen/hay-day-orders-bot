-- Cached Telegram file ids for the generated farm cards and store banner.
ALTER TABLE farm_types ADD COLUMN card_file_id TEXT;
ALTER TABLE farm_types ADD COLUMN card_hash TEXT;
INSERT INTO settings(key, value) VALUES ('store_name', 'HD FARM STORE'), ('banner_file_id', ''), ('banner_hash', '')
ON CONFLICT (key) DO NOTHING;
