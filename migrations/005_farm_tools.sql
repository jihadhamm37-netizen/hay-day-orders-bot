-- Land expansion tools count shown on every farm (الأدوات: 4000 (أدوات أرض)).
ALTER TABLE farm_types ADD COLUMN tools INTEGER NOT NULL DEFAULT 0 CHECK (tools >= 0);
