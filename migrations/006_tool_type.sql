-- Tool type: identical farms can carry land, barn or silo upgrade tools.
ALTER TABLE farms ADD COLUMN tool_type TEXT NOT NULL DEFAULT 'land' CHECK (tool_type IN ('land', 'barn', 'silo'));
DROP INDEX IF EXISTS farms_search;
CREATE INDEX farms_search ON farms(status, lvl, tool_type, price);
