-- =====================================================================
--  HD农场 — AI sales bot. Fresh schema (independent from HD Market).
-- =====================================================================

-- ------------------------------------------------------------- customers
CREATE TABLE customers (
    id               BIGINT PRIMARY KEY,                -- Telegram user id
    username         TEXT,
    first_name       TEXT,
    lang             TEXT NOT NULL DEFAULT 'ar',
    ai_paused        BOOLEAN NOT NULL DEFAULT FALSE,    -- admin took over the chat
    is_banned        BOOLEAN NOT NULL DEFAULT FALSE,
    awaiting         TEXT,                              -- e.g. 'txid:<payment_id>' (survives restarts)
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at  TIMESTAMPTZ
);

-- -------------------------------------------------------------- messages
CREATE TABLE messages (
    id           BIGSERIAL PRIMARY KEY,
    customer_id  BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user','assistant','admin','system')),
    content      TEXT NOT NULL,
    author       TEXT,                                   -- admin username for role=admin
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX messages_customer ON messages(customer_id, id DESC);

-- ----------------------------------------------------------------- farms
-- token_id and password are encrypted (Fernet). token_hash = keyed HMAC to reject duplicates.
CREATE TABLE farms (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    lvl           INTEGER NOT NULL CHECK (lvl > 0),
    barn          INTEGER NOT NULL DEFAULT 0 CHECK (barn >= 0),
    silo          INTEGER NOT NULL DEFAULT 0 CHECK (silo >= 0),
    tools         INTEGER NOT NULL DEFAULT 0 CHECK (tools >= 0),
    price         NUMERIC(18,2) NOT NULL CHECK (price > 0),
    cost          NUMERIC(18,2) CHECK (cost IS NULL OR cost >= 0),
    currency      TEXT NOT NULL DEFAULT 'USDT',
    description   TEXT,
    token_enc     TEXT NOT NULL,
    password_enc  TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    token_hint    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'available'
                  CHECK (status IN ('available','reserved','sold','disabled')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    sold_at       TIMESTAMPTZ
);
CREATE INDEX farms_search ON farms(status, lvl, price);

-- -------------------------------------------------------- payment methods
CREATE TABLE payment_methods (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'manual' CHECK (kind IN ('binance_pay','manual','other')),
    account       TEXT NOT NULL,                     -- Pay ID / wallet / account number shown to customers
    currency      TEXT NOT NULL DEFAULT 'USDT',
    instructions  TEXT,
    require_txid  BOOLEAN NOT NULL DEFAULT TRUE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------- orders
CREATE TABLE orders (
    id                 BIGSERIAL PRIMARY KEY,
    ref                TEXT NOT NULL UNIQUE,
    customer_id        BIGINT NOT NULL REFERENCES customers(id),
    status             TEXT NOT NULL DEFAULT 'pending_confirmation' CHECK (status IN (
                         'pending_confirmation','awaiting_payment','proof_received','payment_review',
                         'payment_confirmed','processing','delivered','cancelled','rejected')),
    offer              JSONB NOT NULL,                 -- what the customer agreed to (snapshot)
    quantity           INTEGER NOT NULL CHECK (quantity > 0),
    unit_price         NUMERIC(18,2) NOT NULL CHECK (unit_price > 0),
    total              NUMERIC(18,2) NOT NULL CHECK (total > 0),
    currency           TEXT NOT NULL,
    payment_method_id  INTEGER REFERENCES payment_methods(id),
    reserved_until     TIMESTAMPTZ,
    reason             TEXT,                           -- reject / cancel reason shown to the customer
    admin_note         TEXT,
    failure_reason     TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at       TIMESTAMPTZ,
    paid_at            TIMESTAMPTZ,
    delivered_at       TIMESTAMPTZ
);
CREATE INDEX orders_customer ON orders(customer_id, id DESC);
CREATE INDEX orders_status ON orders(status, id DESC);
-- only one unconfirmed order per customer at a time
CREATE UNIQUE INDEX orders_one_pending ON orders(customer_id) WHERE status = 'pending_confirmation';

CREATE TABLE order_items (
    id         BIGSERIAL PRIMARY KEY,
    order_id   BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    farm_id    BIGINT NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    price      NUMERIC(18,2) NOT NULL,
    cost       NUMERIC(18,2),
    active     BOOLEAN NOT NULL DEFAULT TRUE
);
-- a farm can belong to at most one live order — makes double sale impossible
CREATE UNIQUE INDEX order_items_farm_once ON order_items(farm_id) WHERE active;
CREATE INDEX order_items_order ON order_items(order_id);

-- --------------------------------------------------------------- payments
CREATE TABLE payments (
    id                    BIGSERIAL PRIMARY KEY,
    order_id              BIGINT NOT NULL REFERENCES orders(id),
    method_id             INTEGER NOT NULL REFERENCES payment_methods(id),
    amount                NUMERIC(18,2) NOT NULL,
    currency              TEXT NOT NULL,
    proof_file_id         TEXT,
    proof_file_unique_id  TEXT,
    txid                  TEXT,
    status                TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    reject_reason         TEXT,
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX payments_proof_once ON payments(proof_file_unique_id) WHERE proof_file_unique_id IS NOT NULL;
CREATE UNIQUE INDEX payments_txid_once ON payments(lower(txid)) WHERE txid IS NOT NULL;
-- one live payment per order (no duplicate payment records)
CREATE UNIQUE INDEX payments_one_live ON payments(order_id) WHERE status IN ('pending','approved');

-- ------------------------------------------------------- guards & history
CREATE FUNCTION immutable_row() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'HD004';
END $$ LANGUAGE plpgsql;

CREATE FUNCTION farms_guard_delete() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('sold','reserved') THEN
        RAISE EXCEPTION 'sold/reserved farms cannot be deleted' USING ERRCODE = 'HD004';
    END IF;
    RETURN OLD;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER farms_guard_delete BEFORE DELETE ON farms FOR EACH ROW EXECUTE FUNCTION farms_guard_delete();

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

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor       TEXT NOT NULL,
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
 ('store_name',        'HD农场'),
 ('ai_enabled',        'true'),
 ('reservation_minutes', '30'),
 ('max_quantity',      '20'),
 ('max_open_orders',   '3'),
 ('store_info',        'نبيع مزارع لعبة Hay Day جاهزة. كل مزرعة لها Token ID وكلمة مرور خاصة بها، وتُسلَّم داخل البوت فور تأكيد الدفع من الإدارة.'),
 ('warranty_policy',   'نضمن أن بيانات المزرعة صحيحة وتعمل عند التسليم. أي مشكلة في الدخول خلال 24 ساعة من التسليم تُحل أو يُستبدل الحساب.'),
 ('delivery_policy',   'يتم التسليم داخل هذه المحادثة بعد تأكيد الدفع من الإدارة، وعادةً خلال دقائق.'),
 ('payment_policy',    'الدفع لكل طلب. بعد تأكيد الطلب يختار العميل وسيلة الدفع، يحوّل المبلغ بالضبط، ثم يرسل صورة الإثبات ورقم العملية.'),
 ('extra_faq',         ''),
 ('ai_instructions',   'تحدث بلطف واختصار. لا تستخدم الإيموجي.'),
 ('handoff_text',      'تم تحويل محادثتك إلى فريق الدعم، وسيرد عليك أحد الموظفين قريباً.');

INSERT INTO payment_methods(name, kind, account, currency, instructions, require_txid, sort_order) VALUES
 ('Binance Pay', 'binance_pay', '1127859028', 'USDT',
  'افتح Binance ← Pay ← إرسال، أدخل معرّف Binance Pay وحوّل المبلغ بالضبط بعملة USDT، ثم أرسل صورة الإيصال ورقم الطلب (Order ID).',
  TRUE, 0);
