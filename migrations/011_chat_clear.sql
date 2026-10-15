-- the customer can clear the chat in the app: messages up to this id are hidden from them (staff still see everything)
ALTER TABLE customers ADD COLUMN IF NOT EXISTS chat_cleared_id BIGINT NOT NULL DEFAULT 0;
