-- customer wallet balance (in USD / USDT), topped up by staff, spendable on orders
ALTER TABLE customers ADD COLUMN IF NOT EXISTS balance NUMERIC(14,2) NOT NULL DEFAULT 0;
ALTER TABLE customers ADD CONSTRAINT customers_balance_nonneg CHECK (balance >= 0);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_from_balance NUMERIC(14,2);
CREATE TABLE IF NOT EXISTS balance_log (
    id            BIGSERIAL PRIMARY KEY,
    customer_id   BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    delta         NUMERIC(14,2) NOT NULL,
    balance_after NUMERIC(14,2) NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('topup','deduct','order','refund')),
    order_id      BIGINT REFERENCES orders(id) ON DELETE SET NULL,
    note          TEXT,
    actor         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS balance_log_customer ON balance_log(customer_id, id DESC);
