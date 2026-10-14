"""System messages (not AI): order summaries, payment instructions, statuses, delivery. Arabic, English, Vietnamese, Chinese."""
from __future__ import annotations

T: dict[str, dict[str, str]] = {
    "welcome": {
        "ar": "أهلاً بك في {store}.\nاكتب لي ما تحتاجه بكلامك العادي، مثلاً: «أريد مزرعة مستوى 100 بسعر مناسب»، وسأساعدك.",
        "en": "Welcome to {store}.\nJust tell me what you need in your own words, e.g. “I want a level 100 farm at a good price”.",
        "vi": "Chào mừng bạn đến với {store}. Hãy cho tôi biết bạn cần gì.", "zh": "欢迎来到 {store}。请告诉我您需要什么。"},
    "summary": {
        "ar": "<b>ملخص الطلب</b>  <code>{ref}</code>\n\nالمزرعة: {name}\nالمستوى: {lvl}\nالمخزن: {barn}\nالصومعة: {silo}\nالأدوات: {tools}\n\n"
              "الكمية: {qty}\nسعر المزرعة: {price} {cur}\n<b>الإجمالي النهائي: {total} {cur}</b>\n\n"
              "للشراء اكتب <b>نعم</b> أو اضغط زر التأكيد. عند التأكيد تُحجز المزارع باسمك لمدة {minutes} دقيقة حتى تدفع.",
        "en": "<b>Order summary</b>  <code>{ref}</code>\n\nFarm: {name}\nLevel: {lvl}\nBarn: {barn}\nSilo: {silo}\nTools: {tools}\n\n"
              "Quantity: {qty}\nPrice per farm: {price} {cur}\n<b>Final total: {total} {cur}</b>\n\n"
              "To buy, reply <b>yes</b> or press confirm. The farms are then reserved for you for {minutes} minutes until you pay.",
        "vi": "Tóm tắt đơn {ref}\n\nCấp: {lvl}\nKho: {barn}\nSilo: {silo}\nCông cụ: {tools}\n\nSố lượng: {qty}\nGiá mỗi nông trại: {price} {cur}\nTổng cộng: {total} {cur}\n\nĐể mua, trả lời “có” hoặc bấm xác nhận. Nông trại sẽ được giữ {minutes} phút.", "zh": "订单摘要 {ref}\n\n等级：{lvl}\n仓库：{barn}\n粮仓：{silo}\n工具：{tools}\n\n数量：{qty}\n单价：{price} {cur}\n总计：{total} {cur}\n\n回复“是”或点击确认即可购买，农场将为您保留 {minutes} 分钟。"},
    "btn_confirm": {"ar": "تأكيد الطلب", "en": "Confirm order"},
    "btn_cancel": {"ar": "إلغاء", "en": "Cancel"},
    "confirmed": {
        "ar": "<b>تم تأكيد الطلب</b>  <code>{ref}</code>\nالمزارع محجوزة لك حتى {until}.\n\nاختر وسيلة الدفع:",
        "en": "<b>Order confirmed</b>  <code>{ref}</code>\nYour farms are reserved until {until}.\n\nChoose a payment method:",
        "vi": "Đã xác nhận đơn {ref}. Chọn phương thức thanh toán:", "zh": "订单 {ref} 已确认。请选择支付方式："},
    "no_methods": {"ar": "لا توجد وسيلة دفع متاحة حالياً بهذه العملة. تم إبلاغ الإدارة.",
                   "en": "No payment method is available for this currency right now. Staff have been notified.",
        "vi": "Hiện chưa có phương thức thanh toán cho loại tiền này. Đã báo quản trị.", "zh": "暂无该币种的支付方式，已通知管理员。"},
    "pay_details": {
        "ar": "<b>الدفع عبر {method}</b>\n\nرقم الطلب: <code>{ref}</code>\nالمبلغ: <b>{total} {cur}</b>\nالمعرّف: <code>{account}</code>\n\n{instructions}\n\n"
              "بعد التحويل أرسل هنا <b>صورة إثبات التحويل فقط</b>، ولا حاجة لرقم العملية.",
        "en": "<b>Pay with {method}</b>\n\nOrder: <code>{ref}</code>\nAmount: <b>{total} {cur}</b>\nAccount: <code>{account}</code>\n\n{instructions}\n\n"
              "After paying, just send the transfer screenshot here (no transaction ID needed).",
        "vi": "Thanh toán qua {method}\n\nĐơn: {ref}\nSố tiền: {total} {cur}\nTài khoản: {account}\n\n{instructions}\n\nSau khi chuyển, chỉ cần gửi ảnh chụp chuyển khoản tại đây.", "zh": "通过 {method} 付款\n\n订单：{ref}\n金额：{total} {cur}\n账号：{account}\n\n{instructions}\n\n转账后，在这里发送转账截图即可。"},
    "copy_account": {"ar": "نسخ المعرّف", "en": "Copy account"},
    "copy_amount": {"ar": "نسخ المبلغ", "en": "Copy amount"},
    "copy_ref": {"ar": "نسخ رقم الطلب", "en": "Copy order number"},
    "need_txid": {"ar": "تم استلام صورة الإثبات للطلب <code>{ref}</code>.\nأرسل الآن رقم العملية (Order ID / Transaction ID) من تفاصيل التحويل.",
                  "en": "Payment screenshot received for <code>{ref}</code>.\nNow send the transaction ID (Order ID) from the transfer details.",
        "vi": "Đã nhận ảnh cho đơn {ref}. Hãy gửi mã giao dịch.", "zh": "已收到订单 {ref} 的截图，请发送交易编号。"},
    "in_review": {"ar": "تم استلام إثبات الدفع للطلب <code>{ref}</code> وهو الآن قيد المراجعة. سيصلك إشعار فور التحقق.",
                  "en": "Payment proof for <code>{ref}</code> received and is under review. You'll be notified once verified.",
        "vi": "Đã nhận bằng chứng thanh toán cho đơn {ref}, đang được kiểm tra. Bạn sẽ được thông báo ngay khi xác minh.", "zh": "已收到订单 {ref} 的付款凭证，正在审核，验证后会通知您。"},
    "payment_confirmed": {"ar": "تم تأكيد الدفع للطلب <code>{ref}</code>. جاري تجهيز التسليم.",
                          "en": "Payment for <code>{ref}</code> confirmed. Preparing your delivery.",
        "vi": "Đã xác nhận thanh toán cho đơn {ref}. Đang chuẩn bị giao hàng.", "zh": "订单 {ref} 付款已确认，正在准备交付。"},
    "payment_rejected": {"ar": "لم يتم قبول إثبات الدفع للطلب <code>{ref}</code>.\nالسبب: {reason}\nيمكنك إرسال إثبات صحيح ما دام الحجز قائماً.",
                         "en": "The payment proof for <code>{ref}</code> was not accepted.\nReason: {reason}\nYou can send a correct proof while the reservation is active.",
        "vi": "Bằng chứng thanh toán cho đơn {ref} không được chấp nhận.\nLý do: {reason}\nBạn có thể gửi lại ảnh đúng khi đơn còn được giữ.", "zh": "订单 {ref} 的付款凭证未通过。\n原因：{reason}\n预留期内可重新发送正确的截图。"},
    "order_cancelled": {"ar": "تم إلغاء الطلب <code>{ref}</code>.\nالسبب: {reason}", "en": "Order <code>{ref}</code> was cancelled.\nReason: {reason}",
        "vi": "Đơn {ref} đã bị hủy.\nLý do: {reason}", "zh": "订单 {ref} 已取消。\n原因：{reason}"},
    "order_rejected": {"ar": "تم رفض الطلب <code>{ref}</code>.\nالسبب: {reason}", "en": "Order <code>{ref}</code> was rejected.\nReason: {reason}",
        "vi": "Đơn {ref} bị từ chối.\nLý do: {reason}", "zh": "订单 {ref} 被拒绝。\n原因：{reason}"},
    "order_status": {"ar": "تم تحديث حالة الطلب <code>{ref}</code>: {status}", "en": "Order <code>{ref}</code> status: {status}",
        "vi": "Trạng thái đơn {ref}: {status}", "zh": "订单 {ref} 状态：{status}"},
    "delivered": {
        "ar": "<b>تم التسليم</b>  <code>{ref}</code>\n{n} مزرعة — المستوى {lvl}\nاضغط على القائمة لنسخها:",
        "en": "<b>Delivered</b>  <code>{ref}</code>\n{n} farm(s) — level {lvl}\nTap the list to copy it:",
        "vi": "Đã giao đơn {ref}\n{n} nông trại — cấp {lvl}", "zh": "订单 {ref} 已交付\n{n} 个农场 — 等级 {lvl}"},
    "keep_safe": {"ar": "احفظ البيانات ولا تشاركها مع أحد.", "en": "Keep these details private."},
    "copy_all": {"ar": "نسخ البيانات", "en": "Copy details"},
    "handoff": {"ar": "{text}", "en": "Your conversation has been transferred to our support team. A staff member will reply soon.",
        "vi": "Cuộc trò chuyện đã được chuyển cho nhân viên hỗ trợ. Họ sẽ trả lời sớm.", "zh": "已为您转接客服，工作人员会尽快回复。"},
    "waiting_staff": {"ar": "تم استلام رسالتك، سيرد عليك فريق الدعم قريباً.", "en": "Message received — our support team will reply soon.",
        "vi": "Đã nhận tin nhắn — đội hỗ trợ sẽ trả lời sớm.", "zh": "已收到消息，客服会尽快回复。"},
    "ai_error": {"ar": "عذراً، حدث خلل مؤقت. تم تحويل محادثتك إلى فريق الدعم.",
                 "en": "Sorry, something went wrong. Your chat was transferred to our support team.",
        "vi": "Xin lỗi, có lỗi tạm thời. Cuộc trò chuyện đã được chuyển cho đội hỗ trợ.", "zh": "抱歉，出现临时错误，已为您转接客服。"},
    "summary_expired": {"ar": "انتهت صلاحية هذا الملخص. اطلب من جديد.", "en": "This summary expired. Please ask again."},
    "cancel_done": {"ar": "تم إلغاء الطلب ولم يُحجز شيء.", "en": "Order cancelled — nothing was reserved.",
        "vi": "Đã hủy đơn hàng.", "zh": "订单已取消。"},
    "banned": {"ar": "حسابك موقوف. تواصل مع الدعم.", "en": "Your account is suspended.",
        "vi": "Tài khoản của bạn đã bị khóa.", "zh": "您的账号已被停用。"},
    "photo_no_order": {"ar": "لا يوجد طلب بانتظار الدفع لإرفاق الصورة به. أكّد طلباً واختر وسيلة الدفع أولاً.",
                       "en": "There is no order awaiting payment to attach this screenshot to. Confirm an order and pick a payment method first.",
        "vi": "Không có đơn nào chờ thanh toán để gắn ảnh này. Hãy xác nhận đơn trước.", "zh": "没有待付款的订单可以附加这张截图，请先确认订单。"},
}


def tt(lang: str | None, key: str, **kw) -> str:
    e = T[key]
    s = e.get(lang or "ar") or e.get("en") or e["ar"]
    return s.format(**kw) if kw else s
