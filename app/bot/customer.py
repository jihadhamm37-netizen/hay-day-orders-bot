"""Customer side: buy farms, wallet, top-up via Binance Pay, orders, support."""
from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..core import Core, StoreError, fmt
from ..services import catalog, deposits, orders, system, wallet
from .ui import (BTN_BUY, BTN_ORDERS, BTN_SUPPORT, BTN_TOPUP, BTN_WALLET, btn, copy_btn, credentials_kb,
                 credentials_text, deposit_line, dt, e, kb, main_menu, order_line, tx_line, type_card, url_btn)
from ..services.orders import STATUS_LABELS as ORD_LABELS

router = Router(name="customer")

QUICK_AMOUNTS = ("5", "10", "20", "50", "100")


class TopUp(StatesGroup):
    amount = State()
    photo = State()
    txid = State()


class Browse(StatesGroup):
    filter = State()


# ------------------------------------------------------------------ start
@router.message(CommandStart())
async def start(message: Message, state: FSMContext, core: Core, role: str | None):
    await state.clear()
    text = await system.setting(core, "welcome_text", "أهلاً بك 🌾")
    await message.answer(e(text), reply_markup=main_menu(bool(role)))


@router.message(Command("claim"))
async def claim(message: Message, state: FSMContext, core: Core):
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    from ..services import admins as admins_svc
    try:
        a = await admins_svc.claim_owner(core, message.from_user.id, parts[1] if len(parts) > 1 else "")
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    try:
        await message.delete()  # remove the setup code from the chat
    except Exception:
        pass
    await message.answer(f"✅ تم ربط حسابك كمالك للمتجر (حساب اللوحة: <code>{e(a['username'])}</code>).\n"
                         "ظهر لك الآن زر «🛠 لوحة الإدارة»، وستصلك الإشعارات ورموز دخول اللوحة هنا.",
                         reply_markup=main_menu(True))


@router.message(Command("cancel"))
@router.message(F.text.in_({"إلغاء", "الغاء"}))
async def cancel_cmd(message: Message, state: FSMContext, role: str | None):
    await state.clear()
    await message.answer("تم الإلغاء.", reply_markup=main_menu(bool(role)))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


# ---------------------------------------------------------------- browse
async def _types_view(core: Core, filters: dict | None = None):
    types = await catalog.list_types(core, for_customers=True, filters=filters)
    if not types:
        txt = "لا توجد مزارع مطابقة حالياً." if filters else "لا توجد مزارع معروضة حالياً، تابعنا قريباً 🌱"
        return txt, kb([btn("🔎 تصفية", "c:filter")] if not filters else [btn("↩️ كل الأنواع", "c:types")])
    rows = []
    for t in types:
        if t["available"] > 0:
            price = fmt(t["min_price"]) if t["min_price"] == t["max_price"] else f"{fmt(t['min_price'])}+"
            label = f"LVL {t['lvl']} • {t['barn']}/{t['silo']} • {price} USDT ({t['available']})"
        else:
            label = f"LVL {t['lvl']} • {t['barn']}/{t['silo']} • غير متوفر"
        rows.append([btn(label, f"c:t:{t['id']}")])
    rows.append([btn("🔎 تصفية حسب LVL / Barn / Silo / السعر", "c:filter")])
    if filters:
        rows.append([btn("↩️ كل الأنواع", "c:types")])
    head = "🛒 <b>اختر نوع المزرعة</b>\n(المستوى • المخزن/الصومعة • السعر (المتوفر))"
    return head, kb(*rows)


@router.message(F.text == BTN_BUY)
async def buy_menu(message: Message, state: FSMContext, core: Core):
    await state.clear()
    text, markup = await _types_view(core)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "c:types")
async def types_cb(cb: CallbackQuery, state: FSMContext, core: Core):
    await state.clear()
    text, markup = await _types_view(core)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data == "c:filter")
async def filter_ask(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Browse.filter)
    await cb.message.answer(
        "🔎 اكتب شروط البحث، أمثلة:\n<code>lvl 70</code>\n<code>lvl&gt;=60 price&lt;=15</code>\n"
        "<code>barn&gt;=4000 silo&gt;=3000</code>\n\nأو /cancel للإلغاء.")
    await cb.answer()


@router.message(Browse.filter, F.text)
async def filter_apply(message: Message, state: FSMContext, core: Core):
    flt = catalog.parse_filter(message.text)
    if not flt:
        await message.answer("لم أفهم الشروط. مثال: <code>lvl&gt;=70 price&lt;=12</code>")
        return
    await state.clear()
    text, markup = await _types_view(core, flt)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("c:t:"))
async def type_detail(cb: CallbackQuery, core: Core):
    type_id = int(cb.data.split(":")[2])
    t = await catalog.get_type(core, type_id)
    if not t or not t["is_active"]:
        await cb.answer("هذا النوع غير متاح.", show_alert=True)
        return
    tiers = await catalog.price_tiers(core, type_id)
    rows = [[btn(f"🛒 شراء بـ {fmt(x['price'])} USDT ({x['available']} متوفر)", f"c:bp:{type_id}:{x['price']}")]
            for x in tiers]
    if not tiers:
        rows.append([btn("❌ غير متوفر حالياً", "noop")])
    rows.append([btn("↩️ رجوع", "c:types")])
    await cb.message.edit_text(type_card(t, tiers), reply_markup=kb(*rows))
    await cb.answer()


# ------------------------------------------------------------------ buy
@router.callback_query(F.data.startswith("c:bp:"))
async def buy_prepare(cb: CallbackQuery, core: Core, db_user: dict):
    _, _, type_id, price = cb.data.split(":")
    try:
        o = await orders.prepare(core, cb.from_user.id, int(type_id), price)
    except StoreError as ex:
        markup = kb([btn("💳 شحن الرصيد", "c:topup")], [btn("↩️ رجوع", f"c:t:{type_id}")]) \
            if ex.code == "insufficient_funds" else kb([btn("↩️ رجوع", f"c:t:{type_id}")])
        await cb.message.edit_text(f"⚠️ {e(ex.message)}", reply_markup=markup)
        await cb.answer()
        return
    snap = o["type_snapshot"]
    bal = db_user["balance"]
    text = (
        "🧾 <b>تأكيد الطلب</b>\n\n"
        f"النوع: <b>{e(snap['name'])}</b>\n"
        f"LVL {snap['lvl']} • Barn {snap['barn']:,} • Silo {snap['silo']:,}\n"
        f"السعر: <b>{fmt(o['price'])} USDT</b>\n\n"
        f"رصيدك الحالي: {fmt(bal)} USDT\n"
        f"الرصيد بعد الشراء: {fmt(Decimal(bal) - o['price'])} USDT\n\n"
        f"رقم الطلب: <code>{o['ref']}</code>\n"
        f"⏱ صالح لمدة {orders.PENDING_TTL_MIN} دقيقة."
    )
    await cb.message.edit_text(text, reply_markup=kb(
        [btn("✅ تأكيد الشراء", f"c:bc:{o['id']}")], [btn("❌ إلغاء", f"c:bx:{o['id']}")]))
    await cb.answer()


@router.callback_query(F.data.startswith("c:bc:"))
async def buy_confirm(cb: CallbackQuery, core: Core):
    order_id = int(cb.data.split(":")[2])
    await cb.answer("⏳ جاري تنفيذ الطلب…")
    # remove the buttons first so extra taps cannot reach this handler again
    try:
        await cb.message.edit_text("⏳ <b>جاري تنفيذ الطلب…</b>")
    except Exception:
        pass
    try:
        o = await orders.purchase(core, cb.from_user.id, order_id)
    except StoreError as ex:
        if ex.code != "already":
            await cb.message.edit_text(f"⚠️ {e(ex.message)}", reply_markup=kb([btn("🛒 المزارع", "c:types")]))
            return
        # a second tap on the same button: just show the real state of the (single) order
        o = await orders.get_order(core, order_id)
        if o["status"] not in ("completed", "needs_review"):
            await cb.message.edit_text(f"⏳ الطلب <code>{o['ref']}</code>: {ORD_LABELS[o['status']]}",
                                       reply_markup=kb([btn("📦 طلباتي", "c:orders")]))
            return
    if o["status"] == "completed":
        await cb.message.edit_text(
            f"✅ <b>تم الشراء بنجاح</b>\nرقم الطلب: <code>{o['ref']}</code>\n"
            "تم إرسال بيانات الدخول في رسالة منفصلة 👇\nيمكنك عرضها لاحقاً من «📦 طلباتي».")
    else:
        await cb.message.edit_text(
            f"⚠️ تم حجز الحساب لطلبك <code>{o['ref']}</code> لكن تعذّر إرسال البيانات.\n"
            "الطلب الآن «يحتاج إلى مراجعة» وتم إبلاغ الإدارة. يمكنك إعادة المحاولة:",
            reply_markup=kb([btn("🔁 إعادة إرسال البيانات", f"c:or:{o['id']}")]))


@router.callback_query(F.data.startswith("c:bx:"))
async def buy_cancel(cb: CallbackQuery, core: Core):
    order_id = int(cb.data.split(":")[2])
    await core.pool.execute("UPDATE orders SET status='cancelled', failure_reason='ألغاه الزبون', updated_at=now() "
                            "WHERE id=$1 AND user_id=$2 AND status='pending'", order_id, cb.from_user.id)
    await cb.message.edit_text("تم إلغاء الطلب ولم يُخصم أي مبلغ.", reply_markup=kb([btn("🛒 المزارع", "c:types")]))
    await cb.answer()


# ---------------------------------------------------------------- wallet
async def _wallet_view(core: Core, user_id: int):
    u = await wallet.get_user(core, user_id)
    txs = await wallet.history(core, user_id, limit=10)
    lines = [f"💼 <b>محفظتي</b>\n\nالرصيد الحالي: <b>{fmt(u['balance'])} USDT</b>", ""]
    if txs:
        lines.append("آخر العمليات:")
        lines += [tx_line(t) for t in txs]
    else:
        lines.append("لا توجد عمليات بعد.")
    return "\n".join(lines), kb([btn("💳 شحن الرصيد", "c:topup"), btn("📜 السجل الكامل", "c:wh:0")])


@router.message(F.text == BTN_WALLET)
async def wallet_menu(message: Message, state: FSMContext, core: Core):
    await state.clear()
    text, markup = await _wallet_view(core, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("c:wh:"))
async def wallet_history(cb: CallbackQuery, core: Core):
    page = int(cb.data.split(":")[2])
    txs = await wallet.history(core, cb.from_user.id, limit=15, offset=page * 15)
    lines = [f"📜 <b>سجل العمليات</b> (صفحة {page + 1})", ""] + ([tx_line(t) for t in txs] or ["لا توجد عمليات."])
    nav = []
    if page > 0:
        nav.append(btn("◀️ السابق", f"c:wh:{page - 1}"))
    if len(txs) == 15:
        nav.append(btn("التالي ▶️", f"c:wh:{page + 1}"))
    await cb.message.edit_text("\n".join(lines), reply_markup=kb(nav, [btn("↩️ المحفظة", "c:wallet")]))
    await cb.answer()


@router.callback_query(F.data == "c:wallet")
async def wallet_cb(cb: CallbackQuery, core: Core):
    text, markup = await _wallet_view(core, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# ---------------------------------------------------------------- top-up
async def _topup_start(message: Message, state: FSMContext, core: Core, user_id: int):
    await state.clear()
    mn = await system.setting(core, "min_deposit", "1")
    mx = await system.setting(core, "max_deposit", "5000")
    await state.set_state(TopUp.amount)
    await message.answer(
        f"💳 <b>شحن الرصيد عبر Binance Pay</b>\n\nاختر المبلغ أو اكتبه بعملة USDT "
        f"(من {mn} إلى {mx}):",
        reply_markup=kb([btn(f"{a} USDT", f"c:ta:{a}") for a in QUICK_AMOUNTS[:3]],
                        [btn(f"{a} USDT", f"c:ta:{a}") for a in QUICK_AMOUNTS[3:]],
                        [btn("❌ إلغاء", "c:tcx")]))


@router.message(F.text == BTN_TOPUP)
async def topup_menu(message: Message, state: FSMContext, core: Core):
    await _topup_start(message, state, core, message.from_user.id)


@router.callback_query(F.data == "c:topup")
async def topup_cb(cb: CallbackQuery, state: FSMContext, core: Core):
    await _topup_start(cb.message, state, core, cb.from_user.id)
    await cb.answer()


async def _create_deposit(message: Message, state: FSMContext, core: Core, user_id: int, amount: str):
    try:
        d = await deposits.create(core, user_id, amount)
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.set_state(TopUp.photo)
    await state.update_data(deposit_id=d["id"])
    instructions = await system.setting(core, "payment_instructions")
    pay_id = d["pay_id_shown"]
    await message.answer(
        f"🧾 طلب الشحن: <code>{d['ref']}</code>\n"
        f"💵 المبلغ: <b>{fmt(d['amount'])} USDT</b>\n\n"
        f"🆔 معرّف Binance Pay:\n<code>{e(pay_id)}</code>\n\n"
        f"{e(instructions)}\n\n"
        "📸 <b>أرسل الآن لقطة شاشة إثبات الدفع.</b>",
        reply_markup=kb([b for b in (copy_btn("📋 نسخ معرّف الدفع", pay_id),
                                     copy_btn("📋 نسخ المبلغ", str(d["amount"]))) if b],
                        [btn("❌ إلغاء طلب الشحن", "c:tcx")]))


@router.callback_query(TopUp.amount, F.data.startswith("c:ta:"))
async def topup_quick(cb: CallbackQuery, state: FSMContext, core: Core):
    await cb.answer()
    await _create_deposit(cb.message, state, core, cb.from_user.id, cb.data.split(":")[2])


@router.message(TopUp.amount, F.text)
async def topup_amount(message: Message, state: FSMContext, core: Core):
    await _create_deposit(message, state, core, message.from_user.id, message.text.replace("USDT", "").strip())


@router.callback_query(F.data == "c:tcx")
async def topup_cancel(cb: CallbackQuery, state: FSMContext, core: Core):
    data = await state.get_data()
    if data.get("deposit_id"):
        try:
            await deposits.cancel(core, cb.from_user.id, data["deposit_id"])
        except StoreError:
            pass
    await state.clear()
    await cb.message.answer("تم إلغاء طلب الشحن.")
    await cb.answer()


@router.message(TopUp.photo, F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def topup_photo(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    if message.photo:
        file_id, unique = message.photo[-1].file_id, message.photo[-1].file_unique_id
    else:
        file_id, unique = message.document.file_id, message.document.file_unique_id
    try:
        await deposits.attach_photo(core, message.from_user.id, data["deposit_id"], file_id, unique)
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        if ex.code == "bad_state":
            await state.clear()
        return
    if await system.setting_bool(core, "require_txid"):
        await state.set_state(TopUp.txid)
        await message.answer("✅ تم استلام الصورة.\n\n🔢 أرسل الآن <b>رقم الطلب (Order ID)</b> الظاهر في تفاصيل "
                             "التحويل داخل تطبيق Binance.")
        return
    await _submit(message, state, core)


@router.message(TopUp.photo)
async def topup_photo_wrong(message: Message):
    await message.answer("📸 أرسل لقطة شاشة إثبات الدفع كصورة، أو /cancel للإلغاء.")


@router.message(TopUp.txid, F.text)
async def topup_txid(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    try:
        await deposits.attach_txid(core, message.from_user.id, data["deposit_id"], message.text)
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        if ex.code == "bad_state":
            await state.clear()
        return
    await _submit(message, state, core)


async def _submit(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    try:
        d = await deposits.submit(core, message.from_user.id, data["deposit_id"])
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.clear()
    if d["status"] == "approved":
        return  # auto-verified; the approval notification was already sent
    await message.answer(
        f"✅ تم استلام طلب الشحن <code>{d['ref']}</code> وهو الآن <b>قيد المراجعة</b>.\n"
        "سيصلك إشعار فور التحقق من وصول المبلغ.")


# ---------------------------------------------------------------- orders
async def _orders_view(core: Core, user_id: int):
    ords = await orders.list_orders(core, user_id=user_id, limit=10)
    deps = await deposits.list_deposits(core, user_id=user_id, limit=5)
    lines = ["📦 <b>طلباتي</b>", ""]
    rows = []
    if ords:
        for o in ords:
            rows.append([btn(order_line(o)[:60], f"c:o:{o['id']}")])
    else:
        lines.append("لا توجد طلبات شراء بعد.")
    if deps:
        lines += ["", "💳 <b>آخر طلبات الشحن:</b>"] + [f"{deposit_line(d)}\n   <code>{d['ref']}</code>" for d in deps]
    return "\n".join(lines), kb(*rows)


@router.message(F.text == BTN_ORDERS)
async def orders_menu(message: Message, state: FSMContext, core: Core):
    await state.clear()
    text, markup = await _orders_view(core, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "c:orders")
async def orders_cb(cb: CallbackQuery, core: Core):
    text, markup = await _orders_view(core, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data.startswith("c:o:"))
async def order_detail(cb: CallbackQuery, core: Core):
    o = await orders.get_order(core, int(cb.data.split(":")[2]))
    if not o or o["user_id"] != cb.from_user.id:
        await cb.answer("الطلب غير موجود.", show_alert=True)
        return
    snap = o["type_snapshot"]
    text = (f"🧾 <b>الطلب</b> <code>{o['ref']}</code>\n\n"
            f"النوع: {e(snap['name'])} — LVL {snap['lvl']} • Barn {snap['barn']} • Silo {snap['silo']}\n"
            f"السعر: {fmt(o['price'])} USDT\nالحالة: <b>{ORD_LABELS[o['status']]}</b>\n"
            f"التاريخ: {dt(o['created_at'])}")
    if o["status"] == "completed":
        text += f"\nتم التسليم: {dt(o['delivered_at'])}"
    if o["status"] in ("cancelled", "needs_review") and o["admin_note"]:
        text += f"\nملاحظة: {e(o['admin_note'])}"
    rows = []
    if o["status"] == "completed":
        rows.append([btn("🔑 عرض بيانات الدخول", f"c:oc:{o['id']}")])
    if o["status"] == "needs_review" and (o["failure_reason"] or "").startswith("فشل التسليم"):
        rows.append([btn("🔁 إعادة إرسال البيانات", f"c:or:{o['id']}")])
    rows.append([btn("↩️ رجوع", "c:orders")])
    await cb.message.edit_text(text, reply_markup=kb(*rows))
    await cb.answer()


@router.callback_query(F.data.startswith("c:oc:"))
async def order_credentials(cb: CallbackQuery, core: Core):
    try:
        o, login, password = await orders.buyer_credentials(core, cb.from_user.id, int(cb.data.split(":")[2]))
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await cb.message.answer(credentials_text(o, login, password), reply_markup=credentials_kb(login, password))
    await cb.answer()


@router.callback_query(F.data.startswith("c:or:"))
async def order_retry(cb: CallbackQuery, core: Core):
    order_id = int(cb.data.split(":")[2])
    try:
        ok = await orders.retry_delivery(core, order_id, user_id=cb.from_user.id, actor=f"tg:{cb.from_user.id}")
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await cb.answer("✅ تم إرسال البيانات" if ok else "تعذر الإرسال، تم إبلاغ الإدارة.", show_alert=not ok)
    if ok:
        await cb.message.edit_text("✅ تم إرسال بيانات الدخول بنجاح 👇")


# --------------------------------------------------------------- support
@router.message(F.text == BTN_SUPPORT)
async def support(message: Message, state: FSMContext, core: Core):
    await state.clear()
    s = await system.get_settings(core)
    rows = []
    if s.get("support_username"):
        rows.append([url_btn("💬 مراسلة الدعم", f"https://t.me/{s['support_username']}")])
    await message.answer(
        f"🛟 <b>الدعم الفني</b>\n\n{e(s.get('support_text', ''))}\n\n"
        f"معرّفك في البوت: <code>{message.from_user.id}</code>\n"
        "أرفق رقم الطلب أو الشحن عند التواصل لتسريع الخدمة.",
        reply_markup=kb(*rows) if rows else None)


@router.message(StateFilter(None))
async def fallback(message: Message, role: str | None):
    await message.answer("اختر من القائمة بالأسفل 👇", reply_markup=main_menu(bool(role)))
