-- Remove emoji from the default welcome texts (owner asked for plain messages).
UPDATE settings SET value = replace(value, ' 🌾', '') WHERE key IN ('welcome_text', 'welcome_text_en');
