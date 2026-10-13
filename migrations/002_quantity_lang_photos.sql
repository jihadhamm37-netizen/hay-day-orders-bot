-- Quantity purchases, per-user language, farm photos, menu icons, English texts.

ALTER TABLE users ADD COLUMN lang TEXT NOT NULL DEFAULT 'ar' CHECK (lang IN ('ar','en'));
ALTER TABLE users ADD COLUMN lang_chosen BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE farm_types ADD COLUMN photo_file_id TEXT;
ALTER TABLE farm_accounts ADD COLUMN photo_file_id TEXT;

-- several orders bought together in one confirmation share a batch id
ALTER TABLE orders ADD COLUMN batch_id TEXT;
CREATE INDEX orders_batch ON orders(batch_id) WHERE batch_id IS NOT NULL;

INSERT INTO settings(key, value) VALUES
 ('welcome_text_en',          'Welcome to the Hay Day farm store 🌾
Choose from the menu below.'),
 ('support_text_en',          'Contact our support team and we will reply as soon as possible.'),
 ('payment_instructions_en',  '1) Open Binance → Pay → Send.
2) Enter the Binance Pay ID above and send the exact USDT amount.
3) After paying, send a screenshot of the receipt here, then the Order ID.'),
 ('max_quantity',             '20'),
 ('icon_buy',                 ''),
 ('icon_wallet',              ''),
 ('icon_topup',               ''),
 ('icon_orders',              ''),
 ('icon_support',             ''),
 ('icon_lang',                '')
ON CONFLICT (key) DO NOTHING;
