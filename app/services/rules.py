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
GREET = _rx(r"^(?:و)?(?:مرحب|مرحبا|هلا|هلو|هاي|اهلين|اهلا|السلام|سلام|صباح|مسا|شلونك|شلونكم|كيفك|كيفكم|ازيك|شخبارك|يا هلا|كيف الحال|كيف حالك|شلون الحال|شو اخبارك)",
            r"\b(?:hi|hello|hey|salam|good (?:morning|evening))\b", r"\b(?:xin chao|chao|alo)\b", r"你好|您好|哈喽|嗨")
BUY = _rx(r"اريد|ابي|ابغي|ابغا|بدي|بدنا|بغيت|بغينا|عايز|عاوز|محتاج|احتاج|نحتاج|حاب|ودي|اشتري|نشتري|شراء|"
          r"اطلب|نطلب|عندك|عندكم|عدكم|عدك|متوفر|موجود|في عندكم|هاتلي|هاتو|جيبلي|جيبو|انطيني|نطيني|اعطيني|عطني|اشوف",
          r"\b(?:want|wanna|need|buy|purchase|order|get|have|looking for|sell|show)\b",
          r"\b(?:mua|muon|can|co .*khong|ban|dat)\b", r"买|要|想要|需要|有没有|有吗|购买|下单|来")
FARM = _rx(r"مزار|مزرع|مزرعه|حساب|حسابات|فارم|فارمات|هاي دي|هايدي", r"\bfarms?\b|\baccounts?\b|\bhay ?day\b",
           r"\bnong trai\b|\btrang trai\b|\bfarm\b", r"农场|账号|帐号")
YES = _rx(r"^(?:و)?(?:نعم|اي|ايه|ايوه|ايوا|اكيد|تمام|موافق|اوكي|اوك|ماشي|يلا|زين|صح|اكد|اوكيه|اكدت|بلي|طيب|خلاص|"
          r"توكل|اي نعم|اي والله|يس|يب|ياريت|يا ريت|اوكي|مضبوط|حلو|اوكي اكد|نعم اكد|اكيد اكد|اشتري|اوافق)\b",
          r"^(?:yes|yeah|yep|yup|ok|okay|sure|confirm|go ahead|do it|deal|i agree|agree)\b",
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
TOOL_TYPE_RX = [
    (r"(?:ادوات|الادوات|عده|عدد)\s*(?:ال)?(?:ارض|اراضي|الارض)|\bland\s*tools?\b|\btools?\s*(?:for\s*)?land\b|cong cu dat|土地工具|扩地工具", "land"),
    (r"(?:ادوات|الادوات|عده|عدد)\s*(?:ال)?(?:حظيره|حضيره|مخزن|مخازن|بارن)|\bbarn\s*tools?\b|\btools?\s*(?:for\s*)?barn\b|cong cu kho(?! thoc)|仓库工具|谷仓工具", "barn"),
    (r"(?:ادوات|الادوات|عده|عدد)\s*(?:ال)?(?:صومعه|سايلو|سيلو)|\bsilo\s*tools?\b|\btools?\s*(?:for\s*)?silo\b|cong cu (?:silo|kho thoc)|粮仓工具|筒仓工具", "silo"),
]
TOOL_LABEL = {
    "ar": {"land": "أدوات أرض", "barn": "أدوات حظيرة", "silo": "أدوات صومعة"},
    "en": {"land": "land tools", "barn": "barn tools", "silo": "silo tools"},
    "vi": {"land": "công cụ đất", "barn": "công cụ kho", "silo": "công cụ silo"},
    "zh": {"land": "土地工具", "barn": "仓库工具", "silo": "粮仓工具"},
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
    out: dict = {}
    for pat, kind in TOOL_TYPE_RX:                     # "ادوات حظيره 3000" → tool_type=barn, tools=3000
        mm = re.search(pat, strip_vi(t), re.I)
        if mm:
            out["tool_type"] = kind
            tv0 = strip_vi(t)
            t = (tv0[:mm.start()] + " ادوات " + tv0[mm.end():]) if tv0 != t else (t[:mm.start()] + " ادوات " + t[mm.end():])
            break
    tv = strip_vi(t)
    used: list[tuple[int, int]] = []
    def free(span: tuple[int, int]) -> bool:
        return all(span[1] <= a or span[0] >= b for a, b in used)

    for key, kw in SPEC_KW.items():
        for src in (t, tv):
            found = None
            for rx in (kw + r"\s*(?:[:=]|هو|هي|يكون|بس|فقط|تقريبا)?\s*" + NUMV, NUMV + r"\s*" + kw):
                for mm in re.finditer(rx, src, re.I):
                    # barn / silo / tools are capacities (hundreds or thousands); a small number is a quantity
                    if key != "lvl" and (_num(mm.group(1)) or 0) < 50:
                        continue
                    if free(mm.span()):
                        found = mm
                        break
                if found:
                    break
            if found:
                out[key] = _num(found.group(1))
                used.append(found.span())
                break
    if "tool_type" not in out:                          # a bare type word: "حظيره" / "الارض" / "silo"
        mm = re.search(r"(?:^|\s)(?:ب|ال|بال)?(ارض|حظيره|حضيره|صومعه|سايلو|land|barn|silo)(?=\s|$|\?)(?:\s*(\d+))?", t, re.I)
        if mm and (not mm.group(2) or int(mm.group(2)) < 50):
            key = {"ارض": "land", "land": "land", "صومعه": "silo", "سايلو": "silo", "silo": "silo"}.get(mm.group(1).lower(), "barn")
            if key == "land" or key not in out:
                out["tool_type"] = key
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
    if "qty" not in out and (used or "tool_type" in out):  # "بدي 1 مستوى 60": the number left over is the quantity
        left = re.findall(r"(?<![\d.])(\d{1,3})(?![\d.])", rest)
        if len(left) == 1 and 0 < int(left[0]) <= 500:
            out["qty"] = int(left[0])
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
    "welcome": {"ar": "أهلًا وسهلًا بك في {store} 🤖🌾\nأنا هنا لمساعدتك في شراء مزارع Hay Day بسهولة.\nماذا تحتاج؟ يمكنك كتابة طلبك مباشرة وسأساعدك خطوة بخطوة.",
                "en": "Welcome to {store} 🤖🌾\nI'm here to help you buy Hay Day farms easily.\nWhat do you need? Just write your request and I'll guide you step by step.",
                "vi": "Chào mừng bạn đến với {store} 🤖🌾\nTôi ở đây để giúp bạn mua nông trại Hay Day dễ dàng.\nBạn cần gì? Cứ viết yêu cầu, tôi sẽ hướng dẫn từng bước.",
                "zh": "欢迎来到 {store} 🤖🌾\n我可以帮您轻松购买 Hay Day 农场。\n您需要什么？直接写下需求，我会一步步帮您。"},
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
    "ask_specs": {"ar": "أكيد! ما مواصفات المزارع التي تحتاجها؟ اكتب المستوى، وسعة المخزن، ونوع الأدوات (أرض أو حظيرة أو صومعة).",
                  "en": "Sure! Which farms do you need? Tell me the level, barn size and tool type (land, barn or silo).",
                  "vi": "Được! Bạn cần nông trại thế nào? Hãy cho biết cấp, sức chứa kho và loại công cụ (đất, kho hoặc silo).",
                  "zh": "好的！您需要什么样的农场？请告诉我等级、仓库容量和工具类型（土地、仓库或粮仓）。"},
    "ask_field_lvl": {"ar": "ما المستوى الذي تحتاجه؟ المتوفر: {vals}", "en": "Which level do you need? Available: {vals}",
                      "vi": "Bạn cần cấp nào? Hiện có: {vals}", "zh": "您需要哪个等级？目前有：{vals}"},
    "ask_field_barn": {"ar": "ما سعة المخزن التي تريدها؟ المتوفر: {vals}", "en": "Which barn size? Available: {vals}",
                       "vi": "Sức chứa kho bao nhiêu? Hiện có: {vals}", "zh": "需要多大的仓库？目前有：{vals}"},
    "ask_field_tool_type": {"ar": "ما نوع الأدوات التي تريدها؟ المتوفر: {vals}", "en": "Which tool type? Available: {vals}",
                            "vi": "Bạn muốn loại công cụ nào? Hiện có: {vals}", "zh": "需要哪种工具？目前有：{vals}"},
    "ask_field_silo": {"ar": "ما سعة الصومعة التي تريدها؟ المتوفر: {vals}", "en": "Which silo size? Available: {vals}",
                       "vi": "Sức chứa silo bao nhiêu? Hiện có: {vals}", "zh": "需要多大的粮仓？目前有：{vals}"},
    "ask_field_tools": {"ar": "كم عدد الأدوات الذي تريده؟ المتوفر: {vals}", "en": "How many tools? Available: {vals}",
                        "vi": "Số lượng công cụ? Hiện có: {vals}", "zh": "需要多少工具？目前有：{vals}"},
    "ask_qty_type": {"ar": "ممتاز 👍\n{offer}\n\nكم مزرعة تحتاج من هذا النوع؟", "en": "Great 👍\n{offer}\n\nHow many farms of this type do you need?",
                     "vi": "Tuyệt 👍\n{offer}\n\nBạn cần bao nhiêu nông trại loại này?", "zh": "好的 👍\n{offer}\n\n这种农场您需要几个？"},
    "shortage": {"ar": "عذرًا، العدد المطلوب غير متوفر حاليًا. طلبت {q} مزارع، والمتوفر في المخزون {n} مزارع فقط.\nكم مزرعة تريد شراءها من الكمية المتوفرة؟ يمكنك كتابة العدد الذي يناسبك أو إلغاء الطلب.",
                 "en": "Sorry, that quantity isn't available right now. You asked for {q} farms and only {n} are in stock.\nHow many would you like from the available quantity? Write the number that suits you, or cancel.",
                 "vi": "Xin lỗi, số lượng này hiện không đủ. Bạn yêu cầu {q} nông trại, kho chỉ còn {n}.\nBạn muốn mua bao nhiêu trong số còn lại? Hãy viết số lượng hoặc hủy.",
                 "zh": "抱歉，库存不足。您要 {q} 个，目前只有 {n} 个。\n您想从现有库存中买几个？请写数量，或取消订单。"},
    "shortage_multi": {"ar": "عذرًا، بعض الكميات غير متوفرة حاليًا:\n{rows}\n\nاكتب العدد الجديد للنوع، مثلاً «اجعل عدد مزارع الأرض 4»، أو اكتب «إلغاء».",
                       "en": "Sorry, some quantities aren't available:\n{rows}\n\nWrite the new number for that type, e.g. “make land 4”, or “cancel”.",
                       "vi": "Xin lỗi, một số loại không đủ số lượng:\n{rows}\n\nHãy viết số mới cho loại đó, ví dụ “đất 4”, hoặc “hủy”.",
                       "zh": "抱歉，部分数量不足：\n{rows}\n\n请写该类型的新数量，例如“土地 4个”，或“取消”。"},
    "shortage_row": {"ar": "• {what}: طلبت {q} والمتوفر {n}", "en": "• {what}: you asked {q}, available {n}",
                     "vi": "• {what}: yêu cầu {q}, còn {n}", "zh": "• {what}：您要 {q}，现有 {n}"},
    "type_gone": {"ar": "عذرًا، هذا النوع غير متوفر حاليًا ({what}). اكتب مواصفات نوع آخر (المستوى، المخزن، نوع الأدوات) وسأتحقق لك.",
                  "en": "Sorry, this type is not available right now ({what}). Write the specs of another type (level, barn, tool type) and I'll check.",
                  "vi": "Xin lỗi, loại này hiện hết ({what}). Hãy viết thông số loại khác (cấp, kho, loại công cụ), tôi sẽ kiểm tra.",
                  "zh": "抱歉，这种目前没有（{what}）。请写其他类型的规格（等级、仓库、工具类型），我帮您查。"},
    "ready": {"ar": "تمام، جهزت لك ملخص الطلب 👇\nهل أنت متأكد من الطلب وتريد الانتقال إلى الدفع؟ يرجى كتابة «نعم» للتأكيد أو «لا» للإلغاء، ويمكنك كتابة «تعديل» إذا أردت تغيير المواصفات أو الكمية.",
              "en": "Here's your order summary 👇\nAre you sure and want to go to payment? Reply “yes” to confirm or “no” to cancel; write “edit” to change the specs or quantity.",
              "vi": "Đây là tóm tắt đơn hàng 👇\nBạn chắc chắn và muốn thanh toán? Trả lời “có” để xác nhận, “không” để hủy, hoặc “sửa” để thay đổi.",
              "zh": "这是您的订单摘要 👇\n确定要下单并付款吗？回复“是”确认，“不”取消，或“修改”更改规格或数量。"},
    "multi_ready": {"ar": "تمام، جهزت لك الطلب 👇 راجع الملخص واختر «نعم، ادفع» للمتابعة أو «تعديل الطلب».",
                    "en": "Done — here is your order 👇 Review it and choose “Yes, pay” or “Edit order”.",
                    "vi": "Xong — đây là đơn của bạn 👇 Kiểm tra rồi chọn “Có, thanh toán” hoặc “Sửa đơn”.",
                    "zh": "好了，这是您的订单 👇 请确认后选择“是，去付款”或“修改订单”。"},
    "multi_ambiguous": {"ar": "في طلبك نوع له أكثر من خيار ({what}). اكتب الطلب مرة ثانية مع تحديد المخزن ونوع الأدوات لكل نوع.",
                        "en": "One type in your order has several options ({what}). Please resend the order with the barn size and tool type for each type.",
                        "vi": "Một loại trong đơn có nhiều lựa chọn ({what}). Hãy gửi lại đơn kèm kho và loại công cụ cho từng loại.",
                        "zh": "订单中有一种有多个选项（{what}）。请重新发送订单，并注明每种的仓库和工具类型。"},
    "edit": {"ar": "تمام، شو تحب تعدّل؟ تقدر تغيّر العدد أو النوع، مثلاً: «خلي الحظيرة 3» أو «احذف الصومعة»، أو اكتب الطلب من جديد.",
             "en": "Sure, what would you like to change? E.g. “make barn 3”, “remove silo”, or write the order again.",
             "vi": "Bạn muốn sửa gì? Ví dụ: “kho 3”, “bỏ silo”, hoặc viết lại đơn.", "zh": "好的，要修改什么？例如“仓库改成3个”“去掉粮仓”，或重新写订单。"},
    "which_line": {"ar": "طلبك فيه أكثر من نوع. أي نوع تقصد؟ اكتب مثلاً «خلي الأرض 3».",
                   "en": "Your order has several types. Which one? e.g. “make land 3”.",
                   "vi": "Đơn có nhiều loại. Bạn muốn sửa loại nào? Ví dụ: “đất 3”.", "zh": "订单里有多种类型，您指哪一种？例如“土地改成3个”。"},
    "pending_hint": {"ar": "\n\nطلبك {ref} بانتظار تأكيدك: اكتب «نعم» للتأكيد أو «لا» للإلغاء.",
                     "en": "\n\nYour order {ref} is waiting: reply “yes” to confirm or “no” to cancel.",
                     "vi": "\n\nĐơn {ref} đang chờ: trả lời “có” để xác nhận hoặc “không” để hủy.", "zh": "\n\n订单 {ref} 待确认：回复“是”确认，或“不”取消。"},
}
OFFER_FMT = {
    "ar": "مستوى {lvl} — مخزن {barn}، صومعة {silo}، {tt} {tools} — {price} {cur}",
    "en": "Level {lvl} — barn {barn}, silo {silo}, {tt} {tools} — {price} {cur}",
    "vi": "Cấp {lvl} — kho {barn}, silo {silo}, {tt} {tools} — {price} {cur}",
    "zh": "等级 {lvl} — 仓库 {barn}，粮仓 {silo}，{tt} {tools} — {price} {cur}",
}
SHORT_FMT = {"ar": "مستوى {lvl}، {tt}", "en": "level {lvl}, {tt}", "vi": "cấp {lvl}, {tt}", "zh": "等级 {lvl}，{tt}"}


def tool_label(lang: str, kind: str | None) -> str:
    return TOOL_LABEL.get(lang, TOOL_LABEL["en"]).get(kind or "land", kind or "")


def r(lang: str, key: str, **kw) -> str:
    return R[key].get(lang, R[key]["en"]).format(**kw)


def offer_text(o: dict, lang: str) -> str:
    return OFFER_FMT.get(lang, OFFER_FMT["en"]).format(lvl=o["lvl"], barn=o["barn"], silo=o["silo"], tools=o["tools"],
                                                       tt=tool_label(lang, o.get("tool_type")),
                                                       price=fmt(o["price"]), cur=o["currency"], n=o["available"])


def offer_list(offers: list[dict], lang: str) -> str:
    return "\n".join(f"{i + 1}) {offer_text(o, lang)}" for i, o in enumerate(offers))


VAL_FMT = {"lvl": "{v}", "barn": "{v}", "silo": "{v}", "tools": "{v}"}


def field_values(field: str, offers: list[dict], lang: str) -> list:
    vals = sorted({o.get(field) or ("land" if field == "tool_type" else 0) for o in offers}, key=lambda v: (str(type(v)), v))
    return vals


def field_vals_text(field: str, vals: list, lang: str) -> str:
    if field == "tool_type":
        return " / ".join(tool_label(lang, v) for v in vals)
    return "، ".join(str(v) for v in vals) if lang == "ar" else ", ".join(str(v) for v in vals)


# ------------------------------------------------------------------ conversation state
async def load_state(core: Core, cid: int) -> dict:
    a = await core.pool.fetchval("SELECT dialog FROM customers WHERE id=$1", cid)
    if a:
        try:
            return json.loads(a)
        except ValueError:
            pass
    return {}


async def save_state(core: Core, cid: int, st: dict) -> None:
    val = json.dumps(st, ensure_ascii=False) if st else None
    await core.pool.execute("UPDATE customers SET dialog=$2 WHERE id=$1", cid, val)


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
                                         min_silo=spec.get("silo"), min_tools=spec.get("tools"),
                                         tool_type=spec.get("tool_type"), limit=20)


SEP_RX = re.compile(r"\n|\s*[+،,;，、；]\s*|\s+(?:و|and|va|và|also|plus)\s+|\s+و(?=\d)|(?<=\D)\s*和\s*|还有|以及", re.I)
EDIT_RX = _rx(r"^(?:تعديل|عدل|اعدل|غير|بدل|تغيير)(?:\s|$)|تعديل الطلب", r"^(?:edit|change|modify)\b", r"^(?:sua|thay doi)\b", r"^(?:修改|更改)")
REMOVE_RX = _rx(r"احذف|شيل|الغي|بدون|ما بدي|مابدي|ما اريد", r"\bremove\b|\bwithout\b|\bdrop\b", r"\bbo\b|\bxoa\b", r"去掉|不要|删除")


def split_lines(raw: str) -> list[dict]:
    """'2 مستوى 50 ادوات ارض و 2 ادوات حظيره' → [{qty 2, lvl 50, tool land}, {qty 2, tool barn, lvl 50}]"""
    segs = [x for part in re.split(r"[\r\n]+", raw or "") for x in SEP_RX.split(norm(part)) if x and x.strip()]
    parsed = [parse(x) for x in segs]
    parsed = [x for x in parsed if x]
    with_qty = [x for x in parsed if "qty" in x]
    if len(with_qty) < 2:
        return []
    shared = {}
    for x in parsed:                     # level / barn / silo / tools said once apply to every type
        for k in ("lvl", "barn", "silo", "tools"):
            if k in x and k not in shared:
                shared[k] = x[k]
    lines, cur = [], None
    for x in parsed:
        if "qty" in x:
            cur = {**shared, **x}
            lines.append(cur)
        elif cur is not None:            # extra details for the previous type ("…، ادوات حظيره")
            cur.update(x)
    return lines


def _line_match(offer: dict, want: dict) -> bool:
    return all(offer.get(k) == want[k] for k in ("lvl", "tool_type") if k in want)


async def _resolve_lines(core: Core, lines: list[dict], lang: str) -> tuple[list[tuple[str, int]] | None, str | None]:
    out = []
    for ln in lines:
        spec = {k: ln[k] for k in ("lvl", "barn", "silo", "tools", "tool_type") if k in ln}
        matches = await _matching(core, spec) if spec else await farms_svc.search_offers(core, limit=20)
        desc = " ".join(filter(None, [SHORT_FMT.get(lang, SHORT_FMT["en"]).split("،")[0].split(",")[0].format(lvl=ln.get("lvl", "?"), tt=""),
                                       tool_label(lang, ln.get("tool_type")) if ln.get("tool_type") else ""]))
        if not matches:
            near = await farms_svc.search_offers(core, limit=8)
            return None, r(lang, "type_gone", what=desc, list=offer_list(near, lang)) if near else r(lang, "no_stock")
        if len(matches) > 1:
            return None, r(lang, "multi_ambiguous", what=desc, list=offer_list(matches[:8], lang))
        out.append((matches[0]["offer_code"], int(ln["qty"])))
    return out, None


async def _shortage_rows(core: Core, wanted: list[tuple[str, int]], lang: str) -> list[str]:
    rows = []
    ords = {"ar": ["النوع الأول", "النوع الثاني", "النوع الثالث", "النوع الرابع", "النوع الخامس"]}.get(lang, [])
    for i, (code, q) in enumerate(wanted):
        o = await farms_svc.find_offer(core, code)
        n = o["available"] if o else 0
        if q > n:
            what = (ords[i] + " — " if i < len(ords) else "") + (offer_text(o, lang).split(" — ")[0] + " " + tool_label(lang, o.get("tool_type")) if o else code)
            rows.append(r(lang, "shortage_row", what=what, q=q, n=n))
    return rows


async def _prepare_multi(core: Core, cid: int, wanted: list[tuple[str, int]], lang: str, res: AgentResult) -> str:
    rows = await _shortage_rows(core, wanted, lang)
    if rows:
        raise ShortageError(r(lang, "shortage_multi", rows="\n".join(rows)))
    o = await orders_svc.prepare_lines(core, cid, wanted)
    res.order = o
    return r(lang, "ready")


class ShortageError(Exception):
    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


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
    has_spec = bool({"lvl", "barn", "silo", "tools", "tool_type"} & p.keys())
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
            f"{o['ref']}: {orders_svc.status_text(o['status'], lang)} — {o['quantity']} × {SHORT_FMT.get(lang, SHORT_FMT['en']).format(lvl=o['offer']['lvl'], tt=tool_label(lang, o['offer'].get('tool_type')))}"
            f" — {fmt(o['total'])} {o['currency']}" + (f" ({o['reason']})" if o["reason"] else "") for o in rows))
    if m(PAY) and not has_spec and "qty" not in p:
        methods = await pay_svc.list_methods(core, active_only=True)
        names = ", ".join(f"{x['name']} ({x['currency']})" for x in methods) or "—"
        extra = r(lang, "pending_hint", ref=pending["ref"]) if pending else ""
        return await finish(r(lang, "pay", m=names) + extra)
    if m(THANKS) and not has_spec and "qty" not in p and not m(BUY):
        return await finish(r(lang, "thanks"))

    # 3b) edit button / "تعديل"
    if m(EDIT_RX) and short_msg and not has_spec and "qty" not in p:
        return await finish(r(lang, "edit"), {**st, "expect": "edit"})

    # 3c) several types in one message → one order with several lines
    multi = split_lines(raw)
    if multi:
        wanted, problem = await _resolve_lines(core, multi, lang)
        if problem:
            return await finish(problem, {})
        try:
            text = await _prepare_multi(core, cid, wanted, lang, res)
        except ShortageError as e:
            return await finish(e.text, {"lines": [[c, q] for c, q in wanted], "expect": "edit"})
        except StoreError as e:
            return await finish(e.message, {})
        return await finish(text, {"lines": [[c, q] for c, q in wanted], "expect": "confirm"})

    # 3d) changing an order that has several types ("خلي الحظيره 3", "احذف الصومعه", "زيد الارض 1")
    if st.get("lines") and len(st["lines"]) > 1 and (p.keys() & {"qty", "tool_type", "lvl"}):
        offers = {c: await farms_svc.find_offer(core, c) for c, _ in st["lines"]}
        target = [c for c, _ in st["lines"] if offers[c] and _line_match(offers[c], p)] if (p.keys() & {"tool_type", "lvl"}) else []
        if len(target) != 1:
            return await finish(r(lang, "which_line"))
        lines = [[c, q] for c, q in st["lines"]]
        if m(REMOVE_RX):
            lines = [[c, q] for c, q in lines if c != target[0]]
        elif "qty" in p:
            lines = [[c, (p["qty"] if c == target[0] else q)] for c, q in lines]
        else:
            return await finish(r(lang, "which_line"))
        lines = [[c, q] for c, q in lines if q > 0]
        if not lines:
            return await finish(r(lang, "ok_no"), {})
        try:
            if len(lines) == 1:
                st.clear()
                st.update({"qty": lines[0][1], "offer": lines[0][0]})
                p, has_spec = {}, False    # continue below with the one remaining type
            else:
                text = await _prepare_multi(core, cid, [(c, q) for c, q in lines], lang, res)
                return await finish(text, {"lines": lines, "expect": "confirm"})
        except ShortageError as e:
            return await finish(e.text, {"lines": lines, "expect": "edit"})
        except StoreError as e:
            return await finish(e.message)

    # 4) fill the order slots from this message + context
    expect = st.get("expect")
    shown = st.get("shown") or []
    num = bare_number(raw)
    picked = None
    if expect and expect.startswith("field:") and num is not None and not has_spec and "qty" not in p:
        field = expect.split(":", 1)[1]
        if field in ("lvl", "barn", "silo", "tools"):
            p[field], has_spec, num = num, True, None      # "50" answers "which level?"
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
        prev = st.get("spec") or {}
        new = {k: p[k] for k in ("lvl", "barn", "silo", "tools", "tool_type") if k in p}
        # "بدي ادوات حظيره" after choosing a level refines the request instead of replacing it
        refine = (expect or "").startswith("field:") or expect == "qty" or (set(new) <= {"tool_type", "tools"} and prev)
        st["spec"] = {**prev, **new} if (refine and prev) else new
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

    # resolve the farm type: ask only for the missing details, one question at a time
    offer = await farms_svc.find_offer(core, st["offer"]) if st.get("offer") else None
    if st.get("offer") and not offer:
        st.pop("offer", None)
    if not offer:
        spec = st.get("spec") or {}
        matches = await _matching(core, spec) if spec else await farms_svc.search_offers(core, limit=50)
        if not matches:
            near = await farms_svc.search_offers(core, limit=50)
            if not near:
                return await finish(r(lang, "no_stock"), {})
            if spec.get("lvl"):
                near.sort(key=lambda o: abs(o["lvl"] - spec["lvl"]))
            near = near[:8]
            for k in ("spec", "shown", "expect"):
                st.pop(k, None)
            return await finish(r(lang, "type_gone", what=spec_text(spec, lang), list=offer_list(near, lang)))
        if len(matches) == 1:
            offer = matches[0]
            st["offer"] = offer["offer_code"]
        elif not spec:
            st.pop("shown", None)
            st.update(expect="specs")
            return await finish(r(lang, "ask_specs"))
        else:
            field = next((f for f in ("lvl", "barn", "tool_type", "silo", "tools")
                          if f not in spec and len({o.get(f) for o in matches}) > 1), None)
            shown_list = matches[:8]
            st.update(shown=[o["offer_code"] for o in shown_list])
            if field:
                st.update(expect=f"field:{field}")
                vals = field_values(field, matches, lang)
                return await finish(r(lang, f"ask_field_{field}", vals=field_vals_text(field, vals, lang)))
            st.update(expect="type")
            return await finish(r(lang, "ask_type", list=offer_list(shown_list, lang)))

    # quantity
    if not st.get("qty"):
        st.update(expect="qty")
        return await finish(r(lang, "ask_qty_type", offer=offer_text(offer, lang)))

    # real stock check — never change the customer's number without asking
    qty = int(st["qty"])
    if offer["available"] <= 0:
        st.clear()
        near = await farms_svc.search_offers(core, limit=8)
        return await finish(r(lang, "type_gone", what=offer_text(offer, lang), list=offer_list(near, lang)) if near else r(lang, "no_stock"), {})
    if qty > offer["available"]:
        st.pop("qty", None)
        st.update(expect="qty")
        return await finish(r(lang, "shortage", q=qty, n=offer["available"]))
    try:
        o = await orders_svc.prepare(core, cid, offer["offer_code"], qty)   # replaces any older unconfirmed order
    except StoreError as e:
        st.pop("qty", None)
        st.update(expect="qty")
        return await finish(e.message)
    res.order = o
    return await finish(r(lang, "ready"), {"qty": qty, "offer": offer["offer_code"], "expect": "confirm",
                                           **({"spec": st["spec"]} if st.get("spec") else {})})


def spec_text(spec: dict, lang: str) -> str:
    bits = []
    if spec.get("lvl"):
        bits.append(SHORT_FMT.get(lang, SHORT_FMT["en"]).split("{lvl}")[0] + str(spec["lvl"]))
    if spec.get("barn"):
        bits.append({"ar": "مخزن", "en": "barn", "vi": "kho", "zh": "仓库"}.get(lang, "barn") + f" {spec['barn']}")
    if spec.get("tool_type"):
        bits.append(tool_label(lang, spec["tool_type"]))
    return "، ".join(bits) if lang == "ar" else ", ".join(bits)


async def safe_respond(core: Core, customer: dict) -> AgentResult:
    try:
        return await respond(core, customer)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("assistant failed")
        return AgentResult(handoff="ai_error")
