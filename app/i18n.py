"""Customer-facing translations. Add a language by adding a column to every entry and to LANGS."""
from __future__ import annotations

LANGS = {"ar": "العربية ", "en": "English "}
DEFAULT = "ar"

T: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------- menu
    "btn_buy": {"ar": "شراء المزارع", "en": "Buy farms"},
    "btn_wallet": {"ar": "محفظتي", "en": "My wallet"},
    "btn_topup": {"ar": "شحن الرصيد", "en": "Top up"},
    "btn_orders": {"ar": "طلباتي", "en": "My orders"},
    "btn_support": {"ar": "الدعم الفني", "en": "Support"},
    "btn_lang": {"ar": "Language / اللغة", "en": "Language / اللغة"},
    "btn_admin": {"ar": "لوحة الإدارة", "en": "Admin panel"},
    "choose_lang": {"ar": "اختر لغتك:\nChoose your language:", "en": "Choose your language:\nاختر لغتك:"},
    "lang_set": {"ar": "تم اختيار اللغة العربية.", "en": "Language set to English."},
    "use_menu": {"ar": "اختر من القائمة بالأسفل ", "en": "Please choose from the menu below "},
    "cancelled": {"ar": "تم الإلغاء.", "en": "Cancelled."},
    "back": {"ar": "رجوع", "en": "Back"},
    "error_generic": {"ar": "حدث خطأ غير متوقع. حاول مرة أخرى أو تواصل مع الدعم.",
                      "en": "Something went wrong. Please try again or contact support."},
    "banned": {"ar": "حسابك موقوف. تواصل مع الدعم الفني.", "en": "Your account is suspended. Please contact support."},
    # ------------------------------------------------------------- browse
    "types_head": {"ar": "<b>اختر نوع المزرعة</b>\n(المستوى • المخزن/الصومعة • السعر (المتوفر))",
                   "en": "<b>Choose a farm type</b>\n(Level • Barn/Silo • Price (in stock))"},
    "no_types": {"ar": "لا توجد مزارع معروضة حالياً، تابعنا قريباً ", "en": "No farms available right now — check back soon "},
    "no_match": {"ar": "لا توجد مزارع مطابقة حالياً.", "en": "No farms match your filter."},
    "out": {"ar": "غير متوفر", "en": "Out of stock"},
    "btn_filter": {"ar": "تصفية حسب LVL / Barn / Silo / Tools / السعر", "en": "Filter by LVL / Barn / Silo / Tools / price"},
    "btn_all_types": {"ar": "كل الأنواع", "en": "All types"},
    "filter_help": {"ar": "اكتب شروط البحث، أمثلة:\n<code>lvl 70</code>\n<code>lvl&gt;=60 price&lt;=15</code>\n"
                          "<code>barn&gt;=4000 silo&gt;=3000</code>\n\nأو /cancel للإلغاء.",
                    "en": "Type your filter, for example:\n<code>lvl 70</code>\n<code>lvl&gt;=60 price&lt;=15</code>\n"
                          "<code>barn&gt;=4000 silo&gt;=3000</code>\n\nor /cancel."},
    "filter_bad": {"ar": "لم أفهم الشروط. مثال: <code>lvl&gt;=70 price&lt;=12</code>",
                   "en": "I couldn't read that. Example: <code>lvl&gt;=70 price&lt;=12</code>"},
    "type_unavailable": {"ar": "هذا النوع غير متاح.", "en": "This farm type is not available."},
    "card_level": {"ar": "المستوى", "en": "Level"},
    "card_barn": {"ar": "المخزن (Barn)", "en": "Barn"},
    "card_silo": {"ar": "الصومعة (Silo)", "en": "Silo"},
    "card_tools": {"ar": "الأدوات: {n} (أدوات أرض)", "en": "Tools: {n} (land tools)"},
    "card_price": {"ar": "السعر", "en": "Price"},
    "card_stock": {"ar": "المتوفر", "en": "In stock"},
    "card_tiers": {"ar": "الأسعار المتاحة:", "en": "Available prices:"},
    "tier_line": {"ar": "• {price} USDT — {n} حساب", "en": "• {price} USDT — {n} accounts"},
    "btn_buy_tier": {"ar": "شراء بـ {price} USDT ({n} متوفر)", "en": "Buy for {price} USDT ({n} left)"},
    "btn_out": {"ar": "غير متوفر حالياً", "en": "Currently out of stock"},
    # ----------------------------------------------------------- quantity
    "qty_ask": {"ar": "<b>كم مزرعة تريد؟</b>\n\nالنوع: <b>{name}</b>\nسعر المزرعة: <b>{price} USDT</b>\n"
                      "المتوفر: {n}\nرصيدك: {balance} USDT\n\nاختر العدد أو اكتبه:",
                "en": "<b>How many farms do you need?</b>\n\nType: <b>{name}</b>\nPrice per farm: <b>{price} USDT</b>\n"
                      "In stock: {n}\nYour balance: {balance} USDT\n\nPick a quantity or type it:"},
    "btn_qty": {"ar": "{q} × = {total}$", "en": "{q} × = {total}$"},
    "btn_qty_other": {"ar": "عدد آخر", "en": "Other amount"},
    "qty_type": {"ar": "اكتب العدد المطلوب (من 1 إلى {max}):", "en": "Type the quantity (1 to {max}):"},
    "qty_bad": {"ar": "العدد يجب أن يكون رقماً بين 1 و {max}.", "en": "Quantity must be a number from 1 to {max}."},
    # ------------------------------------------------------------- confirm
    "confirm": {"ar": "<b>تأكيد الطلب</b>\n\nالنوع: <b>{name}</b>\n{specs}\n\n"
                      "العدد: <b>{qty}</b>\nسعر المزرعة: {price} USDT\n<b>الإجمالي: {total} USDT</b>\n\n"
                      "رصيدك الحالي: {balance} USDT\nالرصيد بعد الشراء: {after} USDT\n\nرقم الطلب: <code>{ref}</code>\n"
                      "صالح لمدة {ttl} دقيقة.",
                "en": "<b>Confirm your order</b>\n\nType: <b>{name}</b>\n{specs}\n\n"
                      "Quantity: <b>{qty}</b>\nPrice per farm: {price} USDT\n<b>Total: {total} USDT</b>\n\n"
                      "Current balance: {balance} USDT\nBalance after purchase: {after} USDT\n\nOrder: <code>{ref}</code>\n"
                      "Valid for {ttl} minutes."},
    "btn_confirm": {"ar": "تأكيد الشراء ({total} USDT)", "en": "Confirm purchase ({total} USDT)"},
    "btn_cancel": {"ar": "إلغاء", "en": "Cancel"},
    "btn_topup_inline": {"ar": "شحن الرصيد", "en": "Top up"},
    "btn_farms": {"ar": "المزارع", "en": "Farms"},
    "processing": {"ar": "<b>جاري تنفيذ الطلب…</b>", "en": "<b>Processing your order…</b>"},
    "processing_short": {"ar": "جاري تنفيذ الطلب…", "en": "Processing…"},
    "bought": {"ar": "<b>تم الشراء بنجاح</b>\nرقم الطلب: <code>{ref}</code>\nالعدد: {qty} — الإجمالي: {total} USDT\n"
                     "تم إرسال بيانات الدخول في الرسالة التالية \nيمكنك عرضها لاحقاً من «طلباتي».",
               "en": "<b>Purchase successful</b>\nOrder: <code>{ref}</code>\nQuantity: {qty} — Total: {total} USDT\n"
                     "Login details are in the next message \nYou can view them again in “My orders”."},
    "bought_partial": {"ar": "تم حجز {qty} حساب لطلبك <code>{ref}</code> لكن تعذّر إرسال بيانات {failed} منها.\n"
                             "تم إبلاغ الإدارة ويمكنك إعادة المحاولة من «طلباتي».",
                       "en": "{qty} accounts were reserved for order <code>{ref}</code> but {failed} could not be delivered.\n"
                             "Support has been notified — you can retry from “My orders”."},
    "order_state": {"ar": "الطلب <code>{ref}</code>: {status}", "en": "Order <code>{ref}</code>: {status}"},
    "buy_cancelled": {"ar": "تم إلغاء الطلب ولم يُخصم أي مبلغ.", "en": "Order cancelled — nothing was charged."},
    "btn_my_orders": {"ar": "طلباتي", "en": "My orders"},
    # --------------------------------------------------------- credentials
    "creds": {"ar": "<b>تم شراء المزرعة بنجاح</b>{part}\n\nرقم الطلب: <code>{ref}</code>\n"
                    "النوع: {name}\n{specs}\nالسعر: {price} USDT\n\n"
                    "<b>ID:</b> <code>{login}</code>\n<b>Password:</b> <code>{password}</code>\n\n"
                    "احفظ البيانات في مكان آمن ولا تشاركها مع أحد.",
              "en": "<b>Your farm is ready</b>{part}\n\nOrder: <code>{ref}</code>\n"
                    "Type: {name}\n{specs}\nPrice: {price} USDT\n\n"
                    "<b>ID:</b> <code>{login}</code>\n<b>Password:</b> <code>{password}</code>\n\n"
                    "Keep these details safe and never share them."},
    "creds_batch": {"ar": "<b>تم شراء {n} مزارع بنجاح</b>\n\nرقم الطلب: <code>{ref}</code>\n"
                          "النوع: {name}\n{specs}\nالإجمالي: {total} USDT\n\n"
                          "اضغط على القائمة لنسخها كاملة ",
                    "en": "<b>{n} farms purchased</b>\n\nOrder: <code>{ref}</code>\n"
                          "Type: {name}\n{specs}\nTotal: {total} USDT\n\n"
                          "Tap the list to copy it all "},
    "creds_batch_more": {"ar": "تكملة القائمة ({a}–{b} من {n}):", "en": "List continued ({a}–{b} of {n}):"},
    "creds_safe": {"ar": "احفظ البيانات في مكان آمن ولا تشاركها مع أحد.", "en": "Keep these details safe and never share them."},
    "btn_show_batch": {"ar": "عرض كل حسابات هذا الشراء ({n})", "en": "Show all accounts of this purchase ({n})"},
    "copy_id": {"ar": "نسخ ID", "en": "Copy ID"},
    "copy_pw": {"ar": "نسخ Password", "en": "Copy password"},
    "copy_all": {"ar": "نسخ البيانات كاملة", "en": "Copy all details"},
    # -------------------------------------------------------------- wallet
    "wallet": {"ar": "<b>محفظتي</b>\n\nالرصيد الحالي: <b>{balance} USDT</b>", "en": "<b>My wallet</b>\n\nBalance: <b>{balance} USDT</b>"},
    "last_tx": {"ar": "آخر العمليات:", "en": "Recent transactions:"},
    "no_tx": {"ar": "لا توجد عمليات بعد.", "en": "No transactions yet."},
    "btn_history": {"ar": "السجل الكامل", "en": "Full history"},
    "history_head": {"ar": "<b>سجل العمليات</b> (صفحة {page})", "en": "<b>Transaction history</b> (page {page})"},
    "prev": {"ar": "السابق", "en": "Previous"},
    "next": {"ar": "التالي ", "en": "Next "},
    "btn_wallet_back": {"ar": "المحفظة", "en": "Wallet"},
    "kind_deposit": {"ar": "شحن رصيد", "en": "Top-up"},
    "kind_purchase": {"ar": "شراء مزرعة", "en": "Farm purchase"},
    "kind_refund": {"ar": "استرداد", "en": "Refund"},
    "kind_admin_credit": {"ar": "إضافة من الإدارة", "en": "Credit by admin"},
    "kind_admin_debit": {"ar": "خصم من الإدارة", "en": "Debit by admin"},
    # --------------------------------------------------------------- topup
    "topup_start": {"ar": "<b>شحن الرصيد عبر Binance Pay</b>\n\nاختر المبلغ أو اكتبه بعملة USDT (من {min} إلى {max}):",
                    "en": "<b>Top up with Binance Pay</b>\n\nPick an amount or type it in USDT ({min} to {max}):"},
    "topup_cancel_btn": {"ar": "إلغاء طلب الشحن", "en": "Cancel top-up"},
    "topup_details": {"ar": "طلب الشحن: <code>{ref}</code>\nالمبلغ: <b>{amount} USDT</b>\n\n"
                            "معرّف Binance Pay:\n<code>{pay_id}</code>\n\n{instructions}\n\n<b>أرسل الآن لقطة شاشة إثبات الدفع.</b>",
                      "en": "Top-up request: <code>{ref}</code>\nAmount: <b>{amount} USDT</b>\n\n"
                            "Binance Pay ID:\n<code>{pay_id}</code>\n\n{instructions}\n\n<b>Now send a screenshot of your payment.</b>"},
    "copy_pay_id": {"ar": "نسخ معرّف الدفع", "en": "Copy Pay ID"},
    "copy_amount": {"ar": "نسخ المبلغ", "en": "Copy amount"},
    "topup_cancelled": {"ar": "تم إلغاء طلب الشحن.", "en": "Top-up request cancelled."},
    "photo_ok_txid": {"ar": "تم استلام الصورة.\n\nأرسل الآن <b>رقم الطلب (Order ID)</b> الظاهر في تفاصيل التحويل داخل تطبيق Binance.",
                      "en": "Screenshot received.\n\nNow send the <b>Order ID</b> shown in the transfer details in the Binance app."},
    "photo_wrong": {"ar": "أرسل لقطة شاشة إثبات الدفع كصورة، أو /cancel للإلغاء.",
                    "en": "Please send the payment screenshot as a photo, or /cancel."},
    "topup_submitted": {"ar": "تم استلام طلب الشحن <code>{ref}</code> وهو الآن <b>قيد المراجعة</b>.\nسيصلك إشعار فور التحقق من وصول المبلغ.",
                        "en": "Top-up <code>{ref}</code> received and is now <b>under review</b>.\nYou'll be notified as soon as the payment is confirmed."},
    # -------------------------------------------------------------- orders
    "orders_head": {"ar": "<b>طلباتي</b>", "en": "<b>My orders</b>"},
    "no_orders": {"ar": "لا توجد طلبات شراء بعد.", "en": "No orders yet."},
    "last_deposits": {"ar": "<b>آخر طلبات الشحن:</b>", "en": "<b>Recent top-ups:</b>"},
    "order_card": {"ar": "<b>الطلب</b> <code>{ref}</code>\n\nالنوع: {name}\n{specs}\n"
                         "السعر: {price} USDT\nالحالة: <b>{status}</b>\nالتاريخ: {date}",
                   "en": "<b>Order</b> <code>{ref}</code>\n\nType: {name}\n{specs}\n"
                         "Price: {price} USDT\nStatus: <b>{status}</b>\nDate: {date}"},
    "delivered_at": {"ar": "تم التسليم: {date}", "en": "Delivered: {date}"},
    "note": {"ar": "ملاحظة: {note}", "en": "Note: {note}"},
    "btn_show_creds": {"ar": "عرض بيانات الدخول", "en": "Show login details"},
    "btn_retry": {"ar": "إعادة إرسال البيانات", "en": "Resend login details"},
    "order_missing": {"ar": "الطلب غير موجود.", "en": "Order not found."},
    "sent_ok": {"ar": "تم إرسال البيانات", "en": "Details sent"},
    "sent_fail": {"ar": "تعذر الإرسال، تم إبلاغ الإدارة.", "en": "Could not send — support has been notified."},
    "sent_ok_msg": {"ar": "تم إرسال بيانات الدخول بنجاح ", "en": "Login details sent "},
    "st_pending": {"ar": "بانتظار التأكيد", "en": "Awaiting confirmation"},
    "st_processing": {"ar": "قيد المعالجة", "en": "Processing"},
    "st_completed": {"ar": "مكتمل", "en": "Completed"},
    "st_cancelled": {"ar": "ملغي", "en": "Cancelled"},
    "st_needs_review": {"ar": "يحتاج إلى مراجعة", "en": "Under review"},
    "dst_awaiting_payment": {"ar": "بانتظار الدفع", "en": "Awaiting payment"},
    "dst_under_review": {"ar": "قيد المراجعة", "en": "Under review"},
    "dst_approved": {"ar": "مقبول", "en": "Approved"},
    "dst_rejected": {"ar": "مرفوض", "en": "Rejected"},
    "dst_cancelled": {"ar": "ملغي", "en": "Cancelled"},
    # ------------------------------------------------------------- support
    "support": {"ar": "<b>الدعم الفني</b>\n\n{text}\n\nمعرّفك في البوت: <code>{uid}</code>\nأرفق رقم الطلب أو الشحن عند التواصل لتسريع الخدمة.",
                "en": "<b>Support</b>\n\n{text}\n\nYour user ID: <code>{uid}</code>\nInclude your order or top-up number for faster help."},
    "btn_contact": {"ar": "مراسلة الدعم", "en": "Message support"},
    # ------------------------------------------------------- notifications
    "n_deposit_ok": {"ar": "<b>تم قبول طلب الشحن</b> <code>{ref}</code>\nأُضيف إلى محفظتك: <b>{amount} USDT</b>{extra}\nرصيدك الحالي: <b>{balance} USDT</b>",
                     "en": "<b>Top-up approved</b> <code>{ref}</code>\nAdded to your wallet: <b>{amount} USDT</b>{extra}\nBalance: <b>{balance} USDT</b>"},
    "n_deposit_extra": {"ar": "\n(المبلغ المطلوب كان {requested} USDT)", "en": "\n(requested amount was {requested} USDT)"},
    "n_deposit_rejected": {"ar": "<b>تم رفض طلب الشحن</b> <code>{ref}</code>\nالسبب: {reason}\nإذا كان لديك استفسار تواصل مع الدعم الفني.",
                           "en": "<b>Top-up rejected</b> <code>{ref}</code>\nReason: {reason}\nContact support if you have any questions."},
    "n_adjust": {"ar": "تم تعديل رصيدك من الإدارة: <b>{amount} USDT</b>\nالسبب: {reason}\nالرصيد الحالي: <b>{balance} USDT</b>\nرقم العملية: <code>{ref}</code>",
                 "en": "Your balance was adjusted by support: <b>{amount} USDT</b>\nReason: {reason}\nBalance: <b>{balance} USDT</b>\nTransaction: <code>{ref}</code>"},
    "n_refund": {"ar": "تم إلغاء الطلب <code>{ref}</code> واسترداد <b>{amount} USDT</b> إلى محفظتك.\nالسبب: {reason}",
                 "en": "Order <code>{ref}</code> was cancelled and <b>{amount} USDT</b> refunded to your wallet.\nReason: {reason}"},
}

# English versions of service errors (Arabic text comes from StoreError.message)
ERRORS_EN = {
    "insufficient_funds": "Insufficient balance. Your balance is {balance} USDT, the total is {total} USDT.",
    "out_of_stock": "Sorry, there isn't enough stock at this price. Nothing was charged.",
    "unavailable": "This farm type is not available right now.",
    "banned": "Your account is suspended. Please contact support.",
    "expired": "This order expired — please start again.",
    "already": "This order has already been processed.",
    "not_found": "Not found.",
    "bad_amount": "Invalid amount. It must be between {min} and {max} USDT.",
    "bad_qty": "Invalid quantity.",
    "bad_state": "There is no open request for this step. Start again from the menu.",
    "proof_reused": "This proof was already used for another top-up.",
    "bad_txid": "Invalid Order ID. Copy it from the transfer details in Binance.",
    "not_retryable": "This order can't be resent.",
    "duplicate": "This operation was already done.",
}


def t(lang: str | None, key: str, **kw) -> str:
    entry = T[key]
    text = entry.get(lang or DEFAULT) or entry[DEFAULT]
    return text.format(**kw) if kw else text


def err(lang: str | None, exc) -> str:
    """Translate a StoreError for the customer."""
    if lang == "en" and exc.code in ERRORS_EN:
        try:
            return "" + ERRORS_EN[exc.code].format(**(exc.params or {}))
        except (KeyError, IndexError):
            return "" + ERRORS_EN[exc.code].split(".")[0] + "."
    return "" + exc.message


def all_texts(key: str) -> set[str]:
    return set(T[key].values())


def render(lang: str | None, key: str, params: dict) -> str:
    """t() with nested (key, params) values resolved in the same language; None values become ''."""
    out = {}
    for k, v in params.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) and v[0] in T:
            out[k] = t(lang, v[0], **v[1])
        else:
            out[k] = v
    return t(lang, key, **out)
