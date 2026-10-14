-- Payment proof is a screenshot only: fix the default Binance Pay instructions.
UPDATE payment_methods
   SET instructions = 'افتح Binance ← Pay ← إرسال، أدخل معرّف Binance Pay وحوّل المبلغ بالضبط بعملة USDT، ثم أرسل صورة التحويل فقط هنا.'
 WHERE kind = 'binance_pay' AND instructions LIKE '%رقم الطلب%';
