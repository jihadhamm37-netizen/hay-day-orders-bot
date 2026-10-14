-- Editable welcome message + timestamp of when a chat was handed to staff (auto-resume of the AI).
INSERT INTO settings(key, value) VALUES
 ('welcome_text', E'أهلاً بك في HD农场 🌾\n\n⚠️ تنبيه قبل الشراء:\nيتم تسليم المزارع عبر Token ID.\n\nاكتب لي نوع المزارع التي تحتاجها وعدد المزارع المطلوبة، وسأساعدك في إتمام طلبك بكل سهولة. ✅')
ON CONFLICT (key) DO NOTHING;

ALTER TABLE customers ADD COLUMN IF NOT EXISTS ai_paused_at TIMESTAMPTZ;
-- launch: give every chat back to the AI
UPDATE customers SET ai_paused = FALSE, ai_paused_at = NULL;

CREATE OR REPLACE FUNCTION customers_pause_stamp() RETURNS trigger AS $$
BEGIN
  IF NEW.ai_paused AND NOT OLD.ai_paused THEN
    NEW.ai_paused_at := now();
  ELSIF NOT NEW.ai_paused THEN
    NEW.ai_paused_at := NULL;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS customers_pause_stamp ON customers;
CREATE TRIGGER customers_pause_stamp BEFORE UPDATE OF ai_paused ON customers
  FOR EACH ROW EXECUTE FUNCTION customers_pause_stamp();
