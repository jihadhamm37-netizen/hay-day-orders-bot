-- Payment proof = screenshot only (no transaction number).
UPDATE payment_methods SET require_txid = FALSE;
UPDATE customers SET awaiting = NULL WHERE awaiting LIKE 'txid:%';
UPDATE orders o SET status='payment_review', updated_at=now()
 WHERE status='proof_received' AND EXISTS (SELECT 1 FROM payments p WHERE p.order_id=o.id AND p.status='pending');
