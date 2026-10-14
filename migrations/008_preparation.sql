-- Paid orders wait in "processing" (preparation) until staff press "deliver"; guard against double delivery.
ALTER TABLE orders ADD COLUMN delivering_at TIMESTAMPTZ;
UPDATE settings SET value = E'أهلًا وسهلًا بك في HD Agent 🤖🌾\nأنا هنا لمساعدتك في شراء مزارع Hay Day بسهولة.\nماذا تحتاج؟ يمكنك كتابة طلبك مباشرة وسأساعدك خطوة بخطوة.'
 WHERE key = 'welcome_text' AND value LIKE 'أهلاً بك في HD Agent 🤖%';
