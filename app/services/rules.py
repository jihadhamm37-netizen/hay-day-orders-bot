"""HD Agent free built-in assistant (no external AI, no cost) — v2: a context-aware dialog.

It keeps the conversation state (how many farms, which type, what it is waiting for), understands Arabic dialects
(Iraqi, Jordanian, Gulf, Levantine, Egyptian) with common spelling mistakes, English, Vietnamese and Chinese,
and fills the order step by step: quantity → farm type → price from the database → explicit confirmation.
Every number it says comes from the database; nothing is reserved or charged before the customer says yes."""
from __future__ import annotations

import json
import re
import unicodedata

from ..core import Core, StoreError, fmt
from . import farms as farms_svc
from . import orders as orders_svc
from . import payments as pay_svc
from .ai import AgentResult
from .system import get_settings

LANGS = ("ar", "en", "vi", "zh")

# ------------------------------------------------------------------ text normalisation
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹０１２３４５６７８９", "012345678901234567890123456789")
_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": "",
                         "گ": "ك", "ڤ": "ف", "چ": "ج", "پ": "ب", "ک": "ك", "ی": "ي"})
_AR_DIAC = re.compile(r"[\u064B-\u065F\u0670]")
_ZH_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def norm(text: str) -> str:
    t = (text or "").translate(_DIGITS)
    t = _AR_DIAC.sub("", t).translate(_AR_MAP)
    t = re.sub(r"(?<=\d)[,٬](?=\d{3}\b)", "", t)
    t = re.sub(r"([^\d\s])\1{2,}", r"\1", t)              # مرحباااا → مرحبا, hiii → hi
    t = t.replace("،", " ").replace("؟", " ? ").replace("!", " ! ")
    return re.sub(r"\s+", " ", t).strip().lower()


def strip_vi(text: str) -> str:
    """Vietnamese without accents (customers often type without them)."""
    t = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", "".join(c for c in t if unicodedata.category(c) != "Mn")).replace("đ", "d")


def script_lang(text: str) -> str | None:
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    if re.search(r"[\u4E00-\u9FFF]", text):
        return "zh"
    if re.search(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", text.lower()):
        return "vi"
    return None


# ------------------------------------------------------------------ vocabulary (patterns run on norm()'d text)
def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), re.I)


# Arabic is matched as substrings (prefixes و/ب/ال/ف attach to words); latin words with boundaries.
GREET = _rx(r"^(?:و)?(?:مرحب|مرحبا|هلا|هلو|هاي|اهلين|اهلا|السلام|سلام|صباح|مسا|شلونك|شلونكم|كيفك|كيفكم|ازيك|شخبارك|يا هلا)",
            r"\b(?:hi|hello|hey|salam|good (?:morning|evening))\b", r"\b(?:xin chao|chao|alo)\b", r"你好|您好|哈喽|嗨")
BUY = _rx(r"اريد|ابي|ابغي|ابغا|بدي|بدنا|بغيت|بغينا|عايز|عاوز|محتاج|احتاج|نحتاج|حاب|ودي|اشتري|نشتري|شراء|"
          r"اطلب|نطلب|عندك|عندكم|عدكم|عدك|متوفر|موجود|في عندكم|هاتلي|هاتو|جيبلي|جيبو|انطيني|نطيني|اعطيني|عطني|اشوف",
          r"\b(?:want|wanna|need|buy|purchase|order|get|have|looking for|sell|show)\b",
          r"\b(?:mua|muon|can|co .*khong|ban|dat)\b", r"买|要|想要|需要|有没有|有吗|购买|下单|来")
FARM = _rx(r"مزار|مزرع|مزرعه|حساب|حسابات|فارم|فارمات|هاي دي|هايدي", r"\bfarms?\b|\baccounts?\b|\bhay ?day\b",
           r"\bnong trai\b|\btrang trai\b|\bfarm\b", r"农场|账号|帐号")
YES = _rx(r"^(?:و)?(?:نعم|اي|ايه|ايوه|ايوا|اكيد|تمام|موافق|اوكي|اوك|ماشي|يلا|زين|صح|اكد|اوكيه|اكدت|بلي|طيب|خلاص|"
          r"توكل|اي نعم|اي والله|يس|يب|ياريت|يا ريت|اوكي|مضبوط|حلو|اوكي اكد|نعم اكد|اكيد اكد|اشتري|اوافق)\b",
          r"^(?:yes|yeah|yep|yup|ok|okay|sure|confirm|go ahead|do it|deal)\b",
          r"^(?:co|vang|dong y|ok|duoc|xac nhan|u)\s*[.!]*$", r"^(?:是|好|好的|可以|确认|对|行|没问题|嗯)")
NO = _rx(r"^(?:و)?(?:لا|كلا|الغ|الغي|الغاء|لا اريد|ما اريد|مابي|ما ابي|ما بدي|مش عايز|بلاش|اتركها|لا شكرا|لغي|كنسل)\b",
         r"^(?:no|nope|cancel|stop|never ?mind)\b", r"^(?:khong|huy|thoi)\b", r"^(?:不|不要|取消|算了)")
STATUS = _rx(r"طلبي|طلباتي|وين طلب|شنو صار|شصار|حاله الطلب|حالة الطلب|متي يوصل|وصل الطلب|طلبيتي",
             r"\bmy orders?\b|\border status\b|\bwhere is my\b", r"\bdon hang\b|\btrang thai\b", r"订单|我的订单|状态")
PAY = _rx(r"دفع|ادفع|الدفع|تحويل|احول|حول|بايننس|باينانس|بينانس|طرق الدفع|وين ادفع|شلون ادفع|كيف ادفع",
          r"\bpay(?:ment)?\b|\bbinance\b|\btransfer\b", r"\bthanh toan\b|\bchuyen khoan\b", r"付款|支付|转账|怎么付")
PRICE = _rx(r"سعر|اسعار|بكم|بجم|شكد|قديش|قداش|كم سعر|كم الحق|بقديش|تكلف|التكلفه|كم ثمن|بكام",
            r"\bprices?\b|\bcost\b|\bhow much\b", r"\bgia\b|\bbao nhieu\b", r"价格|多少钱|价钱|多少")
DISCOUNT = _rx(r"خصم|تخفيض|ارخص|نزل السعر|نزلي|سعر خاص|تنزيل", r"\bdiscount\b|\bcheaper\b", r"\bgiam gia\b|\bre hon\b", r"便宜|折扣|打折")
THANKS = _rx(r"شكرا|مشكور|يعطيك العافيه|تسلم|ممنون|الله يخليك|حبيبي", r"\bthanks?\b|\bthank you\b|\bthx\b", r"\bcam on\b", r"谢谢|多谢")
COMPLAIN = _rx(r"مشكل|شكوي|اشتكي|غلط|خطا|ما يشتغل|مايشتغل|لا يعمل|ما اشتغل|ما يفتح|مايفتح|نصب|حرامي|ما وصل|ماوصل|لم يصل|"
               r"ما وصلت|ما تشتغل|ماتشتغل|ما تفتح|ماتفتح|ما تدخل|ماتدخل|مو شغال|مش شغال|ما شغال|مو زين|ما زبط|ما ضبط|خربان|معطل|استرجاع|ارجاع|رجعلي|ما يدخل|مايدخل|انسرق|محظور|باند|موظف|انسان|الاداره|الدعم|كلم احد",
               r"\bproblem\b|\bissue\b|\bcomplain|\brefund\b|\bscam\b|\bwrong\b|\bnot working\b|\bhuman\b|\bsupport\b|\bbanned\b",
               r"\bloi\b|\bkhieu nai\b|\bhoan tien\b|\bkhong vao duoc\b|\bho tro\b", r"问题|投诉|退款|骗|不能用|客服|人工")

SPEC_KW = {
    "lvl": r"(?:مستوي|مستوا|مستو|المستوي|المستوا|مستواها|لفل|ليفل|لول|لفيل|level|lvl|lv|cap|cấp|等级|级)",
    "barn": r"(?:مخزن|المخزن|مخازن|حظيره|الحظيره|حضيره|الحضيره|بارن|barn|kho(?! thoc)|仓库|谷仓)",
    "silo": r"(?:صومعه|الصومعه|سايلو|سيلو|سلو|silo|kho thoc|粮仓|筒仓)",
    "tools": r"(?:ادوات ارض|ادوات الارض|ادوات|الادوات|اداوت|عدد ارض|tools?|land|cong cu|工具)",
}
NUMV = r"(\d+(?:[.,]\d+)?\s*(?:k\b|ك\b|الف|الاف|الآف|الف)?)"
ZH_QTY = r"([一两二三四五六七八九十]|\d+)\s*(?:个|块)?\s*农场"
WORD_NUMS = [  # on norm()'d text
    (r"مزرعتين|مزرعتان|حسابين|فارمين|ثنتين|اثنين|اثنتين|ثنين|زوج|\btwo\b|\bhai\b", 2),
    (r"ثلاث|تلات|ثلاثه|تلاته|\bthree\b|\bba\b", 3), (r"اربع|اربعه|\bfour\b|\bbon\b", 4),
    (r"خمس|خمسه|\bfive\b|\bnam\b", 5), (r"\bسته\b|\bست\b|\bsix\b|\bsau\b", 6), (r"سبع|سبعه|\bseven\b|\bbay\b", 7),
    (r"ثمان|ثمانيه|ثمنه|تمنيه|\beight\b|\btam\b", 8), (r"تسع|تسعه|\bnine\b|\bchin\b", 9), (r"عشر|عشره|\bten\b|\bmuoi\b", 10),
    (r"وحده|واحده|واحد|مزرعه وحده|مزرعه واحده|\bone\b|\bmot\b|\ba farm\b|(?:^|\s)مزرعه(?:\s|$|\?)|一个农场", 1),
]


def _num(raw: str) -> int | None:
    m = re.match(r"(\d+(?:[.,]\d+)?)\s*(k|ك|الف|الاف|الآف)?", raw.strip(), re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return int(v * 1000) if m.group(2) else int(v)


def parse(text: str) -> dict:
    """Extract level / barn / silo / tools / quantity from free text (any supported language)."""
    t = norm(text)
    tv = strip_vi(t)
    out: dict = {}
    used: list[tuple[int, int]] = []
    for key, kw in SPEC_KW.items():
        for src in (t, tv):
            m = (re.search(kw + r"\s*(?:[:=]|هو|هي|يكون|بس|فقط|تقريبا)?\s*" + NUMV, src, re.I)
                 or re.search(NUMV + r"\s*" + kw, src, re.I))
            if m:
                out[key] = _num(m.group(1))
                if src is t:
                    used.append(m.span())
                break
    rest = t
    for a, b in sorted(used, reverse=True):
        rest = rest[:a] + " " * (b - a) + rest[b:]
    restv = strip_vi(rest)
    m = (re.search(r"(\d+)\s*(?:" + FARM.pattern + r")", restv, re.I)
         or re.search(r"(?:" + FARM.pattern + r")\s*(?:عدد|عددها|عدده)?\s*(\d+)\b", restv, re.I)
         or re.search(r"(?:عدد|كميه|العدد|x|×|so luong|数量)\s*(\d+)", restv, re.I))
    zm = re.search(ZH_QTY, rest)
    if m:
        out["qty"] = int(m.group(1))
    elif zm:
        out["qty"] = _ZH_NUM.get(zm.group(1)) or int(zm.group(1))
    else:
        for pat, n in WORD_NUMS:
            if re.search(pat, restv, re.I):
                out["qty"] = n
                break
    return out


def bare_number(text: str) -> int | None:
    """'3', 'بدي 3', 'ابي 5', 'خلي 4', 'i want 2', '3个' — a number with no spec keyword attached."""
    t = norm(text)
    if any(re.search(kw, t, re.I) for kw in SPEC_KW.values()):
        return None
    nums = re.findall(r"\d+", t)
    if len(nums) == 1 and len(t) <= 40 and int(nums[0]) <= 1000:
        return int(nums[0])
    for k, v in _ZH_NUM.items():
        if t.strip(" 个块吧要") == k:
            return v
    return None


# ------------------------------------------------------------------ replies in 4 languages
R = {
    "welcome": {"ar": "أهلاً وسهلاً بك في {store} 🌾 كيف أقدر أساعدك؟", "en": "Welcome to {store} 🌾 How can I help you?",
                "vi": "Chào mừng bạn đến với {store} 🌾 Tôi có thể giúp gì cho bạn?", "zh": "欢迎来到 {store} 🌾 有什么可以帮您？"},
    "ask_qty": {"ar": "أهلاً بك! كم مزرعة تحتاج؟", "en": "Sure! How many farms do you need?",
                "vi": "Được! Bạn cần bao nhiêu nông trại?", "zh": "好的！您需要几个农场？"},
    "ask_qty_for": {"ar": "متوفر لك:\n{offer}\n\nكم مزرعة تحتاج منها؟", "en": "Available:\n{offer}\n\nHow many do you need?",
                    "vi": "Hiện có:\n{offer}\n\nBạn cần bao nhiêu?", "zh": "有货：\n{offer}\n\n需要几个？"},
    "ask_type": {"ar": "أكيد! ما نوع المزارع التي تريدها؟ هذه المتوفرة الآن:\n\n{list}\n\nاكتب رقم النوع، أو المستوى الذي تريده.",
                 "en": "Sure! Which type of farm would you like? Available now:\n\n{list}\n\nReply with the type number or the level you want.",
                 "vi": "Được! Bạn muốn loại nông trại nào? Hiện có:\n\n{list}\n\nTrả lời số thứ tự hoặc cấp độ bạn muốn.",
                 "zh": "好的！您想要哪种农场？目前有：\n\n{list}\n\n请回复编号或想要的等级。"},
    "no_match": {"ar": "لا يوجد نوع مطابق تماماً لطلبك. هذه أقرب الأنواع المتوفرة:\n\n{list}\n\nاكتب رقم النوع الذي يناسبك.",
                 "en": "Nothing matches exactly. Closest available types:\n\n{list}\n\nReply with the number that suits you.",
                 "vi": "Không có loại khớp chính xác. Các loại gần nhất:\n\n{list}\n\nTrả lời số thứ tự phù hợp.",
                 "zh": "没有完全符合的。最接近的有：\n\n{list}\n\n请回复合适的编号。"},
    "no_stock": {"ar": "للأسف لا توجد مزارع متوفرة حالياً. جرّب لاحقاً.", "en": "Sorry, no farms are in stock right now. Please check later.",
                 "vi": "Xin lỗi, hiện không còn nông trại nào. Vui lòng quay lại sau.", "zh": "抱歉，目前没有库存，请稍后再来。"},
    "only": {"ar": "المتوفر من هذا النوع {n} فقط. كم تريد منها؟", "en": "Only {n} available of this type. How many would you like?",
             "vi": "Loại này chỉ còn {n}. Bạn muốn bao nhiêu?", "zh": "这种只剩 {n} 个。您要几个？"},
    "quote": {"ar": "تمام، طلبك {q} ({offer}).\nسعر المزرعة الواحدة {p} {c}، والمجموع الكلي {t} {c}.\n\nهل تؤكد طلبك للمتابعة؟ ✅",
              "en": "Great — your order is {q} farm(s) ({offer}).\nPrice per farm {p} {c}, total {t} {c}.\n\nDo you confirm your order? ✅",
              "vi": "Được — đơn của bạn: {q} nông trại ({offer}).\nGiá mỗi nông trại {p} {c}, tổng cộng {t} {c}.\n\nBạn xác nhận đơn hàng chứ? ✅",
              "zh": "好的，您的订单：{q} 个农场（{offer}）。\n单价 {p} {c}，总计 {t} {c}。\n\n确认下单吗？✅"},
    "confirmed": {"ar": "تم تأكيد طلبك وحجز المزارع لك ✅ حوّل المبلغ بالضبط حسب التفاصيل التالية، ثم أرسل صورة التحويل فقط من زر المرفقات 📎",
                  "en": "Order confirmed and farms reserved ✅ Transfer the exact amount below, then send only the transfer screenshot with the 📎 button.",
                  "vi": "Đã xác nhận và giữ nông trại cho bạn ✅ Hãy chuyển đúng số tiền bên dưới, rồi gửi ảnh chụp chuyển khoản bằng nút 📎.",
                  "zh": "订单已确认，农场已为您保留 ✅ 请按下方信息转账准确金额，然后用 📎 按钮发送转账截图即可。"},
    "cancelled": {"ar": "تم إلغاء الطلب {ref}. إذا تحتاج شيئاً آخر أنا هنا.", "en": "Order {ref} cancelled. I'm here if you need anything else.",
                  "vi": "Đã hủy đơn {ref}. Cần gì cứ nhắn tôi.", "zh": "订单 {ref} 已取消。还需要什么请告诉我。"},
    "ok_no": {"ar": "تمام، بدون مشكلة. إذا احتجت مزارع اكتب لي.", "en": "No problem. Message me whenever you need farms.",
              "vi": "Không sao. Khi cần nông trại cứ nhắn tôi.", "zh": "没问题，需要农场随时找我。"},
    "confirm_what": {"ar": "ما عندك طلب بانتظار التأكيد. تحب أساعدك تطلب مزارع؟ كم مزرعة تحتاج؟",
                     "en": "There's no order waiting for confirmation. Would you like to order farms? How many?",
                     "vi": "Bạn chưa có đơn nào chờ xác nhận. Bạn muốn đặt bao nhiêu nông trại?", "zh": "目前没有待确认的订单。您想买几个农场？"},
    "status_none": {"ar": "لا توجد طلبات لك بعد.", "en": "You have no orders yet.", "vi": "Bạn chưa có đơn hàng nào.", "zh": "您还没有订单。"},
    "pay": {"ar": "طرق الدفع المتاحة: {m}.\nبعد تأكيد الطلب تظهر لك تفاصيل الدفع والمبلغ. حوّل المبلغ بالضبط ثم أرسل صورة التحويل فقط، وبعد تأكيد الإدارة تظهر لك بيانات المزارع هنا.",
            "en": "Payment methods: {m}.\nAfter you confirm an order you get the payment details. Transfer the exact amount and send only the screenshot; your farms appear here once staff verify it.",
            "vi": "Phương thức thanh toán: {m}.\nSau khi xác nhận đơn, bạn sẽ thấy thông tin thanh toán. Chuyển đúng số tiền rồi gửi ảnh chụp; nông trại sẽ hiện ở đây sau khi được duyệt.",
            "zh": "支付方式：{m}。\n确认订单后会显示付款信息。请转账准确金额并发送截图，审核通过后农场信息会显示在这里。"},
    "discount": {"ar": "أسعارنا ثابتة، لكن أقدر أساعدك تختار النوع الأنسب لميزانيتك. كم مزرعة تحتاج؟",
                 "en": "Our prices are fixed, but I can help you pick the best type for your budget. How many farms do you need?",
                 "vi": "Giá cố định, nhưng tôi có thể giúp bạn chọn loại phù hợp ngân sách. Bạn cần bao nhiêu?", "zh": "价格是固定的，但我可以帮您选最合适的。您需要几个？"},
    "thanks": {"ar": "العفو! أنا بالخدمة دائماً 🌾", "en": "You're welcome! Always happy to help 🌾", "vi": "Không có gì! Luôn sẵn lòng 🌾", "zh": "不客气！随时为您服务 🌾"},
    "unclear": {"ar": "ما فهمت عليك تماماً 🙏 تقصد تشتري مزارع؟ اكتب العدد ونوع المزرعة، مثلاً: «3 مزارع مستوى 50».",
                "en": "Sorry, I didn't quite get that 🙏 Do you want to buy farms? Tell me how many and which type, e.g. “3 farms level 50”.",
                "vi": "Xin lỗi, tôi chưa hiểu 🙏 Bạn muốn mua nông trại? Hãy cho biết số lượng và loại, ví dụ: “3 nông trại cấp 50”.",
                "zh": "抱歉，我没太明白 🙏 您是要买农场吗？请告诉我数量和类型，例如“3个农场 等级50”。"},
    "pending_hint": {"ar": "\n\nطلبك {ref} بانتظار تأكيدك: اكتب «نعم» للتأكيد أو «لا» للإلغاء.",
                     "en": "\n\nYour order {ref} is waiting: reply “yes” to confirm or “no” to cancel.",
                     "vi": "\n\nĐơn {ref} đang chờ: trả lời “có” để xác nhận hoặc “không” để hủy.", "zh": "\n\n订单 {ref} 待确认：回复“是”确认，或“不”取消。"},
}
OFFER_FMT = {
    "ar": "مستوى {lvl} — مخزن {barn}، صومعة {silo}، أدوات {tools} — {price} {cur} (متوفر {n})",
    "en": "Level {lvl} — barn {barn}, silo {silo}, tools {tools} — {price} {cur} ({n} available)",
    "vi": "Cấp {lvl} — kho {barn}, silo {silo}, công cụ {tools} — {price} {cur} (còn {n})",
    "zh": "等级 {lvl} — 仓库 {barn}，粮仓 {silo}，工具 {tools} — {price} {cur}（剩 {n}）",
}
SHORT_FMT = {"ar": "مستوى {lvl}", "en": "level {lvl}", "vi": "cấp {lvl}", "zh": "等级 {lvl}"}


def r(lang: str, key: str, **kw) -> str:
    return R[key].get(lang, R[key]["en"]).format(**kw)


def offer_text(o: dict, lang: str) -> str:
    return OFFER_FMT.get(lang, OFFER_FMT["en"]).format(lvl=o["lvl"], barn=o["barn"], silo=o["silo"], tools=o["tools"],
                                                       price=fmt(o["price"]), cur=o["currency"], n=o["available"])


def offer_list(offers: list[dict], lang: str) -> str:
    return "\n".join(f"{i + 1}) {offer_text(o, lang)}" for i, o in enumerate(offers))


# ------------------------------------------------------------------ conversation state
async def load_state(core: Core, cid: int) -> dict:
    a = await core.pool.fetchval("SELECT awaiting FROM customers WHERE id=$1", cid)
    if a and a.startswith("dlg:"):
        try:
            return json.loads(a[4:])
        except ValueError:
            pass
    return {}


async def save_state(core: Core, cid: int, st: dict) -> None:
    val = ("dlg:" + json.dumps(st, ensure_ascii=False)) if st else None
    await core.pool.execute("UPDATE customers SET awaiting=$2 WHERE id=$1 AND (awaiting IS NULL OR awaiting LIKE 'dlg:%')", cid, val)


def reply_lang(text: str, chosen: str | None) -> str:
    s = script_lang(text)
    chosen = chosen if chosen in LANGS else "ar"
    if s:
        return s
    if re.search(r"[a-z]", text.lower()):
        return chosen if chosen in ("en", "vi") else "en"
    return chosen


async def _matching(core: Core, spec: dict) -> list[dict]:
    return await farms_svc.search_offers(core, min_level=spec.get("lvl"), max_level=spec.get("lvl"), min_barn=spec.get("barn"),
                                         min_silo=spec.get("silo"), min_tools=spec.get("tools"), limit=20)


# ------------------------------------------------------------------ the dialog
async def respond(core: Core, customer: dict) -> AgentResult:
    cid = customer["id"]
    raw = await core.pool.fetchval("SELECT content FROM messages WHERE customer_id=$1 AND role='user' ORDER BY id DESC LIMIT 1", cid) or ""
    t = norm(raw)
    tv = strip_vi(t)
    lang = reply_lang(raw, customer.get("lang"))
    res = AgentResult()
    st = await load_state(core, cid)
    pending = await core.pool.fetchrow(
        "SELECT * FROM orders WHERE customer_id=$1 AND status='pending_confirmation' ORDER BY id DESC LIMIT 1", cid)
    p = parse(raw)
    has_spec = bool({"lvl", "barn", "silo", "tools"} & p.keys())
    m = lambda rx: bool(rx.search(t) or rx.search(tv))  # noqa: E731

    async def finish(text: str, state: dict | None = None) -> AgentResult:
        res.text = text
        await save_state(core, cid, state if state is not None else st)
        return res

    # 1) complaints / problems → staff
    if m(COMPLAIN):
        res.handoff = "شكوى أو مشكلة من العميل"
        await save_state(core, cid, {})
        return res

    # 2) explicit yes / no
    short_msg = len(t.split()) <= 4
    if m(YES) and short_msg and not has_spec and "qty" not in p:
        if pending:
            try:
                o = await orders_svc.confirm(core, cid, pending["id"])
            except StoreError as e:
                return await finish(e.message, {})
            res.confirmed = o
            return await finish(r(lang, "confirmed"), {})
        if st.get("offer") and st.get("qty"):
            pass                                   # fall through: prepare what we were discussing
        else:
            return await finish(r(lang, "confirm_what"), {"expect": "qty"})
    if m(NO) and short_msg and not has_spec and "qty" not in p and bare_number(raw) is None:
        open_o = pending or await core.pool.fetchrow(
            "SELECT * FROM orders WHERE customer_id=$1 AND status='awaiting_payment' ORDER BY id DESC LIMIT 1", cid)
        if open_o:
            await orders_svc.cancel_by_customer(core, cid, open_o["id"])
            return await finish(r(lang, "cancelled", ref=open_o["ref"]), {})
        return await finish(r(lang, "ok_no"), {})

    # 3) side questions (answer, keep the state)
    if m(DISCOUNT) and not has_spec and "qty" not in p:
        return await finish(r(lang, "discount"), {**st, "expect": st.get("expect") or "qty"})
    if m(STATUS) and not has_spec and "qty" not in p:
        rows = await orders_svc.customer_orders(core, cid, 5)
        if not rows:
            return await finish(r(lang, "status_none"))
        return await finish("\n".join(
            f"{o['ref']}: {orders_svc.status_text(o['status'], lang)} — {o['quantity']} × {SHORT_FMT.get(lang, SHORT_FMT['en']).format(lvl=o['offer']['lvl'])}"
            f" — {fmt(o['total'])} {o['currency']}" + (f" ({o['reason']})" if o["reason"] else "") for o in rows))
    if m(PAY) and not has_spec and "qty" not in p:
        methods = await pay_svc.list_methods(core, active_only=True)
        names = ", ".join(f"{x['name']} ({x['currency']})" for x in methods) or "—"
        extra = r(lang, "pending_hint", ref=pending["ref"]) if pending else ""
        return await finish(r(lang, "pay", m=names) + extra)
    if m(THANKS) and not has_spec and "qty" not in p and not m(BUY):
        return await finish(r(lang, "thanks"))

    # 4) fill the order slots from this message + context
    expect = st.get("expect")
    shown = st.get("shown") or []
    num = bare_number(raw)
    picked = None
    if num is not None and not has_spec and "qty" not in p:
        if expect == "type" and 1 <= num <= len(shown):
            picked = shown[num - 1]
        elif expect == "qty" or (st.get("offer") and not st.get("qty")):
            p["qty"] = num
        elif shown and 1 <= num <= len(shown):
            picked = shown[num - 1]
        else:
            p["qty"] = num
    elif expect == "type" and shown and not has_spec:
        # "الاول" / "the first one" / "第一个"
        for i, pat in enumerate((r"الاول|اول واحد|\bfirst\b|thu nhat|第一", r"الثاني|الثانيه|\bsecond\b|thu hai|第二",
                                 r"الثالث|\bthird\b|thu ba|第三")):
            if i < len(shown) and re.search(pat, tv):
                picked = shown[i]
    # a stated number inside a sentence while choosing a type ("بدي الثاني 3 مزارع") is the quantity
    if "qty" in p:
        st["qty"] = p["qty"]
    if has_spec:
        st["spec"] = {k: p[k] for k in ("lvl", "barn", "silo", "tools") if k in p}
        st.pop("offer", None)
    if picked:
        st["offer"] = picked

    buying = m(BUY) or m(FARM) or m(PRICE) or has_spec or "qty" in p or picked or st.get("qty") or st.get("offer") or st.get("spec")
    if not buying:
        if m(GREET):
            s = await get_settings(core)
            hint = r(lang, "pending_hint", ref=pending["ref"]) if pending else ""
            return await finish(r(lang, "welcome", store=s.get("store_name") or "HD Agent") + hint)
        hint = r(lang, "pending_hint", ref=pending["ref"]) if pending else ""
        return await finish(r(lang, "unclear") + hint)

    # resolve the farm type
    offer = await farms_svc.find_offer(core, st["offer"]) if st.get("offer") else None
    if st.get("offer") and not offer:
        st.pop("offer", None)
    if not offer and st.get("spec"):
        matches = await _matching(core, st["spec"])
        if len(matches) == 1:
            offer = matches[0]
            st["offer"] = offer["offer_code"]
        elif not matches:
            near = await farms_svc.search_offers(core, limit=50)
            if not near:
                return await finish(r(lang, "no_stock"), {})
            if st["spec"].get("lvl"):
                near.sort(key=lambda o: abs(o["lvl"] - st["spec"]["lvl"]))
            near = near[:8]
            st.update(expect="type", shown=[o["offer_code"] for o in near])
            st.pop("spec", None)
            return await finish(r(lang, "no_match", list=offer_list(near, lang)))
        else:
            matches = matches[:8]
            st.update(expect="type", shown=[o["offer_code"] for o in matches])
            return await finish(r(lang, "ask_type", list=offer_list(matches, lang)))

    # what is still missing? ask one simple question at a time
    if not st.get("qty"):
        if offer:
            st.update(expect="qty")
            return await finish(r(lang, "ask_qty_for", offer=offer_text(offer, lang)))
        all_offers = await farms_svc.search_offers(core, limit=8)
        if not all_offers:
            return await finish(r(lang, "no_stock"), {})
        st.update(expect="qty")
        return await finish(r(lang, "ask_qty"))
    if not offer:
        all_offers = await farms_svc.search_offers(core, limit=8)
        if not all_offers:
            return await finish(r(lang, "no_stock"), {})
        if len(all_offers) == 1:
            offer = all_offers[0]
            st["offer"] = offer["offer_code"]
        else:
            st.update(expect="type", shown=[o["offer_code"] for o in all_offers])
            return await finish(r(lang, "ask_type", list=offer_list(all_offers, lang)))

    # both known → price from the database, recalculated on every change
    qty = int(st["qty"])
    if qty > offer["available"]:
        st.update(expect="qty")
        st.pop("qty", None)
        return await finish(r(lang, "only", n=offer["available"]))
    try:
        o = await orders_svc.prepare(core, cid, offer["offer_code"], qty)   # replaces any older unconfirmed order
    except StoreError as e:
        st.pop("qty", None)
        st.update(expect="qty")
        return await finish(e.message)
    res.order = o
    short = SHORT_FMT.get(lang, SHORT_FMT["en"]).format(lvl=offer["lvl"])
    keep = {"qty": qty, "offer": offer["offer_code"], "expect": "confirm"}
    qtxt = qty if lang != "ar" else ("مزرعة واحدة" if qty == 1 else "مزرعتين" if qty == 2 else f"{qty} مزارع" if qty <= 10 else f"{qty} مزرعة")
    return await finish(r(lang, "quote", q=qtxt, offer=short, p=fmt(o["unit_price"]), t=fmt(o["total"]), c=o["currency"]), keep)


async def safe_respond(core: Core, customer: dict) -> AgentResult:
    try:
        return await respond(core, customer)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("assistant failed")
        return AgentResult(handoff="ai_error")
