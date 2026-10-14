"""Staff actions from Telegram notifications: approve / reject payment proofs."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..core import Core, StoreError
from ..services import admins
from ..services import payments as pay_svc
from .messenger import btn, e, kb

router = Router(name="admin_tg")
QUICK_REJECT = ["لم يصل المبلغ", "المبلغ لا يطابق الطلب", "الإثبات غير واضح أو غير صحيح", "رقم العملية غير صحيح"]


class R(StatesGroup):
    reason = State()


def actor(uid: int) -> str:
    return f"tg:{uid}"


async def _edit(cb: CallbackQuery, suffix: str):
    msg = cb.message
    try:
        if msg.photo:
            await msg.edit_caption(caption=((msg.caption or "") + "\n\n" + suffix)[:1024], reply_markup=None)
        else:
            await msg.edit_text((msg.html_text or "") + "\n\n" + suffix, reply_markup=None)
    except Exception:
        await msg.answer(suffix)


@router.callback_query(F.data.startswith("a:pa:"))
async def approve(cb: CallbackQuery, core: Core, role: str | None):
    if not admins.has_perm(role, "payments"):
        await cb.answer("غير مصرح.", show_alert=True)
        return
    try:
        p = await pay_svc.approve(core, actor(cb.from_user.id), int(cb.data.split(":")[2]))
    except StoreError as ex:
        await cb.answer(ex.message, show_alert=True)
        await _edit(cb, e(ex.message))
        return
    await cb.answer("تم قبول الدفع وجاري التسليم")
    await _edit(cb, f"تم القبول بواسطة {e(cb.from_user.full_name)} — {p['amount']} {p['currency']}")


@router.callback_query(F.data.startswith("a:pr:"))
async def reject_ask(cb: CallbackQuery, state: FSMContext, role: str | None):
    if not admins.has_perm(role, "payments"):
        await cb.answer("غير مصرح.", show_alert=True)
        return
    pid = int(cb.data.split(":")[2])
    await state.set_state(R.reason)
    await state.update_data(payment_id=pid)
    await cb.message.answer("اختر سبب الرفض أو اكتبه (يظهر للعميل، ويبقى الطلب محجوزاً ليرسل إثباتاً صحيحاً):",
                            reply_markup=kb(*[[btn(r, f"a:prq:{pid}:{i}")] for i, r in enumerate(QUICK_REJECT)]))
    await cb.answer()


async def _reject(target: Message, core: Core, uid: int, pid: int, reason: str, state: FSMContext):
    try:
        await pay_svc.reject(core, actor(uid), pid, reason)
    except StoreError as ex:
        await target.answer(e(ex.message))
        return
    await state.clear()
    await target.answer(f"تم رفض الإثبات — السبب: {e(reason)}")


@router.callback_query(F.data.startswith("a:prq:"))
async def reject_quick(cb: CallbackQuery, state: FSMContext, core: Core, role: str | None):
    if not admins.has_perm(role, "payments"):
        await cb.answer("غير مصرح.", show_alert=True)
        return
    _, _, pid, i = cb.data.split(":")
    await cb.answer()
    await _reject(cb.message, core, cb.from_user.id, int(pid), QUICK_REJECT[int(i)], state)


@router.message(R.reason, F.text)
async def reject_text(message: Message, state: FSMContext, core: Core, role: str | None):
    if not role:
        await state.clear()
        return
    data = await state.get_data()
    await _reject(message, core, message.from_user.id, data["payment_id"], message.text, state)
