"""Conversational sales agent (Claude via the Anthropic Messages API).

The model only *talks*. Everything factual comes from tools that read the database, and every action that
matters (creating an order, prices, reservations, payments, delivery) is executed by the system, never by the model.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import aiohttp

from ..core import Core, StoreError, fmt
from . import customers as cust_svc
from . import farms as farms_svc
from . import orders as orders_svc
from . import payments as pay_svc
from .system import get_settings, raise_alert

log = logging.getLogger(__name__)
API_URL = "https://api.anthropic.com/v1/messages"
MAX_TOOL_ROUNDS = 6
HISTORY_LIMIT = 30

TOOLS = [
    {"name": "search_farms",
     "description": "Search farms that are IN STOCK right now. Returns offers (identical farms grouped) with offer_code, "
                    "name, level (lvl), barn, silo, tools, price, currency, available count. Call this before talking about "
                    "any farm, price, level or availability. Empty result = nothing matches.",
     "input_schema": {"type": "object", "properties": {
         "min_level": {"type": "integer"}, "max_level": {"type": "integer"},
         "min_price": {"type": "number"}, "max_price": {"type": "number"},
         "currency": {"type": "string"}, "keyword": {"type": "string"}}}},
    {"name": "stock_overview",
     "description": "Overall stock: how many farms are available and the level/price ranges. Use for general questions.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "prepare_order",
     "description": "Prepare an order for an offer the customer clearly wants. The SYSTEM then shows the customer an "
                    "official summary with the final price and a confirm button. Nothing is reserved until they confirm. "
                    "Only call when the customer has chosen a specific offer and quantity.",
     "input_schema": {"type": "object", "required": ["offer_code", "quantity"], "properties": {
         "offer_code": {"type": "string", "description": "offer_code from search_farms"},
         "quantity": {"type": "integer", "minimum": 1}}}},
    {"name": "my_orders",
     "description": "The customer's recent orders with their real current status, totals and reasons.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "cancel_order",
     "description": "Cancel one of the customer's orders that is not paid yet (only if the customer explicitly asks).",
     "input_schema": {"type": "object", "required": ["order_ref"], "properties": {"order_ref": {"type": "string"}}}},
    {"name": "payment_methods",
     "description": "Active payment methods (name, kind, currency). Payment details are shown by the system after confirming an order.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "handoff_to_human",
     "description": "Transfer the conversation to the store staff. Use when you cannot answer from the tools and store "
                    "information, when the customer asks for a human, complains, reports a problem with a delivered farm, "
                    "asks for a discount/price change, or anything outside your rules.",
     "input_schema": {"type": "object", "required": ["reason"], "properties": {"reason": {"type": "string"}}}},
]


@dataclass
class AgentResult:
    text: str = ""
    order: dict | None = None          # order summary the system must show with a confirm button
    handoff: str | None = None         # reason, if the chat was transferred to staff
    tool_calls: list[str] = field(default_factory=list)


def _system_prompt(s: dict, customer: dict) -> str:
    store = s.get("store_name") or "HD农场"
    return f"""You are the sales assistant of "{store}", a Telegram store that sells Hay Day game farms. Each farm is delivered as a Token ID + password.

LANGUAGE: Always reply in the customer's language and dialect (Arabic incl. Iraqi dialect, English, or any other language). Understand slang and informal writing.

HARD RULES (never break them):
1. Never invent or estimate farms, levels, barn/silo/tools numbers, prices, currencies, stock, order statuses or payment details. Use ONLY tool results and the store information below. If a tool returns nothing, say so honestly.
2. You cannot change prices, give discounts, reserve, confirm payments or deliver. The system does those. If asked, explain politely or hand off to staff.
3. Never ask for or reveal Token IDs/passwords. They are delivered automatically by the system only after the payment is verified by staff.
4. To sell: search_farms → present the matching offers clearly (level, barn, silo, tools, price + currency, available) → when the customer picks one and a quantity, call prepare_order. Then tell them to review the official summary and press the confirm button. Do not restate a total different from the tool result.
5. After confirming an order the system shows the payment methods and instructions; payment is confirmed only after staff verify it.
6. For order status questions call my_orders and report the real status.
7. If you are not sure, or the request is outside these rules, call handoff_to_human.
8. Do not use emojis. Keep replies short and clear. Plain text only (no markdown tables).

STORE INFORMATION (official — you may quote it):
- About: {s.get('store_info', '')}
- Warranty: {s.get('warranty_policy', '')}
- Delivery: {s.get('delivery_policy', '')}
- Payment: {s.get('payment_policy', '')}
- Extra FAQ: {s.get('extra_faq', '') or '-'}

STYLE NOTES FROM THE OWNER: {s.get('ai_instructions', '')}

Customer: {customer.get('first_name') or ''} (Telegram id {customer['id']}).
"""


def _to_api_messages(hist: list[dict]) -> list[dict]:
    msgs: list[dict] = []
    for m in hist:
        if m["role"] == "user":
            role, text = "user", m["content"]
        elif m["role"] == "assistant":
            role, text = "assistant", m["content"]
        elif m["role"] == "admin":
            role, text = "assistant", f"[Store staff wrote]: {m['content']}"
        else:
            role, text = "assistant", f"[System notice]: {m['content']}"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n\n" + text
        else:
            msgs.append({"role": role, "content": text})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


async def _run_tool(core: Core, customer: dict, name: str, args: dict, res: AgentResult) -> dict:
    cid = customer["id"]
    lang = customer.get("lang") or "ar"
    try:
        if name == "search_farms":
            offers = await farms_svc.search_offers(
                core, min_level=args.get("min_level"), max_level=args.get("max_level"), min_price=args.get("min_price"),
                max_price=args.get("max_price"), currency=args.get("currency"), query=args.get("keyword"), limit=12)
            return {"offers": [{k: o[k] for k in ("offer_code", "name", "lvl", "barn", "silo", "tools", "price",
                                                   "currency", "available", "description")} for o in offers]}
        if name == "stock_overview":
            return await farms_svc.stock_summary(core)
        if name == "prepare_order":
            o = await orders_svc.prepare(core, cid, str(args.get("offer_code", "")), int(args.get("quantity", 1)))
            res.order = o
            return {"result": "official summary with a confirm button will be shown to the customer right after your reply",
                    "order_ref": o["ref"], "quantity": o["quantity"], "unit_price": str(o["unit_price"]),
                    "total": str(o["total"]), "currency": o["currency"]}
        if name == "my_orders":
            out = []
            for o in await orders_svc.customer_orders(core, cid, 8):
                out.append({"ref": o["ref"], "status": o["status"], "status_text": orders_svc.status_text(o["status"], lang),
                            "level": o["offer"]["lvl"], "quantity": o["quantity"], "total": str(o["total"]),
                            "currency": o["currency"], "reason": o["reason"],
                            "reserved_until": o["reserved_until"].isoformat() if o["reserved_until"] else None})
            return {"orders": out}
        if name == "cancel_order":
            o = await orders_svc.cancel_by_customer(core, cid, args.get("order_ref", ""))
            return {"cancelled": o["ref"]}
        if name == "payment_methods":
            return {"methods": [{"name": m["name"], "kind": m["kind"], "currency": m["currency"]}
                                for m in await pay_svc.list_methods(core, active_only=True)]}
        if name == "handoff_to_human":
            res.handoff = str(args.get("reason", ""))[:300] or "customer request"
            return {"result": "conversation transferred to staff; tell the customer a staff member will reply soon"}
    except StoreError as e:
        return {"error": e.code, "message": e.message, **{k: _jsonable(v) for k, v in (e.params or {}).items()}}
    return {"error": "unknown_tool"}


async def _call_api(core: Core, payload: dict) -> dict:
    headers = {"x-api-key": core.config.anthropic_api_key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    if core.config.anthropic_workspace_id:
        headers["anthropic-workspace-id"] = core.config.anthropic_workspace_id
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(API_URL, headers=headers, data=json.dumps(payload)) as r:
            data = await r.json(content_type=None)
            if r.status != 200:
                raise RuntimeError(f"AI API {r.status}: {(data.get('error') or {}).get('message', data)}")
            return data


# The bot replaces this in tests with a fake model.
call_api = _call_api


def enabled(core: Core) -> bool:
    return bool(core.config.anthropic_api_key)


async def respond(core: Core, customer: dict) -> AgentResult:
    """Run the agent on the customer's conversation (the newest user message is already logged)."""
    s = await get_settings(core)
    hist = await cust_svc.history(core, customer["id"], HISTORY_LIMIT)
    messages = _to_api_messages(hist)
    res = AgentResult()
    if not messages:
        return res
    for _ in range(MAX_TOOL_ROUNDS):
        data = await call_api(core, {"model": core.config.ai_model, "max_tokens": 800,
                                     "system": _system_prompt(s, customer), "tools": TOOLS, "messages": messages})
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        uses = [b for b in blocks if b.get("type") == "tool_use"]
        if not uses:
            res.text = text
            return res
        messages.append({"role": "assistant", "content": blocks})
        results = []
        for u in uses:
            res.tool_calls.append(u["name"])
            out = await _run_tool(core, customer, u["name"], u.get("input") or {}, res)
            results.append({"type": "tool_result", "tool_use_id": u["id"], "content": json.dumps(_jsonable(out), ensure_ascii=False)})
        messages.append({"role": "user", "content": results})
        if res.handoff and text:
            res.text = text
    res.text = res.text or ""
    return res


async def safe_respond(core: Core, customer: dict) -> AgentResult:
    try:
        return await respond(core, customer)
    except Exception as e:  # network/API errors must never break the chat
        log.exception("AI failed")
        await raise_alert(core, "error", "ai_error", f"تعذر رد الذكاء الاصطناعي على العميل {customer['id']}: {str(e)[:200]}",
                          "customer", customer["id"], perm="chat")
        return AgentResult(handoff="ai_error")
