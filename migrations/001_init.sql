-- =====================================================================
--  Hay Day Store — initial schema
--  All money is USDT, numeric(18,2). Balances can only change through
--  rows inserted into wallet_transactions (enforced by triggers).
-- =====================================================================

-- ---------------------------------------------------------------- users
CREATE TABLE users (
    id              BIGINT PRIMARY KEY,               -- Telegram user id
    username        TEXT,
    first_name      TEXT,
    balance         NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    is_banned       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------- farm types
CREATE TABLE farm_types (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    lvl         INTEGER NOT NULL CHECK (lvl > 0),
    barn        INTEGER NOT NULL CHECK (barn >= 0),
    silo        INTEGER NOT NULL CHECK (silo >= 0),
    price       NUMERIC(18,2) NOT NULL CHECK (price > 0),
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------- farm accounts
-- login and password are stored encrypted (Fernet / AES-128-CBC + HMAC).
-- login_hash is a keyed HMAC of the login used to reject duplicates.
CREATE TABLE farm_accounts (
    id            BIGSERIAL PRIMARY KEY,
    type_id       INTEGER NOT NULL REFERENCES farm_types(id) ON DELETE RESTRICT,
    login_enc     TEXT NOT NULL,
    password_enc  TEXT NOT NULL,
    login_hash    TEXT NOT NULL UNIQUE,
    login_hint    TEXT NOT NULL,                       -- masked, e.g. "abc•••"
    custom_price  NUMERIC(18,2) CHECK (custom_price IS NULL OR custom_price > 0),
    status        TEXT NOT NULL DEFAULT 'available'
                  CHECK (status IN ('available','reserved','sold','disabled')),
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    sold_at       TIMESTAMPTZ
);
CREATE INDEX farm_accounts_type_status ON farm_accounts(type_id, status);

-- ---------------------------------------------------------------- orders
CREATE TABLE orders (
    id               BIGSERIAL PRIMARY KEY,
    ref              TEXT NOT NULL UNIQUE,
    user_id          BIGINT NOT NULL REFERENCES users(id),
    type_id          INTEGER NOT NULL REFERENCES farm_types(id),
    account_id       BIGINT REFERENCES farm_accounts(id) ON DELETE RESTRICT,
    price            NUMERIC(18,2) NOT NULL CHECK (price > 0),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','processing','completed','cancelled','needs_review')),
    type_snapshot    JSONB NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    failure_reason   TEXT,
    admin_note       TEXT,
    delivered_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- an account can belong to at most one live order — makes double sale impossible
CREATE UNIQUE INDEX orders_account_once ON orders(account_id)
    WHERE account_id IS NOT NULL AND status <> 'cancelled';
CREATE INDEX orders_user ON orders(user_id, created_at DESC);
CREATE INDEX orders_status ON orders(status, created_at DESC);

-- -------------------------------------------------------------- deposits
CREATE TABLE deposits (
    id                    BIGSERIAL PRIMARY KEY,
    ref                   TEXT NOT NULL UNIQUE,
    user_id               BIGINT NOT NULL REFERENCES users(id),
    amount                NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    credited_amount       NUMERIC(18,2),
    status                TEXT NOT NULL DEFAULT 'awaiting_payment'
                          CHECK (status IN ('awaiting_payment','under_review','approved','rejected','cancelled')),
    pay_id_shown          TEXT,
    proof_file_id         TEXT,
    proof_file_unique_id  TEXT,
    proof_txid            TEXT,
    reject_reason         TEXT,
    auto_verified         BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- one proof (screenshot / Binance order id) can never back two deposits
CREATE UNIQUE INDEX deposits_proof_file_once ON deposits(proof_file_unique_id)
    WHERE proof_file_unique_id IS NOT NULL;
CREATE UNIQUE INDEX deposits_txid_once ON deposits(lower(proof_txid))
    WHERE proof_txid IS NOT NULL;
-- at most one open (unpaid) deposit per user
CREATE UNIQUE INDEX deposits_one_open ON deposits(user_id)
    WHERE status = 'awaiting_payment';
CREATE INDEX deposits_status ON deposits(status, created_at DESC);

-- ---------------------------------------------------- wallet transactions
CREATE TABLE wallet_transactions (
    id               BIGSERIAL PRIMARY KEY,
    ref              TEXT NOT NULL UNIQUE,
    user_id          BIGINT NOT NULL REFERENCES users(id),
    amount           NUMERIC(18,2) NOT NULL CHECK (amount <> 0),
    balance_before   NUMERIC(18,2) NOT NULL,
    balance_after    NUMERIC(18,2) NOT NULL CHECK (balance_after >= 0),
    kind             TEXT NOT NULL CHECK (kind IN
                       ('deposit','purchase','refund','admin_credit','admin_debit')),
    idempotency_key  TEXT NOT NULL UNIQUE,
    order_id         BIGINT REFERENCES orders(id),
    deposit_id       BIGINT REFERENCES deposits(id),
    actor            TEXT,
    reason           TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX wallet_tx_user ON wallet_transactions(user_id, created_at DESC);

-- The ONLY way a balance changes: inserting a wallet transaction.
CREATE FUNCTION wallet_tx_apply() RETURNS trigger AS $$
DECLARE
    old_bal NUMERIC(18,2);
BEGIN
    SELECT balance INTO old_bal FROM users WHERE id = NEW.user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet: unknown user %', NEW.user_id USING ERRCODE = 'HD002';
    END IF;
    IF old_bal + NEW.amount < 0 THEN
        RAISE EXCEPTION 'wallet: insufficient balance' USING ERRCODE = 'HD001';
    END IF;
    NEW.balance_before := old_bal;
    NEW.balance_after  := old_bal + NEW.amount;
    UPDATE users SET balance = NEW.balance_after WHERE id = NEW.user_id;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER wallet_tx_apply BEFORE INSERT ON wallet_transactions
    FOR EACH ROW EXECUTE FUNCTION wallet_tx_apply();

-- Block any direct balance edit that does not come from the trigger above.
CREATE FUNCTION users_guard_balance() RETURNS trigger AS $$
BEGIN
    IF NEW.balance IS DISTINCT FROM OLD.balance AND pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'balance can only change through wallet_transactions'
            USING ERRCODE = 'HD003';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER users_guard_balance BEFORE UPDATE OF balance ON users
    FOR EACH ROW EXECUTE FUNCTION users_guard_balance();

CREATE FUNCTION users_guard_insert() RETURNS trigger AS $$
BEGIN
    IF NEW.balance <> 0 THEN
        RAISE EXCEPTION 'new users start with zero balance' USING ERRCODE = 'HD003';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER users_guard_insert BEFORE INSERT ON users
    FOR EACH ROW EXECUTE FUNCTION users_guard_insert();

-- Financial history is append-only.
CREATE FUNCTION immutable_row() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'HD004';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER wallet_tx_immutable BEFORE UPDATE OR DELETE ON wallet_transactions
    FOR EACH ROW EXECUTE FUNCTION immutable_row();

-- Sold accounts are never deleted.
CREATE FUNCTION farm_accounts_guard_delete() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('sold','reserved') THEN
        RAISE EXCEPTION 'sold/reserved accounts cannot be deleted' USING ERRCODE = 'HD004';
    END IF;
    RETURN OLD;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER farm_accounts_guard_delete BEFORE DELETE ON farm_accounts
    FOR EACH ROW EXECUTE FUNCTION farm_accounts_guard_delete();

-- --------------------------------------------------------------- settings
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  TEXT
);

-- ----------------------------------------------------------------- admins
CREATE TABLE admins (
    id             SERIAL PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT,
    telegram_id    BIGINT UNIQUE,
    role           TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('owner','admin','support')),
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    token_version  INTEGER NOT NULL DEFAULT 1,
    failed_logins  INTEGER NOT NULL DEFAULT 0,
    locked_until   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at  TIMESTAMPTZ
);

CREATE TABLE login_codes (
    id          BIGSERIAL PRIMARY KEY,
    admin_id    INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------- audit log
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor       TEXT NOT NULL,          -- "web:ahmed", "tg:12345", "system"
    action      TEXT NOT NULL,
    entity      TEXT,
    entity_id   TEXT,
    details     JSONB,
    ip          TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_created ON audit_log(created_at DESC);
CREATE TRIGGER audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION immutable_row();

-- ----------------------------------------------------------------- alerts
CREATE TABLE alerts (
    id          BIGSERIAL PRIMARY KEY,
    level       TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('info','warning','error')),
    kind        TEXT NOT NULL,
    message     TEXT NOT NULL,
    entity      TEXT,
    entity_id   TEXT,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX alerts_unread ON alerts(is_read, created_at DESC);

-- ---------------------------------------------------------- default data
INSERT INTO settings(key, value) VALUES
 ('binance_pay_id',      '1127859028'),
 ('payment_instructions','1) افتح تطبيق Binance ← Pay ← إرسال.
2) أدخل معرّف Binance Pay أعلاه والصق المبلغ بعملة USDT بالضبط.
3) بعد التحويل أرسل هنا لقطة شاشة لإيصال الدفع ثم رقم الطلب (Order ID).'),
 ('welcome_text',        'أهلاً بك في متجر مزارع Hay Day 🌾
اختر من القائمة بالأسفل.'),
 ('support_text',        'للتواصل مع الدعم الفني راسلنا وسنرد بأسرع وقت.'),
 ('support_username',    ''),
 ('hide_out_of_stock',   'false'),
 ('low_stock_threshold', '3'),
 ('min_deposit',         '1'),
 ('max_deposit',         '5000'),
 ('require_txid',        'true'),
 ('auto_verify_enabled', 'false');
