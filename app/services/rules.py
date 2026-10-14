"""Free built-in sales assistant (no external AI, no cost).

Understands Arabic (incl. Iraqi/Gulf/Levantine wording) and English requests about farms: level, barn, silo, tools,
quantity, yes/no, order status, payment and complaints. Every number it says comes from the database."""
from __future__ import annotations

import re
from decimal import Decimal

from ..core import Core, StoreError, fmt
from . import customers as cust_svc
from . import farms as farms_svc
from . import orders as orders_svc
from . import payments as pay_svc
from .ai import AgentResult

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ARABIC = re.compile(r"[؀-ۿ]")

KW = {
    "lvl": r"(?:مستوى|مستواها|المستوى|لفل|ليفل|لڤل|لول|level|lvl|lv)",
    "barn": r"(?:مخزن|المخزن|مخازن|حظيرة|الحظيرة|حضيرة|الحضيرة|بارن|barn)",
    "silo": r"(?:صومعة|الصومعة|صومعه|الصومعه|سايلو|سيلو|silo)",
    "tools": r"(?:ادوات\s*ارض|أدوات\s*أرض|ادوات|أدوات|الادوات|الأدوات|اداوت|tools|land)",
}
FARM_WORD = r"(?:مزارع|مزرعة|مزرعه|مزرعات|حسابات|حساب|farms?|accounts?)"
NUM = r"(\d+(?:[.,]\d+)?\s*(?:k|K|ك|الف|ألف|آلاف|الاف|الآف)?)"
WORD_NUMS = [
    (r"\bمزرعتين\b|\bمزرعتان\b|\bحسابين\b", 2), (r"\bثنتين\b|\bاثنين\b|\bإثنين\b|\bاثنتين\b|\bزوج\b|\btwo\b", 2),
    (r"\bثلاث(?:ة|ه)?\b|\bتلات(?:ة|ه)?\b|\bthree\b", 3), (r"\bاربع(?:ة|ه)?\b|\bأربع(?:ة|ه)?\b|\bfour\b", 4),
    (r"\bخمس(?:ة|ه)?\b|\bfive\b", 5), (r"\bست(?:ة|ه)\b|\bsix\b", 6), (r"\bسبع(?:ة|ه)?\b|\bseven\b", 7),
    (r"\bثمان(?:ية|يه)?\b|\bثمن(?:ة|ه)\b|\beight\b", 8), (r"\bتسع(?:ة|ه)?\b|\bnine\b", 9), (r"\bعشر(?:ة|ه)?\b|\bten\b", 10),
    (r"\bوحدة\b|\bوحده\b|\bواحدة\b|\bواحده\b|\bواحد\b|\bمزرعة واحدة\b|\bone\b", 1),
]
YES = re.compile(r"^(?:نعم|اي|إي|ايه|إيه|أيوه|ايوه|ايوا|اكيد|أكيد|تمام|موافق|اوكي|اوك|ماشي|يلا|زين|صح|اكد|أكد|أؤكد|اوكيه|"
                 r"yes|yeah|yep|ok|okay|sure|confirm)(?:\s|[.!،,]|$)", re.I)
NO = re.compile(r"^(?:لا|لأ|كلا|الغ|ألغ|الغي|ألغي|إلغاء|الغاء|لا اريد|ما اريد|مابي|ما ابي|no|nope|cancel)(?:\s|[.!،,]|$)", re.I)
STATUS = re.compile(r"طلبي|طلباتي|حالة|حاله|وين طلب|وصل طلب|status|my order", re.I)
PAY = re.compile(r"دفع|ادفع|أدفع|الدفع|تحويل|بايننس|باينانس|binance|pay|حول|أحول|احول", re.I)
PRICE = re.compile(r"سعر|اسعار|أسعار|بكم|بچم|شكد|كم سعر|price|cost|how much", re.I)
BUY = re.compile(r"اريد|أريد|ابي|أبي|ابغى|أبغى|بدي|اشتري|أشتري|شراء|عندكم|عندك|متوفر|موجود|مزارع|مزرعة|مزرعه|"
                 r"want|buy|need|have|farm", re.I)
COMPLAIN = re.compile(r"مشكل|شكوى|اشتكي|أشتكي|غلط|خطأ|ما يشتغل|مايشتغل|لا يعمل|ما اشتغل|ما يفتح|مايفتح|نصب|حرامي|"
                      r"ما وصل|ماوصل|لم يصل|لم تصل|ما وصلت|خربان|معطل|استرجاع|ارجاع|إرجاع|"
                      r"موظف|انسان|إنسان|الادارة|الإدارة|الدعم|problem|issue|complain|refund|scam|wrong|not working|human|support",
                      re.I)
DISCOUNT = re.compile(r"خصم|تخفيض|ارخص|أرخص|نزل السعر|نزّل|discount|cheaper", re.I)
GREET = re.compile(r"^(?:مرحبا|هلا|هلو|اهلا|أهلا|السلام|سلام|صباح|مساء|hi|hello|hey)", re.I)


def _norm(text: str) -> str:
    t = (text or "").translate(AR_DIGITS).replace("٬", "").replace("،", " ، ")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)        # 10,000 → 10000
    return re.sub(r"\s+", " ", t).strip()


def _num(raw: str) -> int | None:
    m = re.match(r"(\d+(?:[.,]\d+)?)\s*(k|K|ك|الف|ألف|آلاف|الاف|الآف)?", raw.strip())
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    if m.group(2):
        v *= 1000
    return int(v)


def parse(text: str) -> dict:
    """Extract level / barn / silo / tools / quantity from free text."""
    t = _norm(text)
    out: dict = {}
    used: list[tuple[int, int]] = []
    for key, kw in KW.items():
        m = re.search(kw + r"\s*(?:[:=]|هو|هي|يكون|تكون|بـ|ب)?\s*" + NUM, t, re.I) or re.search(NUM + r"\s*" + kw, t, re.I)
        if m:
            out[key] = _num(m.group(1))
            used.append(m.span())
    rest = t
    for a, b in sorted(used, reverse=True):
        rest = rest[:a] + " " * (b - a) + rest[b:]
    m = (re.search(r"(\d+)\s*" + FARM_WORD, rest, re.I) or re.search(FARM_WORD + r"\s*(?:عدد)?\s*(\d+)\b", rest, re.I)
         or re.search(r"(?:عدد|كمية|كميه|x|×)\s*(\d+)", rest, re.I))
    if m:
        out["qty"] = int(m.group(1))
    else:
        for pat, n in WORD_NUMS:
            if re.search(pat, rest, re.I):
                out["qty"] = n
                break
    return out


def _lang(text: str, fallback: str | None) -> str:
    return "ar" if ARABIC.search(text or "") else ("en" if re.search(r"[A-Za-z]", text or "") else (fallback or "ar"))


def _offer_line(i: int | None, o: dict, lang: str) -> str:
    head = f"{i}) " if i else ""
    if lang == "ar":
        return (f"{head}مستوى {o['lvl']} — مخزن {o['barn']}، صومعة {o['silo']}، أدوات {o['tools']}\n"
                f"   السعر {fmt(o['price'])} {o['currency']} — المتوفر {o['available']}")
    return (f"{head}Level {o['lvl']} — barn {o['barn']}, silo {o['silo']}, tools {o['tools']}\n"
            f"   {fmt(o['price'])} {o['currency']} — {o['available']} available")


async def _set_pick(core: Core, cid: int, codes: list[str], qty: int | None) -> None:
    await core.pool.execute("UPDATE customers SET awaiting=$2 WHERE id=$1", cid, f"pick:{qty or ''}:{','.join(codes)}")


async def _clear_pick(core: Core, cid: int) -> None:
    await core.pool.execute("UPDATE customers SET awaiting=NULL WHERE id=$1 AND awaiting LIKE 'pick:%'", cid)


async def _get_pick(core: Core, cid: int) -> tuple[int | None, list[str]] | None:
    a = await core.pool.fetchval("SELECT awaiting FROM customers WHERE id=$1", cid)
    if not a or not a.startswith("pick:"):
        return None
    _, q, codes = a.split(":", 2)
    return (int(q) if q else None), [c for c in codes.split(",") if c]


async def _prepare(core: Core, cid: int, offer: dict, qty: int, lang: str, res: AgentResult) -> None:
    if qty > offer["available"]:
        res.text = (f"المتوفر من هذا العرض {offer['available']} فقط. كم تريد منها؟" if lang == "ar"
                    else f"Only {offer['available']} available for this offer. How many would you like?")
        await _set_pick(core, cid, [offer["offer_code"]], None)
        return
    try:
        o = await orders_svc.prepare(core, cid, offer["offer_code"], qty)
    except StoreError as e:
        res.text = e.message
        return
    await _clear_pick(core, cid)
    res.order = o
    res.text = (f"{qty} مزرعة × {fmt(o['unit_price'])} = {fmt(o['total'])} {o['currency']}\n\nمتأكد تريد تشتري؟ اكتب «نعم» للتأكيد أو «لا» للإلغاء."
                if lang == "ar" else
                f"{qty} farm(s) × {fmt(o['unit_price'])} = {fmt(o['total'])} {o['currency']}\n\nAre you sure you want to buy? Reply “yes” to confirm or “no” to cancel.")


async def _list_offers(core: Core, lang: str, offers: list[dict], intro: str, cid: int, qty: int | None) -> str:
    offers = offers[:8]
    await _set_pick(core, cid, [o["offer_code"] for o in offers], qty)
    lines = "\n".join(_offer_line(i + 1, o, lang) for i, o in enumerate(offers))
    ask = ("اكتب رقم العرض" + (" " if qty else " وعدد المزارع") + "، مثلاً: 1" + ("" if qty else " و 3 مزارع") if lang == "ar"
           else "Reply with the offer number" + ("" if qty else " and how many, e.g. “1, 3 farms”"))
    return f"{intro}\n\n{lines}\n\n{ask}"


async def respond(core: Core, customer: dict) -> AgentResult:
    cid = customer["id"]
    last = await core.pool.fetchval("SELECT content FROM messages WHERE customer_id=$1 AND role='user' ORDER BY id DESC LIMIT 1", cid)
    text = _norm(last or "")
    lang = _lang(text, customer.get("lang"))
    res = AgentResult()
    pending = await core.pool.fetchrow(
        "SELECT * FROM orders WHERE customer_id=$1 AND status='pending_confirmation' ORDER BY id DESC LIMIT 1", cid)
    spec = parse(text)

    # complaints / problems / asking for a person → staff
    if COMPLAIN.search(text):
        res.handoff = "شكوى أو مشكلة من العميل"
        return res

    # yes / no for a prepared order
    if pending and YES.search(text) and not {"lvl", "barn", "silo", "tools"} & spec.keys():
        try:
            o = await orders_svc.confirm(core, cid, pending["id"])
        except StoreError as e:
            res.text = e.message
            return res
        res.confirmed = o
        res.text = ("تم تأكيد طلبك وحجز المزارع لك. حوّل المبلغ بالضبط حسب التفاصيل التالية، ثم أرسل صورة التحويل فقط من زر المرفقات."
                    if lang == "ar" else
                    "Order confirmed and farms reserved. Transfer the exact amount below, then send the transfer screenshot.")
        return res
    if NO.search(text):
        open_o = pending or await core.pool.fetchrow(
            "SELECT * FROM orders WHERE customer_id=$1 AND status='awaiting_payment' ORDER BY id DESC LIMIT 1", cid)
        await _clear_pick(core, cid)
        if open_o:
            await orders_svc.cancel_by_customer(core, cid, open_o["id"])
            res.text = (f"تم إلغاء الطلب {open_o['ref']}. إذا تحتاج شيئاً آخر اكتب لي." if lang == "ar"
                        else f"Order {open_o['ref']} cancelled. Tell me if you need anything else.")
        else:
            res.text = "تمام. إذا تحتاج مزارع اكتب المستوى والعدد." if lang == "ar" else "Okay. Tell me the level and quantity if you need farms."
        return res

    # choosing from a list I showed earlier: "1", "2 و 3 مزارع", "الاول"
    pick = await _get_pick(core, cid)
    if pick and not {"lvl", "barn", "silo", "tools"} & spec.keys():
        pq, codes = pick
        m = re.match(r"^\s*(?:رقم|العرض|عرض|#|no\.?)?\s*(\d{1,2})\b", text, re.I)
        idx = None
        if m and len(codes) > 1 and 1 <= int(m.group(1)) <= len(codes) and not re.match(r"^\s*\d+\s*" + FARM_WORD, text, re.I):
            idx = int(m.group(1)) - 1
            spec.pop("qty", None)
            rest = text[m.end():]
            q2 = parse(rest).get("qty") or (int(x.group(1)) if (x := re.search(r"(\d+)", rest)) else None)
            if q2:
                spec["qty"] = q2
        elif len(codes) == 1:
            idx = 0
            if "qty" not in spec and (x := re.fullmatch(r"\s*(\d{1,3})\s*", text)):
                spec["qty"] = int(x.group(1))
        if idx is not None:
            offer = await farms_svc.find_offer(core, codes[idx])
            if not offer:
                await _clear_pick(core, cid)
                res.text = "هذا العرض لم يعد متوفراً. اكتب ما تحتاجه من جديد." if lang == "ar" else "That offer is no longer available."
                return res
            qty = spec.get("qty") or pq
            if not qty:
                await _set_pick(core, cid, [offer["offer_code"]], None)
                res.text = (f"اخترت:\n{_offer_line(None, offer, lang)}\n\nكم مزرعة تريد؟" if lang == "ar"
                            else f"You chose:\n{_offer_line(None, offer, lang)}\n\nHow many farms?")
                return res
            await _prepare(core, cid, offer, qty, lang, res)
            return res

    if DISCOUNT.search(text) and not spec:
        res.text = ("الأسعار ثابتة ولا يمكن تغييرها، لكن أقدر أساعدك تختار المزرعة الأنسب لميزانيتك. اكتب «الأسعار» لعرض المتوفر."
                    if lang == "ar" else "Prices are fixed, but I can help you pick the best farm for your budget. Type “prices”.")
        return res

    # order status
    if STATUS.search(text) and not spec:
        orders = await orders_svc.customer_orders(core, cid, 5)
        if not orders:
            res.text = "لا توجد طلبات لك بعد." if lang == "ar" else "You have no orders yet."
        else:
            res.text = "\n".join(f"{o['ref']}: {orders_svc.status_text(o['status'], lang)} — {o['quantity']} × مستوى {o['offer']['lvl']} — "
                                 f"{fmt(o['total'])} {o['currency']}" + (f" ({o['reason']})" if o["reason"] else "")
                                 for o in orders) + ("\n\nالتفاصيل في «طلباتي» أعلى الشاشة." if lang == "ar" else "")
        return res

    # payment questions
    if PAY.search(text) and not spec:
        methods = await pay_svc.list_methods(core, active_only=True)
        names = "، ".join(f"{m['name']} ({m['currency']})" for m in methods) or "—"
        res.text = (f"طرق الدفع المتاحة: {names}.\nبعد تأكيد الطلب تظهر لك تفاصيل الدفع والمبلغ. حوّل المبلغ بالضبط ثم أرسل صورة التحويل فقط "
                    "(بدون رقم عملية). بعد تأكيد الإدارة تصلك بيانات المزارع هنا." if lang == "ar" else
                    f"Payment methods: {names}. After you confirm an order you get the payment details; transfer the exact amount and "
                    "send the screenshot only. Your farms appear here once staff verify the payment.")
        return res

    # a request with specs and/or quantity
    if spec.keys() & {"lvl", "barn", "silo", "tools"}:
        offers = await farms_svc.search_offers(
            core, min_level=spec.get("lvl"), max_level=spec.get("lvl"), min_barn=spec.get("barn"),
            min_silo=spec.get("silo"), min_tools=spec.get("tools"), limit=20)
        qty = spec.get("qty")
        if not offers:
            near = await farms_svc.search_offers(core, limit=50)
            if spec.get("lvl"):
                near.sort(key=lambda o: abs(o["lvl"] - spec["lvl"]))
            if not near:
                res.text = "للأسف لا توجد مزارع متوفرة حالياً." if lang == "ar" else "Sorry, no farms are in stock right now."
                return res
            res.text = await _list_offers(core, lang, near, "لا يوجد عرض مطابق تماماً لطلبك. هذه أقرب المزارع المتوفرة:" if lang == "ar"
                                          else "Nothing matches exactly. Closest available:", cid, qty)
            return res
        if len(offers) == 1:
            if qty:
                await _prepare(core, cid, offers[0], qty, lang, res)
            else:
                await _set_pick(core, cid, [offers[0]["offer_code"]], None)
                res.text = (f"متوفر:\n{_offer_line(None, offers[0], lang)}\n\nكم مزرعة تريد؟" if lang == "ar"
                            else f"Available:\n{_offer_line(None, offers[0], lang)}\n\nHow many farms?")
            return res
        res.text = await _list_offers(core, lang, offers, "هذه العروض المطابقة:" if lang == "ar" else "Matching offers:", cid, qty)
        return res

    # just a quantity while a single offer is in focus is handled above; vague buy / price / greeting → show stock
    if BUY.search(text) or PRICE.search(text) or GREET.search(text) or spec.get("qty"):
        offers = await farms_svc.search_offers(core, limit=20)
        if not offers:
            res.text = ("أهلاً بك. للأسف لا توجد مزارع متوفرة حالياً، تابعنا لاحقاً." if lang == "ar"
                        else "Welcome! Sorry, no farms are in stock right now.")
            return res
        intro = "أهلاً بك. هذه المزارع المتوفرة الآن:" if lang == "ar" else "Welcome! Farms available now:"
        res.text = await _list_offers(core, lang, offers, intro, cid, spec.get("qty"))
        return res

    res.text = ("اكتب ما تحتاجه، مثلاً: «اريد 5 مزارع مستوى 50 مخزن 3000 أدوات 3000»، أو اكتب «الأسعار» لعرض المتوفر، "
                "أو «طلباتي» لمعرفة حالة طلبك." if lang == "ar" else
                "Tell me what you need, e.g. “5 farms level 50 barn 3000”, or type “prices” to see stock, or “my orders”.")
    return res


async def safe_respond(core: Core, customer: dict) -> AgentResult:
    try:
        return await respond(core, customer)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("rules assistant failed")
        return AgentResult(handoff="ai_error")
