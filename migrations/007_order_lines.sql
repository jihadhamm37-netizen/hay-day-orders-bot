-- One order can contain several farm types: [{offer snapshot, quantity, unit_price, subtotal}, ...]
ALTER TABLE orders ADD COLUMN lines JSONB;
UPDATE orders SET lines = jsonb_build_array(jsonb_build_object(
    'offer', offer, 'quantity', quantity, 'unit_price', unit_price::text, 'subtotal', total::text));
