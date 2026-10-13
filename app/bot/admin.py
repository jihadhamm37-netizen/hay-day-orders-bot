"""Admin menu inside Telegram — visible only to authorised Telegram IDs."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message, TelegramObject

from ..core import Core, StoreError, fmt
from ..services import admins, backup, catalog, deposits, orders, stats, system, wallet
from ..services.deposits import STATUS_LABELS as DEP_LABELS
from ..services.orders import STATUS_LABELS as ORD_LABELS
from .ui import BTN_ADMIN, btn, deposit_line, dt, e, kb, order_line, tx_line, type_line

router = Router(name="admin")

ACC_LABELS = {"available": "متوفر", "reserved": "محجوز", "sold": "مباع", "disabled": "موقوف"}
QUICK_REJECT = ["لم يصل المبلغ", "المبلغ المحوّل لا يطابق الطلب", "الإثبات غير واضح أو غير صحيح",
                "رقم العملية غير صحيح"]


class AdminOnly(BaseMiddleware):
    """Drops every admin update from non-admins silently (the menu stays invisible to them)."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        if not data.get("role"):
            if isinstance(event, CallbackQuery):
                await event.answer("غير مصرح.", show_alert=True)
            return None
        return await handler(event, data)


router.message.middleware(AdminOnly())
router.callback_query.middleware(AdminOnly())


def actor(user_id: int) -> str:
    return f"tg:{user_id}"


async def need(cb_or_msg, role: str, perm: str) -> bool:
    if admins.has_perm(role, perm):
        return True
    if isinstance(cb_or_msg, CallbackQuery):
        await cb_or_msg.answer("ليست لديك صلاحية لهذا الإجراء.", show_alert=True)
    else:
        await cb_or_msg.answer("ليست لديك صلاحية لهذا الإجراء.")
    return False


class A(StatesGroup):
    new_type = State()
    edit_type = State()
    type_price = State()
    add_accounts = State()
    acc_price = State()
    dep_amount = State()
    dep_reason = State()
    refund_reason = State()
    user_search = State()
    user_amount = State()
    user_reason = State()
    setting_value = State()
    type_search = State()


async def reply(target: Message | CallbackQuery, text: str, markup=None, edit: bool = True):
    """Edit the callback's message when possible, otherwise send a new one."""
    if isinstance(target, CallbackQuery):
        msg = target.message
        if edit and msg and msg.text is not None:
            try:
                await msg.edit_text(text, reply_markup=markup)
                return
            except Exception:
                pass
        await msg.answer(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


# =================================================================== menu
async def _menu(core: Core, role: str):
    pending = await core.pool.fetchval("SELECT count(*) FROM deposits WHERE status='under_review'")
    review = await core.pool.fetchval("SELECT count(*) FROM orders WHERE status='needs_review'")
    alerts = await core.pool.fetchval("SELECT count(*) FROM alerts WHERE NOT is_read")
    rows = [
        [btn("📊 الإحصائيات", "a:stats"), btn(f"🔔 التنبيهات ({alerts})", "a:alerts")],
        [btn(f"💰 طلبات الشحن ({pending})", "a:deps"), btn(f"🧾 الطلبات ⚠️{review}", "a:ords:review:0")],
    ]
    if admins.has_perm(role, "catalog"):
        rows.append([btn("📦 الأنواع والمخزون", "a:types"), btn("➕ نوع جديد", "a:tnew")])
    if admins.has_perm(role, "users"):
        rows.append([btn("👤 بحث عن مستخدم", "a:usearch"), btn("⚙️ الإعدادات", "a:set")])
    row = [btn("📜 سجل النشاط", "a:audit")]
    if admins.has_perm(role, "backup"):
        row.append(btn("🗄 نسخة احتياطية", "a:backup"))
    rows.append(row)
    text = (f"🛠 <b>لوحة الإدارة</b> — صلاحيتك: {admins.ROLES.get(role, role)}\n\n"
            "لإدارة متقدمة استخدم لوحة التحكم على الويب.")
    return text, kb(*rows)


@router.message(F.text == BTN_ADMIN)
@router.message(Command("admin"))
async def admin_menu(message: Message, state: FSMContext, core: Core, role: str):
    await state.clear()
    text, markup = await _menu(core, role)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "a:menu")
async def admin_menu_cb(cb: CallbackQuery, state: FSMContext, core: Core, role: str):
    await state.clear()
    text, markup = await _menu(core, role)
    await reply(cb, text, markup)
    await cb.answer()


BACK = [btn("↩️ القائمة", "a:menu")]


# ================================================================== stats
@router.callback_query(F.data == "a:stats")
async def stats_cb(cb: CallbackQuery, core: Core):
    s = await stats.overview(core)
    sa, de, us, st = s["sales"], s["deposits"], s["users"], s["stock"]
    text = (
        "📊 <b>الإحصائيات</b>\n\n"
        f"🛒 المبيعات المكتملة: <b>{sa['completed']}</b>\n"
        f"💵 إجمالي الإيرادات: <b>{fmt(sa['revenue'])} USDT</b>\n"
        f"📅 اليوم: {sa['today_count']} عملية — {fmt(sa['today_revenue'])} USDT\n"
        f"🗓 آخر 30 يوماً: {fmt(sa['month_revenue'])} USDT\n\n"
        f"💳 إجمالي المشحون (مقبول): <b>{fmt(de['total_deposited'])} USDT</b>\n"
        f"🔎 بانتظار المراجعة: {de['pending_review']} ({fmt(de['pending_amount'])} USDT)\n\n"
        f"👥 المستخدمون: {us['users']} (جدد اليوم: {us['new_today']})\n"
        f"💼 مجموع أرصدة العملاء: <b>{fmt(us['balances'])} USDT</b>\n\n"
        f"📦 المخزون المتوفر: {st['available']} (قيمته {fmt(st['stock_value'])} USDT)\n"
        f"✅ المباع: {st['sold']} • محجوز: {st['reserved']} • موقوف: {st['disabled']}\n"
        f"🚫 أنواع نفد مخزونها: {s['out_of_stock_types']}\n"
        f"⚠️ طلبات تحتاج مراجعة: {sa['needs_review']}"
    )
    await reply(cb, text, kb(BACK))
    await cb.answer()


@router.callback_query(F.data == "a:alerts")
async def alerts_cb(cb: CallbackQuery, core: Core):
    items = await system.list_alerts(core, unread_only=True, limit=15)
    icons = {"error": "🚨", "warning": "⚠️", "info": "ℹ️"}
    lines = ["🔔 <b>التنبيهات غير المقروءة</b>", ""] + [
        f"{icons.get(a['level'], '•')} {dt(a['created_at'])} — {e(a['message'])}" for a in items]
    if not items:
        lines.append("لا توجد تنبيهات جديدة ✅")
    await reply(cb, "\n".join(lines), kb([btn("✔️ تعليم الكل كمقروء", "a:alread")] if items else [], BACK))
    await cb.answer()


@router.callback_query(F.data == "a:alread")
async def alerts_read(cb: CallbackQuery, core: Core):
    await system.mark_alerts_read(core)
    await cb.answer("تم.")
    await reply(cb, "✔️ تم تعليم جميع التنبيهات كمقروءة.", kb(BACK))


# ================================================================== types
async def _types_list(core: Core, filters: dict | None = None):
    types = await catalog.list_types(core, filters=filters)
    rows = []
    for t in types:
        state = "" if t["is_active"] else "⏸ "
        rows.append([btn(f"{state}{t['name']} • {fmt(t['price'])}$ • ✅{t['available_raw']} 💰{t['sold']}",
                         f"a:t:{t['id']}")])
    rows.append([btn("➕ نوع جديد", "a:tnew"), btn("🔎 بحث/تصفية", "a:tsearch")])
    rows.append(BACK)
    head = "📦 <b>الأنواع والمخزون</b>\n✅ متوفر • 💰 مباع\n"
    if not types:
        head += "\nلا توجد أنواع."
    return head, kb(*rows)


@router.callback_query(F.data == "a:types")
async def types_cb(cb: CallbackQuery, state: FSMContext, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.clear()
    text, markup = await _types_list(core)
    await reply(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data == "a:tsearch")
async def types_search(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.set_state(A.type_search)
    await cb.message.answer("اكتب شروط التصفية مثل: <code>lvl&gt;=60 barn&gt;=4000 price&lt;=15</code>")
    await cb.answer()


@router.message(A.type_search, F.text)
async def types_search_apply(message: Message, state: FSMContext, core: Core):
    await state.clear()
    text, markup = await _types_list(core, catalog.parse_filter(message.text))
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "a:tnew")
async def type_new(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.set_state(A.new_type)
    await cb.message.answer(
        "➕ <b>نوع مزرعة جديد</b>\nأرسل البيانات بهذا الترتيب في سطر واحد:\n"
        "<code>LVL Barn Silo Price [الاسم]</code>\n\nمثال:\n<code>70 4000 3000 10</code>\n"
        "<code>85 5500 5000 18.5 مزرعة VIP</code>\n\n/cancel للإلغاء")
    await cb.answer()


def _parse_type_line(text: str) -> dict:
    parts = text.split()
    if len(parts) < 4:
        raise StoreError("bad_input", "الصيغة: LVL Barn Silo Price [الاسم]")
    data = {"lvl": parts[0], "barn": parts[1], "silo": parts[2], "price": parts[3]}
    if len(parts) > 4:
        data["name"] = " ".join(parts[4:])
    return data


@router.message(A.new_type, F.text)
async def type_new_save(message: Message, state: FSMContext, core: Core):
    try:
        t = await catalog.create_type(core, actor(message.from_user.id), _parse_type_line(message.text))
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.clear()
    await message.answer(f"✅ تم إنشاء النوع «{e(t['name'])}».\nأضف الآن الحسابات التابعة له:",
                         reply_markup=kb([btn("➕ إضافة حسابات", f"a:ta:{t['id']}")], [btn("📦 فتح النوع", f"a:t:{t['id']}")]))


async def _type_view(core: Core, type_id: int):
    t = await catalog.get_type(core, type_id)
    if not t:
        return "النوع غير موجود.", kb(BACK)
    tiers = await catalog.price_tiers(core, type_id)
    text = (f"🌾 <b>{e(t['name'])}</b> {'(⏸ موقوف عن البيع)' if not t['is_active'] else ''}\n"
            f"{type_line(t)}\nالسعر: <b>{fmt(t['price'])} USDT</b>\n\n"
            f"✅ متوفر: {t['available_raw']}\n🔒 محجوز: {t['reserved']}\n💰 مباع: {t['sold']}\n"
            f"⏸ موقوف: {t['disabled']}\nالإجمالي: {t['total']}")
    if len(tiers) > 1:
        text += "\n\nالأسعار المتوفرة: " + "، ".join(f"{fmt(x['price'])} ({x['available']})" for x in tiers)
    rows = [
        [btn("➕ إضافة حسابات / CSV", f"a:ta:{type_id}")],
        [btn("📋 الحسابات المتوفرة", f"a:tl:{type_id}:available:0"), btn("💰 المباعة", f"a:tl:{type_id}:sold:0")],
        [btn("⏸ الموقوفة", f"a:tl:{type_id}:disabled:0"), btn("🔒 المحجوزة", f"a:tl:{type_id}:reserved:0")],
        [btn("💲 تعديل السعر", f"a:tp:{type_id}"), btn("✏️ تعديل البيانات", f"a:te:{type_id}")],
        [btn("▶️ تفعيل البيع" if not t["is_active"] else "⏸ إيقاف البيع", f"a:tt:{type_id}")],
    ]
    if t["total"] == 0:
        rows.append([btn("🗑 حذف النوع", f"a:td:{type_id}")])
    rows.append([btn("↩️ الأنواع", "a:types")])
    return text, kb(*rows)


@router.callback_query(F.data.startswith("a:t:"))
async def type_cb(cb: CallbackQuery, state: FSMContext, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.clear()
    text, markup = await _type_view(core, int(cb.data.split(":")[2]))
    await reply(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.startswith("a:tt:"))
async def type_toggle(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    type_id = int(cb.data.split(":")[2])
    t = await catalog.get_type(core, type_id)
    await catalog.update_type(core, actor(cb.from_user.id), type_id, {"is_active": not t["is_active"]})
    await cb.answer("تم إيقاف البيع" if t["is_active"] else "تم تفعيل البيع")
    text, markup = await _type_view(core, type_id)
    await reply(cb, text, markup)


@router.callback_query(F.data.startswith("a:td:"))
async def type_delete(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    try:
        await catalog.delete_type(core, actor(cb.from_user.id), int(cb.data.split(":")[2]))
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await cb.answer("تم الحذف")
    text, markup = await _types_list(core)
    await reply(cb, text, markup)


@router.callback_query(F.data.startswith("a:tp:"))
async def type_price(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.set_state(A.type_price)
    await state.update_data(type_id=int(cb.data.split(":")[2]))
    await cb.message.answer("💲 أرسل السعر الجديد للنوع بالكامل (USDT):\n"
                            "ملاحظة: الحسابات التي لها سعر خاص تحتفظ بسعرها.")
    await cb.answer()


@router.message(A.type_price, F.text)
async def type_price_save(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    try:
        await catalog.update_type(core, actor(message.from_user.id), data["type_id"], {"price": message.text})
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.clear()
    text, markup = await _type_view(core, data["type_id"])
    await message.answer("✅ تم تحديث السعر.\n\n" + text, reply_markup=markup)


@router.callback_query(F.data.startswith("a:te:"))
async def type_edit(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.set_state(A.edit_type)
    await state.update_data(type_id=int(cb.data.split(":")[2]))
    await cb.message.answer("✏️ أرسل البيانات الجديدة:\n<code>LVL Barn Silo Price [الاسم]</code>")
    await cb.answer()


@router.message(A.edit_type, F.text)
async def type_edit_save(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    try:
        await catalog.update_type(core, actor(message.from_user.id), data["type_id"], _parse_type_line(message.text))
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.clear()
    text, markup = await _type_view(core, data["type_id"])
    await message.answer("✅ تم التحديث.\n\n" + text, reply_markup=markup)


# --------------------------------------------------------------- accounts
@router.callback_query(F.data.startswith("a:ta:"))
async def accounts_add(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.set_state(A.add_accounts)
    await state.update_data(type_id=int(cb.data.split(":")[2]), items=None)
    await cb.message.answer(
        "➕ <b>إضافة حسابات</b>\n\nأرسل الحسابات نصاً، حساب في كل سطر:\n"
        "<code>ID:Password</code>\nأو <code>ID,Password,السعر_الخاص</code> (السعر اختياري)\n\n"
        "أو أرسل ملف <b>CSV</b> بالأعمدة: <code>id,password,price,note</code>\n\n"
        "سيتم فحص التكرار والأخطاء قبل الحفظ. /cancel للإلغاء")
    await cb.answer()


async def _preview(message: Message, state: FSMContext, core: Core, items: list[dict], parse_errors: list[str]):
    report = await catalog.validate_accounts(core, items)
    valid = report["valid"]
    await state.update_data(items=[{k: v for k, v in x.items() if k != "hash"} | {"price": str(x["price"]) if x["price"] else None}
                                   for x in valid])
    problems = parse_errors + report["errors"] + report["duplicates_in_file"] + report["duplicates_in_db"]
    text = (f"🔎 <b>نتيجة الفحص</b>\n\n✅ صالح للحفظ: <b>{len(valid)}</b>\n"
            f"❌ أخطاء: {len(parse_errors) + len(report['errors'])}\n"
            f"♻️ مكرر داخل الملف: {len(report['duplicates_in_file'])}\n"
            f"📦 موجود مسبقاً: {len(report['duplicates_in_db'])}")
    if problems:
        text += "\n\n" + "\n".join(e(p) for p in problems[:20])
        if len(problems) > 20:
            text += f"\n… و{len(problems) - 20} أخرى"
    markup = kb([btn(f"✅ حفظ {len(valid)} حساب", "a:imp:ok")] if valid else [], [btn("❌ إلغاء", "a:imp:no")])
    await message.answer(text, reply_markup=markup)


@router.message(A.add_accounts, F.document)
async def accounts_csv(message: Message, state: FSMContext, core: Core, bot: Bot):
    doc = message.document
    if doc.file_size and doc.file_size > 2_000_000:
        await message.answer("⚠️ الملف أكبر من 2MB.")
        return
    buf = await bot.download(doc)
    items, errors = catalog.parse_csv(buf.read())
    await _preview(message, state, core, items, errors)


@router.message(A.add_accounts, F.text)
async def accounts_text(message: Message, state: FSMContext, core: Core):
    items, errors = catalog.parse_lines(message.text)
    try:
        await message.delete()  # do not leave plaintext passwords in the chat history
    except Exception:
        pass
    await _preview(message, state, core, items, errors)


@router.callback_query(A.add_accounts, F.data == "a:imp:ok")
async def accounts_save(cb: CallbackQuery, state: FSMContext, core: Core):
    data = await state.get_data()
    items = data.get("items") or []
    await state.update_data(items=None)
    if not items:
        await cb.answer("لا يوجد ما يُحفظ.", show_alert=True)
        return
    report = await catalog.add_accounts(core, actor(cb.from_user.id), data["type_id"], items)
    await state.clear()
    await cb.answer()
    await reply(cb, f"✅ تم حفظ <b>{report['inserted']}</b> حساب.\n"
                    f"تم تخطي: {len(items) - report['inserted']}",
                kb([btn("➕ إضافة المزيد", f"a:ta:{data['type_id']}")], [btn("📦 فتح النوع", f"a:t:{data['type_id']}")]))


@router.callback_query(F.data == "a:imp:no")
async def accounts_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await reply(cb, "تم الإلغاء ولم يُحفظ شيء.", kb(BACK))
    await cb.answer()


@router.callback_query(F.data.startswith("a:tl:"))
async def accounts_list(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    _, _, type_id, status, page = cb.data.split(":")
    type_id, page = int(type_id), int(page)
    items = await catalog.list_accounts(core, type_id, status, limit=10, offset=page * 10)
    rows = [[btn(f"#{a['id']} {a['login_hint']} • {fmt(a['effective_price'])}$"
                 + (" ★" if a["custom_price"] else "") + (f" • {a['order_ref']}" if a["order_ref"] else ""),
                 f"a:ac:{a['id']}")] for a in items]
    nav = []
    if page > 0:
        nav.append(btn("◀️", f"a:tl:{type_id}:{status}:{page - 1}"))
    if len(items) == 10:
        nav.append(btn("▶️", f"a:tl:{type_id}:{status}:{page + 1}"))
    rows += [nav, [btn("↩️ النوع", f"a:t:{type_id}")]]
    head = f"📋 الحسابات ({ACC_LABELS[status]}) — صفحة {page + 1}\n★ = سعر خاص"
    if not items:
        head += "\n\nلا توجد حسابات."
    await reply(cb, head, kb(*rows))
    await cb.answer()


async def _account_view(core: Core, account_id: int):
    rs = await catalog.list_accounts(core, search=str(account_id), limit=1)
    if not rs:
        return "الحساب غير موجود.", kb(BACK)
    a = rs[0]
    text = (f"🔐 <b>حساب #{a['id']}</b>\nالنوع: {e(a['type_name'])}\nID: {e(a['login_hint'])} (مخفي)\n"
            f"الحالة: <b>{ACC_LABELS[a['status']]}</b>\nالسعر الفعلي: {fmt(a['effective_price'])} USDT"
            + (" (سعر خاص)" if a["custom_price"] else "") +
            f"\nأُضيف: {dt(a['created_at'])}" + (f"\nبيع: {dt(a['sold_at'])} — {a['order_ref']}" if a["sold_at"] else "")
            + (f"\nملاحظة: {e(a['note'])}" if a["note"] else ""))
    rows = []
    if a["status"] in ("available", "disabled"):
        rows.append([btn("⏸ إيقاف عن البيع" if a["status"] == "available" else "▶️ إتاحة للبيع", f"a:act:{a['id']}"),
                     btn("💲 سعر خاص", f"a:acp:{a['id']}")])
        if not a["order_ref"]:
            rows.append([btn("🗑 حذف", f"a:acd:{a['id']}")])
    rows.append([btn("↩️ النوع", f"a:t:{a['type_id']}")])
    return text, kb(*rows)


@router.callback_query(F.data.startswith("a:ac:"))
async def account_cb(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    text, markup = await _account_view(core, int(cb.data.split(":")[2]))
    await reply(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.startswith("a:act:"))
async def account_toggle(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    acc_id = int(cb.data.split(":")[2])
    cur = await core.pool.fetchval("SELECT status FROM farm_accounts WHERE id=$1", acc_id)
    try:
        await catalog.update_account(core, actor(cb.from_user.id), acc_id,
                                     {"status": "disabled" if cur == "available" else "available"})
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await cb.answer("تم")
    text, markup = await _account_view(core, acc_id)
    await reply(cb, text, markup)


@router.callback_query(F.data.startswith("a:acd:"))
async def account_delete(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "catalog"):
        return
    acc_id = int(cb.data.split(":")[2])
    type_id = await core.pool.fetchval("SELECT type_id FROM farm_accounts WHERE id=$1", acc_id)
    try:
        await catalog.delete_account(core, actor(cb.from_user.id), acc_id)
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await cb.answer("تم الحذف")
    text, markup = await _type_view(core, type_id)
    await reply(cb, text, markup)


@router.callback_query(F.data.startswith("a:acp:"))
async def account_price(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "catalog"):
        return
    await state.set_state(A.acc_price)
    await state.update_data(account_id=int(cb.data.split(":")[2]))
    await cb.message.answer("💲 أرسل السعر الخاص لهذا الحساب، أو <code>0</code> لإلغاء السعر الخاص.")
    await cb.answer()


@router.message(A.acc_price, F.text)
async def account_price_save(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    val = message.text.strip()
    try:
        await catalog.update_account(core, actor(message.from_user.id), data["account_id"],
                                     {"custom_price": None if val in ("0", "0.0", "-") else val})
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.clear()
    text, markup = await _account_view(core, data["account_id"])
    await message.answer("✅ تم.\n\n" + text, reply_markup=markup)


# =============================================================== deposits
@router.callback_query(F.data == "a:deps")
async def deposits_list(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "deposits"):
        return
    items = await deposits.list_deposits(core, status="under_review", limit=20)
    rows = [[btn(f"{fmt(d['amount'])} USDT • {d['user_id']} • {dt(d['created_at'])}", f"a:dp:{d['id']}")]
            for d in items]
    rows.append([btn("📜 آخر الطلبات المراجَعة", "a:depsh")])
    rows.append(BACK)
    await reply(cb, f"💰 <b>طلبات الشحن قيد المراجعة</b> ({len(items)})" + ("" if items else "\n\nلا توجد طلبات ✅"),
                kb(*rows))
    await cb.answer()


@router.callback_query(F.data == "a:depsh")
async def deposits_history(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "deposits"):
        return
    items = await deposits.list_deposits(core, limit=20)
    lines = ["📜 <b>آخر طلبات الشحن</b>", ""] + [f"{deposit_line(d)} • <code>{d['user_id']}</code>" for d in items]
    await reply(cb, "\n".join(lines), kb([btn("↩️ رجوع", "a:deps")]))
    await cb.answer()


@router.callback_query(F.data.startswith("a:dp:"))
async def deposit_view(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "deposits"):
        return
    d = await deposits.get(core, int(cb.data.split(":")[2]))
    if not d:
        await cb.answer("غير موجود", show_alert=True)
        return
    text = deposits.admin_card(d) + f"\nالحالة: <b>{DEP_LABELS[d['status']]}</b>"
    from .messenger import deposit_review_kb
    markup = deposit_review_kb(d["id"]) if d["status"] == "under_review" else None
    if d["proof_file_id"]:
        await cb.message.answer_photo(d["proof_file_id"], caption=text[:1024], reply_markup=markup)
    else:
        await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


async def _edit_review_msg(cb: CallbackQuery, suffix: str):
    """Append the decision to the admin card (photo caption or text) and drop the buttons."""
    msg = cb.message
    try:
        if msg.photo:
            await msg.edit_caption(caption=((msg.caption or "") + "\n\n" + suffix)[:1024], reply_markup=None)
        else:
            await msg.edit_text((msg.text or "") + "\n\n" + suffix, reply_markup=None)
    except Exception:
        await msg.answer(suffix)


@router.callback_query(F.data.startswith("a:da:"))
async def deposit_approve(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "deposits"):
        return
    try:
        d = await deposits.approve(core, actor(cb.from_user.id), int(cb.data.split(":")[2]))
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        await _edit_review_msg(cb, f"ℹ️ {ex.message}")
        return
    await cb.answer("تم القبول وإضافة الرصيد ✅")
    await _edit_review_msg(cb, f"✅ تم القبول بواسطة {e(cb.from_user.full_name)} — أُضيف {fmt(d['credited_amount'])} USDT")


@router.callback_query(F.data.startswith("a:dam:"))
async def deposit_amount_ask(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "deposits"):
        return
    await state.set_state(A.dep_amount)
    await state.update_data(deposit_id=int(cb.data.split(":")[2]))
    await cb.message.answer("✏️ أرسل المبلغ الذي وصل فعلياً (USDT) ليُضاف بدلاً من المبلغ المطلوب:")
    await cb.answer()


@router.message(A.dep_amount, F.text)
async def deposit_amount_save(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    try:
        d = await deposits.approve(core, actor(message.from_user.id), data["deposit_id"], credited=message.text,
                                   note="مبلغ معدّل من المشرف")
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        if ex.code == "already":
            await state.clear()
        return
    await state.clear()
    await message.answer(f"✅ تم قبول {d['ref']} وإضافة {fmt(d['credited_amount'])} USDT.")


@router.callback_query(F.data.startswith("a:dr:"))
async def deposit_reject_ask(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "deposits"):
        return
    dep_id = int(cb.data.split(":")[2])
    await state.set_state(A.dep_reason)
    await state.update_data(deposit_id=dep_id)
    await cb.message.answer("❌ اختر سبب الرفض أو اكتبه:",
                            reply_markup=kb(*[[btn(r, f"a:drq:{dep_id}:{i}")] for i, r in enumerate(QUICK_REJECT)]))
    await cb.answer()


async def _do_reject(target, core: Core, admin_id: int, dep_id: int, reason: str, state: FSMContext):
    try:
        d = await deposits.reject(core, actor(admin_id), dep_id, reason)
    except StoreError as ex:
        await reply(target, f"⚠️ {e(ex.message)}", edit=False)
        return
    await state.clear()
    await reply(target, f"❌ تم رفض {d['ref']} — السبب: {e(reason)}", edit=False)


@router.callback_query(F.data.startswith("a:drq:"))
async def deposit_reject_quick(cb: CallbackQuery, state: FSMContext, core: Core, role: str):
    if not await need(cb, role, "deposits"):
        return
    _, _, dep_id, idx = cb.data.split(":")
    await cb.answer()
    await _do_reject(cb, core, cb.from_user.id, int(dep_id), QUICK_REJECT[int(idx)], state)


@router.message(A.dep_reason, F.text)
async def deposit_reject_text(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    await _do_reject(message, core, message.from_user.id, data["deposit_id"], message.text, state)


# ================================================================= orders
@router.callback_query(F.data.startswith("a:ords:"))
async def orders_list(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "orders"):
        return
    _, _, flt, page = cb.data.split(":")
    page = int(page)
    items = await orders.list_orders(core, status="needs_review" if flt == "review" else None,
                                     limit=10, offset=page * 10)
    rows = [[btn(f"{order_line(o)[:45]} • {o['user_id']}", f"a:o:{o['id']}")] for o in items]
    nav = []
    if page > 0:
        nav.append(btn("◀️", f"a:ords:{flt}:{page - 1}"))
    if len(items) == 10:
        nav.append(btn("▶️", f"a:ords:{flt}:{page + 1}"))
    rows += [nav, [btn("⚠️ تحتاج مراجعة", "a:ords:review:0"), btn("📋 الكل", "a:ords:all:0")], BACK]
    title = "⚠️ الطلبات التي تحتاج مراجعة" if flt == "review" else "🧾 جميع الطلبات"
    await reply(cb, f"<b>{title}</b>" + ("" if items else "\n\nلا توجد طلبات."), kb(*rows))
    await cb.answer()


async def _order_view(core: Core, order_id: int):
    o = await orders.get_order(core, order_id)
    if not o:
        return "غير موجود", kb(BACK)
    snap = o["type_snapshot"]
    text = (f"🧾 <b>{o['ref']}</b>\nالمشتري: <code>{o['user_id']}</code> {('@' + e(o['username'])) if o['username'] else ''}\n"
            f"النوع: {e(snap['name'])} — LVL {snap['lvl']}\nالسعر: {fmt(o['price'])} USDT\n"
            f"الحالة: <b>{ORD_LABELS[o['status']]}</b>\nالحساب: {('#' + str(o['account_id']) + ' ' + e(o['login_hint'])) if o['account_id'] else '—'}\n"
            f"أُنشئ: {dt(o['created_at'])}\nسُلّم: {dt(o['delivered_at'])}")
    if o["failure_reason"]:
        text += f"\nالسبب: {e(o['failure_reason'])}"
    if o["admin_note"]:
        text += f"\nملاحظة الإدارة: {e(o['admin_note'])}"
    rows = []
    if o["status"] == "needs_review":
        rows.append([btn("🔁 إعادة الإرسال", f"a:or:{o['id']}"), btn("✅ تم التسليم يدوياً", f"a:om:{o['id']}")])
    if o["status"] in ("needs_review", "completed", "processing"):
        rows.append([btn("↩️ استرداد المبلغ", f"a:orf:{o['id']}")])
    rows.append([btn("↩️ الطلبات", "a:ords:all:0")])
    return text, kb(*rows)


@router.callback_query(F.data.startswith("a:o:"))
async def order_cb(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "orders"):
        return
    text, markup = await _order_view(core, int(cb.data.split(":")[2]))
    await reply(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.startswith("a:or:"))
async def order_redeliver(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "orders"):
        return
    oid = int(cb.data.split(":")[2])
    try:
        ok = await orders.retry_delivery(core, oid, actor=actor(cb.from_user.id))
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await cb.answer("✅ تم التسليم" if ok else "فشل الإرسال مجدداً (ربما حظر المستخدم البوت).", show_alert=not ok)
    text, markup = await _order_view(core, oid)
    await reply(cb, text, markup)


@router.callback_query(F.data.startswith("a:om:"))
async def order_mark(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "orders"):
        return
    oid = int(cb.data.split(":")[2])
    try:
        await orders.mark_delivered(core, actor(cb.from_user.id), oid, "تأكيد يدوي من تيليجرام")
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await cb.answer("تم")
    text, markup = await _order_view(core, oid)
    await reply(cb, text, markup)


@router.callback_query(F.data.startswith("a:orf:"))
async def order_refund_ask(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "wallet"):
        return
    await state.set_state(A.refund_reason)
    await state.update_data(order_id=int(cb.data.split(":")[2]))
    await cb.message.answer("↩️ اكتب سبب الاسترداد (سيظهر للزبون):")
    await cb.answer()


@router.message(A.refund_reason, F.text)
async def order_refund_reason(message: Message, state: FSMContext):
    await state.update_data(reason=message.text.strip())
    data = await state.get_data()
    await message.answer("هل تعيد الحساب إلى المخزون ليُباع مجدداً؟\n"
                         "(اختر «لا» إذا كان من المحتمل أن الزبون استلم البيانات)",
                         reply_markup=kb([btn("نعم، أعده للمخزون", f"a:orx:{data['order_id']}:1"),
                                          btn("لا، أوقفه", f"a:orx:{data['order_id']}:0")]))


@router.callback_query(A.refund_reason, F.data.startswith("a:orx:"))
async def order_refund_do(cb: CallbackQuery, state: FSMContext, core: Core):
    _, _, oid, restock = cb.data.split(":")
    data = await state.get_data()
    try:
        o = await orders.refund(core, actor(cb.from_user.id), int(oid), data.get("reason", ""), restock == "1")
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        return
    await state.clear()
    await cb.answer("تم الاسترداد")
    await reply(cb, f"✅ تم إلغاء {o['ref']} واسترداد {fmt(o['price'])} USDT للزبون.", kb(BACK))


# ================================================================== users
@router.callback_query(F.data == "a:usearch")
async def user_search(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "users"):
        return
    await state.set_state(A.user_search)
    await cb.message.answer("👤 أرسل Telegram User ID للمستخدم (أرقام فقط) أو اسم المستخدم:")
    await cb.answer()


async def _user_view(core: Core, user_id: int):
    u = await wallet.get_user(core, user_id)
    if not u:
        return None, None
    stats_ = await core.pool.fetchrow(
        "SELECT COUNT(*) FILTER (WHERE status='completed') AS done, COALESCE(SUM(price) FILTER (WHERE status='completed'),0) AS spent "
        "FROM orders WHERE user_id=$1", user_id)
    dep = await core.pool.fetchval("SELECT COALESCE(SUM(credited_amount),0) FROM deposits WHERE user_id=$1 AND status='approved'",
                                   user_id)
    text = (f"👤 <b>{e(u['first_name'] or '')}</b> {('@' + e(u['username'])) if u['username'] else ''}\n"
            f"ID: <code>{u['id']}</code>\nالرصيد: <b>{fmt(u['balance'])} USDT</b>\n"
            f"المشتريات: {stats_['done']} ({fmt(stats_['spent'])} USDT)\nإجمالي الشحن: {fmt(dep)} USDT\n"
            f"الانضمام: {dt(u['created_at'])}\nآخر نشاط: {dt(u['last_seen_at'])}"
            + ("\n⛔️ <b>محظور</b>" if u["is_banned"] else ""))
    markup = kb([btn("➕ إضافة رصيد", f"a:uc:{user_id}:1"), btn("➖ خصم رصيد", f"a:uc:{user_id}:-1")],
                [btn("📜 الحركات المالية", f"a:uh:{user_id}"), btn("🧾 طلباته", f"a:uo:{user_id}")],
                [btn("✅ فك الحظر" if u["is_banned"] else "⛔️ حظر", f"a:ub:{user_id}")], BACK)
    return text, markup


@router.message(A.user_search, F.text)
async def user_search_do(message: Message, state: FSMContext, core: Core):
    q = message.text.strip()
    found = await wallet.search_users(core, q, limit=10)
    await state.clear()
    if not found:
        await message.answer("لا يوجد مستخدم مطابق.", reply_markup=kb(BACK))
        return
    if len(found) == 1:
        text, markup = await _user_view(core, found[0]["id"])
        await message.answer(text, reply_markup=markup)
        return
    await message.answer("نتائج البحث:", reply_markup=kb(*[[btn(
        f"{u['id']} @{u['username'] or '-'} • {fmt(u['balance'])}$", f"a:u:{u['id']}")] for u in found], BACK))


@router.callback_query(F.data.startswith("a:u:"))
async def user_cb(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "users"):
        return
    text, markup = await _user_view(core, int(cb.data.split(":")[2]))
    await reply(cb, text or "غير موجود", markup)
    await cb.answer()


@router.callback_query(F.data.startswith("a:ub:"))
async def user_ban(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "users"):
        return
    uid = int(cb.data.split(":")[2])
    u = await wallet.get_user(core, uid)
    await wallet.set_banned(core, actor(cb.from_user.id), uid, not u["is_banned"])
    await cb.answer("تم")
    text, markup = await _user_view(core, uid)
    await reply(cb, text, markup)


@router.callback_query(F.data.startswith("a:uh:"))
async def user_history(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "users"):
        return
    uid = int(cb.data.split(":")[2])
    txs = await wallet.history(core, uid, limit=20)
    lines = [f"📜 <b>حركات</b> <code>{uid}</code>", ""] + ([tx_line(t) + (f"\n   {e(t['reason'])}" if t["reason"] else "")
                                                           for t in txs] or ["لا توجد حركات."])
    await reply(cb, "\n".join(lines)[:4000], kb([btn("↩️ المستخدم", f"a:u:{uid}")]))
    await cb.answer()


@router.callback_query(F.data.startswith("a:uo:"))
async def user_orders(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "users"):
        return
    uid = int(cb.data.split(":")[2])
    items = await orders.list_orders(core, user_id=uid, limit=15)
    rows = [[btn(order_line(o)[:55], f"a:o:{o['id']}")] for o in items]
    rows.append([btn("↩️ المستخدم", f"a:u:{uid}")])
    await reply(cb, f"🧾 طلبات <code>{uid}</code>" + ("" if items else "\nلا توجد."), kb(*rows))
    await cb.answer()


@router.callback_query(F.data.startswith("a:uc:"))
async def user_adjust_ask(cb: CallbackQuery, state: FSMContext, role: str):
    if not await need(cb, role, "wallet"):
        return
    _, _, uid, sign = cb.data.split(":")
    await state.set_state(A.user_amount)
    await state.update_data(user_id=int(uid), sign=int(sign))
    await cb.message.answer(f"{'➕ إضافة' if sign == '1' else '➖ خصم'} رصيد — أرسل المبلغ (USDT):")
    await cb.answer()


@router.message(A.user_amount, F.text)
async def user_adjust_amount(message: Message, state: FSMContext):
    try:
        from ..core import money
        amt = money(message.text)
        if amt <= 0:
            raise StoreError("bad_amount", "المبلغ يجب أن يكون أكبر من صفر.")
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.update_data(amount=str(amt))
    await state.set_state(A.user_reason)
    await message.answer("📝 اكتب سبب العملية (إلزامي، يُحفظ في السجل ويظهر للزبون):")


@router.message(A.user_reason, F.text)
async def user_adjust_reason(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    amount = data["amount"] if data["sign"] > 0 else "-" + data["amount"]
    try:
        tx = await wallet.admin_adjust(core, actor(message.from_user.id), data["user_id"], amount, message.text,
                                       idempotency_key=f"adj:tg:{message.chat.id}:{message.message_id}")
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        if ex.code != "reason_required":
            await state.clear()
        return
    await state.clear()
    text, markup = await _user_view(core, data["user_id"])
    await message.answer(f"✅ تمت العملية <code>{tx['ref']}</code>\n\n" + text, reply_markup=markup)


# =============================================================== settings
@router.callback_query(F.data == "a:set")
async def settings_cb(cb: CallbackQuery, state: FSMContext, core: Core, role: str):
    if not await need(cb, role, "settings"):
        return
    await state.clear()
    s = await system.get_settings(core, fresh=True)
    lines = ["⚙️ <b>الإعدادات</b>", ""]
    rows = []
    for key, (label, kind) in system.SETTINGS_SCHEMA.items():
        val = s.get(key, "")
        if kind == "bool":
            shown = "✅ نعم" if val == "true" else "❌ لا"
            rows.append([btn(f"{label}: {shown}", f"a:sb:{key}")])
        else:
            short = (val[:40] + "…") if len(val) > 40 else val
            lines.append(f"• <b>{label}</b>: {e(short) or '—'}")
            rows.append([btn(f"✏️ {label}", f"a:se:{key}")])
    rows.append(BACK)
    await reply(cb, "\n".join(lines), kb(*rows))
    await cb.answer()


@router.callback_query(F.data.startswith("a:sb:"))
async def setting_toggle(cb: CallbackQuery, state: FSMContext, core: Core, role: str):
    if not await need(cb, role, "settings"):
        return
    key = cb.data.split(":", 2)[2]
    cur = await system.setting(core, key, "false")
    await system.update_settings(core, actor(cb.from_user.id), {key: "false" if cur == "true" else "true"})
    await settings_cb(cb, state, core, role)


@router.callback_query(F.data.startswith("a:se:"))
async def setting_edit(cb: CallbackQuery, state: FSMContext, core: Core, role: str):
    if not await need(cb, role, "settings"):
        return
    key = cb.data.split(":", 2)[2]
    await state.set_state(A.setting_value)
    await state.update_data(key=key)
    cur = await system.setting(core, key)
    await cb.message.answer(f"✏️ <b>{system.SETTINGS_SCHEMA[key][0]}</b>\nالقيمة الحالية:\n<code>{e(cur)}</code>\n\n"
                            "أرسل القيمة الجديدة، أو /cancel للإلغاء.")
    await cb.answer()


@router.message(A.setting_value, F.text)
async def setting_save(message: Message, state: FSMContext, core: Core):
    data = await state.get_data()
    try:
        await system.update_settings(core, actor(message.from_user.id), {data["key"]: message.text})
    except StoreError as ex:
        await message.answer(f"⚠️ {e(ex.message)}")
        return
    await state.clear()
    await message.answer("✅ تم الحفظ.", reply_markup=kb([btn("⚙️ الإعدادات", "a:set")]))


# ============================================================ audit/backup
@router.callback_query(F.data == "a:audit")
async def audit_cb(cb: CallbackQuery, core: Core, role: str):
    items = await system.list_audit(core, limit=20)
    lines = ["📜 <b>سجل النشاط (آخر 20)</b>", ""] + [
        f"• {dt(a['created_at'])} <b>{e(a['actor'])}</b> — {e(a['action'])}"
        + (f" #{e(a['entity_id'])}" if a["entity_id"] else "") for a in items]
    await reply(cb, "\n".join(lines)[:4000], kb(BACK))
    await cb.answer()


@router.callback_query(F.data == "a:backup")
async def backup_cb(cb: CallbackQuery, core: Core, role: str):
    if not await need(cb, role, "backup"):
        return
    await cb.answer("⏳ جاري إنشاء النسخة…")
    try:
        path = await backup.make_backup(core)
    except StoreError as ex:
        await cb.message.answer(f"⚠️ {e(ex.message)}")
        return
    await cb.message.answer_document(FSInputFile(path), caption=f"🗄 نسخة احتياطية: {path.name}\n"
                                     "احتفظ بها مع مفتاح ENCRYPTION_KEY لاستعادة كلمات المرور.")
    async with core.pool.acquire() as conn:
        await system.audit(conn, actor(cb.from_user.id), "backup.create", "backup", path.name)
