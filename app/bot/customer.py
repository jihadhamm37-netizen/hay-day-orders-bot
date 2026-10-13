"""Customer side: buy farms (with quantity), wallet, top-up via Binance Pay, orders, support, language."""
from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message

from ..core import Core, StoreError, fmt
from ..i18n import err, t
from ..services import catalog, deposits, orders, system, wallet
from .ui import (MENU, btn, copy_btn, credentials_kb, credentials_text, deposit_line, dt, e, kb, lang_kb,
                 main_menu, menu_labels, order_line, tx_line, type_card, url_btn)

log = logging.getLogger(__name__)
router = Router(name="customer")

QUICK_AMOUNTS = ("5", "10", "20", "50", "100")
QUICK_QTY = (1, 2, 3, 5, 10)


class TopUp(StatesGroup):
    amount = State()
    photo = State()
    txid = State()


class Browse(StatesGroup):
    filter = State()
    qty = State()


# ---------------------------------------------------------------- helpers
async def menu_icons(core: Core) -> dict:
    if getattr(core, "icons_broken", False):
        return {}
    s = await system.get_settings(core)
    return {k: s.get(f"icon_{k}", "").strip() for k in MENU if s.get(f"icon_{k}", "").strip()}


async def send_menu(message: Message, core: Core, text: str, lang: str, is_admin: bool, **kw):
    """Send text with the main keyboard; falls back to emoji buttons if custom icons are refused."""
    icons = await menu_icons(core)
    try:
        return await message.answer(text, reply_markup=main_menu(lang, is_admin, icons), **kw)
    except TelegramBadRequest as ex:
        if not icons:
            raise
        log.warning("custom emoji icons refused (%s) — the bot owner needs Telegram Premium", ex)
        core.icons_broken = True
        return await message.answer(text, reply_markup=main_menu(lang, is_admin, None), **kw)


async def show(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None, photo: str | None = None):
    """Replace the current screen, switching between photo and text messages as needed."""
    msg = cb.message
    try:
        if photo:
            if msg.photo:
                await msg.edit_media(InputMediaPhoto(media=photo, caption=text), reply_markup=markup)
                return
        elif msg.text is not None:
            await msg.edit_text(text, reply_markup=markup)
            return
    except TelegramBadRequest as ex:
        if "message is not modified" in str(ex):
            return
    try:
        await msg.delete()
    except Exception:
        pass
    if photo:
        try:
            await msg.answer_photo(photo, caption=text, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass
    await msg.answer(text, reply_markup=markup)


# ------------------------------------------------------------------ start
@router.message(CommandStart())
async def start(message: Message, state: FSMContext, core: Core, role: str | None, lang: str, db_user: dict):
    await state.clear()
    s = await system.get_settings(core)
    text = s.get("welcome_text_en" if lang == "en" else "welcome_text") or s.get("welcome_text", "")
    await send_menu(message, core, e(text), lang, bool(role))
    if not db_user.get("lang_chosen"):
        await message.answer(t(lang, "choose_lang"), reply_markup=lang_kb())


@router.message(F.text.in_(menu_labels("lang")))
@router.message(Command("language", "lang"))
async def language(message: Message, state: FSMContext, lang: str):
    await state.clear()
    await message.answer(t(lang, "choose_lang"), reply_markup=lang_kb())


@router.callback_query(F.data.startswith("c:lang:"))
async def language_set(cb: CallbackQuery, core: Core, role: str | None):
    new = cb.data.split(":")[2]
    await wallet.set_lang(core, cb.from_user.id, new)
    await cb.answer()
    try:
        await cb.message.delete()
    except Exception:
        pass
    await send_menu(cb.message, core, t(new, "lang_set"), new, bool(role))


@router.message(Command("claim"))
async def claim(message: Message, state: FSMContext, core: Core, lang: str):
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
    await send_menu(message, core,
                    f"✅ تم ربط حسابك كمالك للمتجر (حساب اللوحة: <code>{e(a['username'])}</code>).\n"
                    "ظهر لك الآن زر «🛠 لوحة الإدارة»، وستصلك الإشعارات ورموز دخول اللوحة هنا.", lang, True)


@router.message(Command("cancel"))
@router.message(F.text.in_({"إلغاء", "الغاء", "cancel", "Cancel"}))
async def cancel_cmd(message: Message, state: FSMContext, core: Core, role: str | None, lang: str):
    await state.clear()
    await send_menu(message, core, t(lang, "cancelled"), lang, bool(role))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


# ---------------------------------------------------------------- browse
async def _types_view(core: Core, lang: str, filters: dict | None = None):
    types = await catalog.list_types(core, for_customers=True, filters=filters)
    if not types:
        return (t(lang, "no_match") if filters else t(lang, "no_types")), kb(
            [btn(t(lang, "btn_filter"), "c:filter")] if not filters else [btn(t(lang, "btn_all_types"), "c:types")])
    rows = []
    for tp in types:
        if tp["available"] > 0:
            price = fmt(tp["min_price"]) if tp["min_price"] == tp["max_price"] else f"{fmt(tp['min_price'])}+"
            label = f"{'🖼 ' if tp.get('photo_file_id') else ''}LVL {tp['lvl']} • {tp['barn']}/{tp['silo']} • {price} USDT ({tp['available']})"
            rows.append([btn(label, f"c:t:{tp['id']}", "success")])
        else:
            rows.append([btn(f"LVL {tp['lvl']} • {tp['barn']}/{tp['silo']} • {t(lang, 'out')}", f"c:t:{tp['id']}")])
    rows.append([btn(t(lang, "btn_filter"), "c:filter")])
    if filters:
        rows.append([btn(t(lang, "btn_all_types"), "c:types")])
    return t(lang, "types_head"), kb(*rows)


@router.message(F.text.in_(menu_labels("buy")))
async def buy_menu(message: Message, state: FSMContext, core: Core, lang: str):
    await state.clear()
    text, markup = await _types_view(core, lang)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "c:types")
async def types_cb(cb: CallbackQuery, state: FSMContext, core: Core, lang: str):
    await state.clear()
    text, markup = await _types_view(core, lang)
    await show(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data == "c:filter")
async def filter_ask(cb: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(Browse.filter)
    await cb.message.answer(t(lang, "filter_help"))
    await cb.answer()


@router.message(Browse.filter, F.text)
async def filter_apply(message: Message, state: FSMContext, core: Core, lang: str):
    flt = catalog.parse_filter(message.text)
    if not flt:
        await message.answer(t(lang, "filter_bad"))
        return
    await state.clear()
    text, markup = await _types_view(core, lang, flt)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("c:t:"))
async def type_detail(cb: CallbackQuery, state: FSMContext, core: Core, lang: str):
    await state.clear()
    type_id = int(cb.data.split(":")[2])
    tp = await catalog.get_type(core, type_id)
    if not tp or not tp["is_active"]:
        await cb.answer(t(lang, "type_unavailable"), show_alert=True)
        return
    tiers = await catalog.price_tiers(core, type_id)
    rows = [[btn(t(lang, "btn_buy_tier", price=fmt(x["price"]), n=x["available"]), f"c:bq:{type_id}:{x['price']}", "success")]
            for x in tiers]
    if not tiers:
        rows.append([btn(t(lang, "btn_out"), "noop")])
    rows.append([btn(t(lang, "back"), "c:types")])
    await show(cb, type_card(tp, tiers, lang), kb(*rows), photo=tp.get("photo_file_id"))
    await cb.answer()


# --------------------------------------------------------------- quantity
async def _max_qty(core: Core) -> int:
    try:
        return max(1, int(await system.setting(core, "max_quantity", "20")))
    except ValueError:
        return 20


@router.callback_query(F.data.startswith("c:bq:"))
async def qty_pick(cb: CallbackQuery, state: FSMContext, core: Core, lang: str, db_user: dict):
    _, _, type_id, price = cb.data.split(":")
    tp = await catalog.get_type(core, int(type_id))
    tiers = {str(x["price"]): x["available"] for x in await catalog.price_tiers(core, int(type_id))}
    available = tiers.get(price, 0)
    if not tp or not available:
        await cb.answer(t(lang, "btn_out"), show_alert=True)
        return
    limit = min(available, await _max_qty(core))
    p = Decimal(price)
    choices = [q for q in QUICK_QTY if q <= limit]
    rows, row = [], []
    for q in choices:
        row.append(btn(t(lang, "btn_qty", q=q, total=fmt(p * q)), f"c:bp:{type_id}:{price}:{q}",
                       "success" if p * q <= db_user["balance"] else None))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if limit > 1:
        rows.append([btn(t(lang, "btn_qty_other"), f"c:bo:{type_id}:{price}")])
    rows.append([btn(t(lang, "back"), f"c:t:{type_id}")])
    await show(cb, t(lang, "qty_ask", name=e(tp["name"]), price=fmt(p), n=available, balance=fmt(db_user["balance"])),
               kb(*rows), photo=tp.get("photo_file_id"))
    await cb.answer()


@router.callback_query(F.data.startswith("c:bo:"))
async def qty_other(cb: CallbackQuery, state: FSMContext, core: Core, lang: str):
    _, _, type_id, price = cb.data.split(":")
    await state.set_state(Browse.qty)
    await state.update_data(type_id=int(type_id), price=price)
    await cb.message.answer(t(lang, "qty_type", max=await _max_qty(core)))
    await cb.answer()


@router.message(Browse.qty, F.text)
async def qty_typed(message: Message, state: FSMContext, core: Core, lang: str, db_user: dict):
    data = await state.get_data()
    mx = await _max_qty(core)
    txt = message.text.strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if not txt.isdigit() or not (1 <= int(txt) <= mx):
        await message.answer(t(lang, "qty_bad", max=mx))
        return
    await state.clear()
    await _prepare_and_confirm(message, None, core, lang, db_user, data["type_id"], data["price"], int(txt))


@router.callback_query(F.data.startswith("c:bp:"))
async def buy_prepare(cb: CallbackQuery, state: FSMContext, core: Core, lang: str, db_user: dict):
    parts = cb.data.split(":")
    type_id, price = int(parts[2]), parts[3]
    qty = int(parts[4]) if len(parts) > 4 else 1
    await _prepare_and_confirm(cb.message, cb, core, lang, db_user, type_id, price, qty)
    await cb.answer()


async def _prepare_and_confirm(message: Message, cb: CallbackQuery | None, core: Core, lang: str, db_user: dict,
                               type_id: int, price: str, qty: int):
    async def out(text, markup):
        if cb:
            await show(cb, text, markup)
        else:
            await message.answer(text, reply_markup=markup)

    try:
        o = await orders.prepare(core, db_user["id"], type_id, price, qty)
    except StoreError as ex:
        rows = [[btn(t(lang, "btn_topup_inline"), "c:topup", "success")]] if ex.code == "insufficient_funds" else []
        rows.append([btn(t(lang, "back"), f"c:t:{type_id}")])
        await out(e(err(lang, ex)), kb(*rows))
        return
    snap = o["type_snapshot"]
    bal = Decimal(db_user["balance"])
    text = t(lang, "confirm", name=e(snap["name"]), lvl=snap["lvl"], barn=f"{snap['barn']:,}", silo=f"{snap['silo']:,}",
             qty=qty, price=fmt(o["price"]), total=fmt(o["total"]), balance=fmt(bal), after=fmt(bal - o["total"]),
             ref=o["batch_ref"], ttl=orders.PENDING_TTL_MIN)
    await out(text, kb([btn(t(lang, "btn_confirm", total=fmt(o["total"])), f"c:bc:{o['id']}", "success")],
                       [btn(t(lang, "btn_cancel"), f"c:bx:{o['id']}", "danger")]))


@router.callback_query(F.data.startswith("c:bc:"))
async def buy_confirm(cb: CallbackQuery, core: Core, lang: str):
    order_id = int(cb.data.split(":")[2])
    await cb.answer(t(lang, "processing_short"))
    # remove the buttons first so extra taps cannot reach this handler again
    await show(cb, t(lang, "processing"))
    try:
        o = await orders.purchase(core, cb.from_user.id, order_id)
        batch = o["batch"]
    except StoreError as ex:
        if ex.code != "already":
            await show(cb, e(err(lang, ex)), kb([btn(t(lang, "btn_farms"), "c:types")]))
            return
        # a second tap on the same button: just show the real state of the (single) order
        o = await orders.get_order(core, order_id)
        if o["status"] not in ("completed", "needs_review"):
            await show(cb, t(lang, "order_state", ref=o["ref"], status=t(lang, "st_" + o["status"])),
                       kb([btn(t(lang, "btn_my_orders"), "c:orders")]))
            return
        batch = [o]
    ref = batch[0]["ref"].rsplit("-", 1)[0] if len(batch) > 1 else batch[0]["ref"]
    failed = [x for x in batch if x["status"] != "completed"]
    total = fmt(sum(x["price"] for x in batch))
    if not failed:
        await show(cb, t(lang, "bought", ref=ref, qty=len(batch), total=total))
    else:
        await show(cb, t(lang, "bought_partial", ref=ref, qty=len(batch), failed=len(failed)),
                   kb(*[[btn(f"{t(lang, 'btn_retry')} — {x['ref']}", f"c:or:{x['id']}")] for x in failed[:10]]))


@router.callback_query(F.data.startswith("c:bx:"))
async def buy_cancel(cb: CallbackQuery, core: Core, lang: str):
    order_id = int(cb.data.split(":")[2])
    await core.pool.execute(
        "UPDATE orders SET status='cancelled', failure_reason='ألغاه الزبون', updated_at=now() WHERE user_id=$2 "
        "AND status='pending' AND (id=$1 OR batch_id=(SELECT batch_id FROM orders WHERE id=$1))",
        order_id, cb.from_user.id)
    await show(cb, t(lang, "buy_cancelled"), kb([btn(t(lang, "btn_farms"), "c:types")]))
    await cb.answer()


# ---------------------------------------------------------------- wallet
async def _wallet_view(core: Core, user_id: int, lang: str):
    u = await wallet.get_user(core, user_id)
    txs = await wallet.history(core, user_id, limit=10)
    lines = [t(lang, "wallet", balance=fmt(u["balance"])), ""]
    lines += ([t(lang, "last_tx")] + [tx_line(x, lang) for x in txs]) if txs else [t(lang, "no_tx")]
    return "\n".join(lines), kb([btn(t(lang, "btn_topup_inline"), "c:topup", "success"),
                                 btn(t(lang, "btn_history"), "c:wh:0")])


@router.message(F.text.in_(menu_labels("wallet")))
async def wallet_menu(message: Message, state: FSMContext, core: Core, lang: str):
    await state.clear()
    text, markup = await _wallet_view(core, message.from_user.id, lang)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("c:wh:"))
async def wallet_history(cb: CallbackQuery, core: Core, lang: str):
    page = int(cb.data.split(":")[2])
    txs = await wallet.history(core, cb.from_user.id, limit=15, offset=page * 15)
    lines = [t(lang, "history_head", page=page + 1), ""] + ([tx_line(x, lang) for x in txs] or [t(lang, "no_tx")])
    nav = []
    if page > 0:
        nav.append(btn(t(lang, "prev"), f"c:wh:{page - 1}"))
    if len(txs) == 15:
        nav.append(btn(t(lang, "next"), f"c:wh:{page + 1}"))
    await show(cb, "\n".join(lines), kb(nav, [btn(t(lang, "btn_wallet_back"), "c:wallet")]))
    await cb.answer()


@router.callback_query(F.data == "c:wallet")
async def wallet_cb(cb: CallbackQuery, core: Core, lang: str):
    text, markup = await _wallet_view(core, cb.from_user.id, lang)
    await show(cb, text, markup)
    await cb.answer()


# ---------------------------------------------------------------- top-up
async def _topup_start(message: Message, state: FSMContext, core: Core, lang: str):
    await state.clear()
    mn = await system.setting(core, "min_deposit", "1")
    mx = await system.setting(core, "max_deposit", "5000")
    await state.set_state(TopUp.amount)
    await message.answer(
        t(lang, "topup_start", min=mn, max=mx),
        reply_markup=kb([btn(f"{a} USDT", f"c:ta:{a}", "success") for a in QUICK_AMOUNTS[:3]],
                        [btn(f"{a} USDT", f"c:ta:{a}", "success") for a in QUICK_AMOUNTS[3:]],
                        [btn(t(lang, "btn_cancel"), "c:tcx", "danger")]))


@router.message(F.text.in_(menu_labels("topup")))
async def topup_menu(message: Message, state: FSMContext, core: Core, lang: str):
    await _topup_start(message, state, core, lang)


@router.callback_query(F.data == "c:topup")
async def topup_cb(cb: CallbackQuery, state: FSMContext, core: Core, lang: str):
    await _topup_start(cb.message, state, core, lang)
    await cb.answer()


async def _create_deposit(message: Message, state: FSMContext, core: Core, user_id: int, amount: str, lang: str):
    try:
        d = await deposits.create(core, user_id, amount)
    except StoreError as ex:
        if ex.code == "bad_amount" and not ex.params:
            ex.params = {"min": await system.setting(core, "min_deposit", "1"),
                         "max": await system.setting(core, "max_deposit", "5000")}
        await message.answer(e(err(lang, ex)))
        return
    await state.set_state(TopUp.photo)
    await state.update_data(deposit_id=d["id"])
    s = await system.get_settings(core)
    instructions = (s.get("payment_instructions_en") if lang == "en" else None) or s.get("payment_instructions", "")
    pay_id = d["pay_id_shown"]
    await message.answer(
        t(lang, "topup_details", ref=d["ref"], amount=fmt(d["amount"]), pay_id=e(pay_id), instructions=e(instructions)),
        reply_markup=kb([b for b in (copy_btn(t(lang, "copy_pay_id"), pay_id),
                                     copy_btn(t(lang, "copy_amount"), str(d["amount"]))) if b],
                        [btn(t(lang, "topup_cancel_btn"), "c:tcx", "danger")]))


@router.callback_query(TopUp.amount, F.data.startswith("c:ta:"))
async def topup_quick(cb: CallbackQuery, state: FSMContext, core: Core, lang: str):
    await cb.answer()
    await _create_deposit(cb.message, state, core, cb.from_user.id, cb.data.split(":")[2], lang)


@router.message(TopUp.amount, F.text)
async def topup_amount(message: Message, state: FSMContext, core: Core, lang: str):
    amount = message.text.replace("USDT", "").replace("$", "").strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789."))
    await _create_deposit(message, state, core, message.from_user.id, amount, lang)


@router.callback_query(F.data == "c:tcx")
async def topup_cancel(cb: CallbackQuery, state: FSMContext, core: Core, lang: str):
    data = await state.get_data()
    if data.get("deposit_id"):
        try:
            await deposits.cancel(core, cb.from_user.id, data["deposit_id"])
        except StoreError:
            pass
    await state.clear()
    await cb.message.answer(t(lang, "topup_cancelled"))
    await cb.answer()


@router.message(TopUp.photo, F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def topup_photo(message: Message, state: FSMContext, core: Core, lang: str):
    data = await state.get_data()
    if message.photo:
        file_id, unique = message.photo[-1].file_id, message.photo[-1].file_unique_id
    else:
        file_id, unique = message.document.file_id, message.document.file_unique_id
    try:
        await deposits.attach_photo(core, message.from_user.id, data["deposit_id"], file_id, unique)
    except StoreError as ex:
        await message.answer(e(err(lang, ex)))
        if ex.code == "bad_state":
            await state.clear()
        return
    if await system.setting_bool(core, "require_txid"):
        await state.set_state(TopUp.txid)
        await message.answer(t(lang, "photo_ok_txid"))
        return
    await _submit(message, state, core, lang)


@router.message(TopUp.photo)
async def topup_photo_wrong(message: Message, lang: str):
    await message.answer(t(lang, "photo_wrong"))


@router.message(TopUp.txid, F.text)
async def topup_txid(message: Message, state: FSMContext, core: Core, lang: str):
    data = await state.get_data()
    try:
        await deposits.attach_txid(core, message.from_user.id, data["deposit_id"], message.text)
    except StoreError as ex:
        await message.answer(e(err(lang, ex)))
        if ex.code == "bad_state":
            await state.clear()
        return
    await _submit(message, state, core, lang)


async def _submit(message: Message, state: FSMContext, core: Core, lang: str):
    data = await state.get_data()
    try:
        d = await deposits.submit(core, message.from_user.id, data["deposit_id"])
    except StoreError as ex:
        await message.answer(e(err(lang, ex)))
        return
    await state.clear()
    if d["status"] == "approved":
        return  # auto-verified; the approval notification was already sent
    await message.answer(t(lang, "topup_submitted", ref=d["ref"]))


# ---------------------------------------------------------------- orders
async def _orders_view(core: Core, user_id: int, lang: str):
    ords = await orders.list_orders(core, user_id=user_id, limit=15)
    deps = await deposits.list_deposits(core, user_id=user_id, limit=5)
    lines = [t(lang, "orders_head"), ""]
    rows = [[btn(order_line(o, lang)[:60], f"c:o:{o['id']}")] for o in ords]
    if not ords:
        lines.append(t(lang, "no_orders"))
    if deps:
        lines += ["", t(lang, "last_deposits")] + [f"{deposit_line(d, lang)}\n   <code>{d['ref']}</code>" for d in deps]
    return "\n".join(lines), kb(*rows)


@router.message(F.text.in_(menu_labels("orders")))
async def orders_menu(message: Message, state: FSMContext, core: Core, lang: str):
    await state.clear()
    text, markup = await _orders_view(core, message.from_user.id, lang)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "c:orders")
async def orders_cb(cb: CallbackQuery, core: Core, lang: str):
    text, markup = await _orders_view(core, cb.from_user.id, lang)
    await show(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.startswith("c:o:"))
async def order_detail(cb: CallbackQuery, core: Core, lang: str):
    o = await orders.get_order(core, int(cb.data.split(":")[2]))
    if not o or o["user_id"] != cb.from_user.id:
        await cb.answer(t(lang, "order_missing"), show_alert=True)
        return
    snap = o["type_snapshot"]
    text = t(lang, "order_card", ref=o["ref"], name=e(snap["name"]), lvl=snap["lvl"], barn=snap["barn"],
             silo=snap["silo"], price=fmt(o["price"]), status=t(lang, "st_" + o["status"]), date=dt(o["created_at"]))
    if o["status"] == "completed":
        text += "\n" + t(lang, "delivered_at", date=dt(o["delivered_at"]))
    if o["status"] in ("cancelled", "needs_review") and o["admin_note"]:
        text += "\n" + t(lang, "note", note=e(o["admin_note"]))
    rows = []
    if o["status"] == "completed":
        rows.append([btn(t(lang, "btn_show_creds"), f"c:oc:{o['id']}", "success")])
    if o["status"] == "needs_review" and (o["failure_reason"] or "").startswith("فشل التسليم"):
        rows.append([btn(t(lang, "btn_retry"), f"c:or:{o['id']}", "primary")])
    rows.append([btn(t(lang, "back"), "c:orders")])
    await show(cb, text, kb(*rows))
    await cb.answer()


@router.callback_query(F.data.startswith("c:oc:"))
async def order_credentials(cb: CallbackQuery, core: Core, lang: str):
    try:
        o, login, password = await orders.buyer_credentials(core, cb.from_user.id, int(cb.data.split(":")[2]))
    except StoreError as ex:
        await cb.answer(err(lang, ex), show_alert=True)
        return
    text, markup = credentials_text(o, login, password, lang), credentials_kb(login, password, lang)
    if o.get("photo"):
        try:
            await cb.message.answer_photo(o["photo"], caption=text, reply_markup=markup)
            await cb.answer()
            return
        except TelegramBadRequest:
            pass
    await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data.startswith("c:or:"))
async def order_retry(cb: CallbackQuery, core: Core, lang: str):
    order_id = int(cb.data.split(":")[2])
    try:
        ok = await orders.retry_delivery(core, order_id, user_id=cb.from_user.id, actor=f"tg:{cb.from_user.id}")
    except StoreError as ex:
        await cb.answer(err(lang, ex), show_alert=True)
        return
    await cb.answer(t(lang, "sent_ok") if ok else t(lang, "sent_fail"), show_alert=not ok)
    if ok:
        await show(cb, t(lang, "sent_ok_msg"))


# --------------------------------------------------------------- support
@router.message(F.text.in_(menu_labels("support")))
async def support(message: Message, state: FSMContext, core: Core, lang: str):
    await state.clear()
    s = await system.get_settings(core)
    text = (s.get("support_text_en") if lang == "en" else None) or s.get("support_text", "")
    rows = []
    if s.get("support_username"):
        rows.append([url_btn(t(lang, "btn_contact"), f"https://t.me/{s['support_username']}")])
    await message.answer(t(lang, "support", text=e(text), uid=message.from_user.id),
                         reply_markup=kb(*rows) if rows else None)


@router.message(StateFilter(None))
async def fallback(message: Message, core: Core, role: str | None, lang: str):
    await send_menu(message, core, t(lang, "use_menu"), lang, bool(role))
