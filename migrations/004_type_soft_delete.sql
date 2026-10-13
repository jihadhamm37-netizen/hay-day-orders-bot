-- Types that were sold before are archived (hidden everywhere) instead of erased, so order history stays intact.
ALTER TABLE farm_types ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE farm_types ADD COLUMN deleted_at TIMESTAMPTZ;
