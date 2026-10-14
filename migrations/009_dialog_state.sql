-- the assistant's conversation memory gets its own column (it used to share customers.awaiting with the
-- payment-proof marker, so a customer who had sent a proof lost the conversation after every message)
ALTER TABLE customers ADD COLUMN IF NOT EXISTS dialog TEXT;
UPDATE customers SET dialog = substr(awaiting, 5), awaiting = NULL WHERE awaiting LIKE 'dlg:%';
