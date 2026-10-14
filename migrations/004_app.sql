-- =====================================================================
--  HD Agent — customers use a mobile/web app instead of Telegram.
-- =====================================================================
CREATE SEQUENCE IF NOT EXISTS customers_id_seq START 100001;
ALTER TABLE customers ALTER COLUMN id SET DEFAULT nextval('customers_id_seq');

ALTER TABLE customers
    ADD COLUMN access_code   TEXT UNIQUE,            -- HD-XXXXXX, created in the admin panel
    ADD COLUMN code_active   BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN device_id     TEXT,                   -- the single device allowed to use the code
    ADD COLUMN device_label  TEXT,
    ADD COLUMN bound_at      TIMESTAMPTZ,
    ADD COLUMN session_ver   INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN created_by    TEXT;

-- chat items: plain text or a card the app renders (order summary, payment details, delivery...)
ALTER TABLE messages
    ADD COLUMN kind     TEXT NOT NULL DEFAULT 'text',
    ADD COLUMN payload  JSONB;
CREATE INDEX messages_poll ON messages(customer_id, id);

-- payment screenshots are stored in the database
ALTER TABLE payments
    ADD COLUMN proof_image BYTEA,
    ADD COLUMN proof_mime  TEXT;

UPDATE settings SET value = 'HD Agent' WHERE key = 'store_name';
UPDATE settings SET value = E'أهلاً بك في HD Agent 🤖\n\n⚠️ تنبيه قبل الشراء:\nيتم تسليم المزارع عبر Token ID.\n\nاكتب لي نوع المزارع التي تحتاجها وعدد المزارع المطلوبة، وسأساعدك في إتمام طلبك بكل سهولة. ✅'
 WHERE key = 'welcome_text';
