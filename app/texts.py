"""System messages (not AI): order summaries, payment instructions, statuses, delivery. Arabic + English."""
from __future__ import annotations

T: dict[str, dict[str, str]] = {
    "welcome": {
        "ar": "أهلاً بك في {store}.\nاكتب لي ما تحتاجه بكلامك العادي، مثلاً: «أريد مزرعة مستوى 100 بسعر مناسب»، وسأساعدك.",
        "en": "Welcome to {store}.\nJust tell me what you need in your own words, e.g. “I want a level 100 farm at a good price”."},
    "summary": {
        "ar": "<b>ملخص الطلب</b>  <code>{ref}</code>\n\nالمزرعة: {name}\nالمستوى: {lvl}\nالمخزن: {barn}\nالصومعة: {silo}\nالأدوات: {tools}\n\n"
              "الكمية: {qty}\nسعر المزرعة: {price} {cur}\n<b>الإجمالي النهائي: {total} {cur}</b>\n\n"
              "للشراء اكتب <b>نعم</b> أو اضغط زر التأكيد. عند التأكيد تُحجز المزارع باسمك لمدة {minutes} دقيقة حتى تدفع.",
        "en": "<b>Order summary</b>  <code>{ref}</code>\n\nFarm: {name}\nLevel: {lvl}\nBarn: {barn}\nSilo: {silo}\nTools: {tools}\n\n"
              "Quantity: {qty}\nPrice per farm: {price} {cur}\n<b>Final total: {total} {cur}</b>\n\n"
              "To buy, reply <b>yes</b> or press confirm. The farms are then reserved for you for {minutes} minutes until you pay."},
    "btn_confirm": {"ar": "تأكيد الطلب", "en": "Confirm order"},
    "btn_cancel": {"ar": "إلغاء", "en": "Cancel"},
    "confirmed": {
        "ar": "<b>تم تأكيد الطلب</b>  <code>{ref}</code>\nالمزارع محجوزة لك حتى {until}.\n\nاختر وسيلة الدفع:",
        "en": "<b>Order confirmed</b>  <code>{ref}</code>\nYour farms are reserved until {until}.\n\nChoose a payment method:"},
    "no_methods": {"ar": "لا توجد وسيلة دفع متاحة حالياً بهذه العملة. تم إبلاغ الإدارة.",
                   "en": "No payment method is available for this currency right now. Staff have been notified."},
    "pay_details": {
        "ar": "<b>الدفع عبر {method}</b>\n\nرقم الطلب: <code>{ref}</code>\nالمبلغ: <b>{total} {cur}</b>\nالمعرّف: <code>{account}</code>\n\n{instructions}\n\n"
              "بعد التحويل أرسل هنا <b>صورة إثبات التحويل فقط</b>، ولا حاجة لرقم العملية.",
        "en": "<b>Pay with {method}</b>\n\nOrder: <code>{ref}</code>\nAmount: <b>{total} {cur}</b>\nAccount: <code>{account}</code>\n\n{instructions}\n\n"
              "After paying, just send the transfer screenshot here (no transaction ID needed)."},
    "copy_account": {"ar": "نسخ المعرّف", "en": "Copy account"},
    "copy_amount": {"ar": "نسخ المبلغ", "en": "Copy amount"},
    "copy_ref": {"ar": "نسخ رقم الطلب", "en": "Copy order number"},
    "need_txid": {"ar": "تم استلام صورة الإثبات للطلب <code>{ref}</code>.\nأرسل الآن رقم العملية (Order ID / Transaction ID) من تفاصيل التحويل.",
                  "en": "Payment screenshot received for <code>{ref}</code>.\nNow send the transaction ID (Order ID) from the transfer details."},
    "in_review": {"ar": "تم استلام إثبات الدفع للطلب <code>{ref}</code> وهو الآن قيد المراجعة. سيصلك إشعار فور التحقق.",
                  "en": "Payment proof for <code>{ref}</code> received and is under review. You'll be notified once verified."},
    "payment_confirmed": {"ar": "تم تأكيد الدفع للطلب <code>{ref}</code>. جاري تجهيز التسليم.",
                          "en": "Payment for <code>{ref}</code> confirmed. Preparing your delivery."},
    "payment_rejected": {"ar": "لم يتم قبول إثبات الدفع للطلب <code>{ref}</code>.\nالسبب: {reason}\nيمكنك إرسال إثبات صحيح ما دام الحجز قائماً.",
                         "en": "The payment proof for <code>{ref}</code> was not accepted.\nReason: {reason}\nYou can send a correct proof while the reservation is active."},
    "order_cancelled": {"ar": "تم إلغاء الطلب <code>{ref}</code>.\nالسبب: {reason}", "en": "Order <code>{ref}</code> was cancelled.\nReason: {reason}"},
    "order_rejected": {"ar": "تم رفض الطلب <code>{ref}</code>.\nالسبب: {reason}", "en": "Order <code>{ref}</code> was rejected.\nReason: {reason}"},
    "order_status": {"ar": "تم تحديث حالة الطلب <code>{ref}</code>: {status}", "en": "Order <code>{ref}</code> status: {status}"},
    "delivered": {
        "ar": "<b>تم التسليم</b>  <code>{ref}</code>\n{n} مزرعة — المستوى {lvl}\nاضغط على القائمة لنسخها:",
        "en": "<b>Delivered</b>  <code>{ref}</code>\n{n} farm(s) — level {lvl}\nTap the list to copy it:"},
    "keep_safe": {"ar": "احفظ البيانات ولا تشاركها مع أحد.", "en": "Keep these details private."},
    "copy_all": {"ar": "نسخ البيانات", "en": "Copy details"},
    "handoff": {"ar": "{text}", "en": "Your conversation has been transferred to our support team. A staff member will reply soon."},
    "waiting_staff": {"ar": "تم استلام رسالتك، سيرد عليك فريق الدعم قريباً.", "en": "Message received — our support team will reply soon."},
    "ai_error": {"ar": "عذراً، حدث خلل مؤقت. تم تحويل محادثتك إلى فريق الدعم.",
                 "en": "Sorry, something went wrong. Your chat was transferred to our support team."},
    "summary_expired": {"ar": "انتهت صلاحية هذا الملخص. اطلب من جديد.", "en": "This summary expired. Please ask again."},
    "cancel_done": {"ar": "تم إلغاء الطلب ولم يُحجز شيء.", "en": "Order cancelled — nothing was reserved."},
    "banned": {"ar": "حسابك موقوف. تواصل مع الدعم.", "en": "Your account is suspended."},
    "photo_no_order": {"ar": "لا يوجد طلب بانتظار الدفع لإرفاق الصورة به. أكّد طلباً واختر وسيلة الدفع أولاً.",
                       "en": "There is no order awaiting payment to attach this screenshot to. Confirm an order and pick a payment method first."},
}


def tt(lang: str | None, key: str, **kw) -> str:
    e = T[key]
    s = e.get("ar" if lang == "ar" else "en") or e["ar"]
    return s.format(**kw) if kw else s
