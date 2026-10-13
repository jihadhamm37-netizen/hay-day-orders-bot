"""Optional automatic verification of incoming Binance Pay transfers.

Uses the official signed endpoint GET /sapi/v1/pay/transactions with a READ-ONLY
API key of the receiving Binance account. When it is not configured, or when no
exact match is found, the deposit simply stays in manual review.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

import aiohttp

from ..core import Core

BASE_URL = "https://api.binance.com"


def enabled(core: Core) -> bool:
    return bool(core.config.binance_api_key and core.config.binance_api_secret)


async def fetch_transactions(core: Core, start_ms: int) -> list[dict]:
    params = {"startTime": start_ms, "limit": 100, "recvWindow": 10000,
              "timestamp": int(time.time() * 1000)}
    query = urlencode(params)
    sig = hmac.new(core.config.binance_api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}/sapi/v1/pay/transactions?{query}&signature={sig}"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers={"X-MBX-APIKEY": core.config.binance_api_key}) as r:
            data = await r.json(content_type=None)
            if r.status != 200 or not data.get("success", False):
                raise RuntimeError(f"Binance API {r.status}: {data.get('msg') or data.get('message')}")
            return data.get("data") or []


def match(txs: list[dict], txid: str, amount: Decimal, created_at: datetime,
          pay_id: str | None = None) -> tuple[bool, str]:
    txid = txid.strip()
    since_ms = int(created_at.timestamp() * 1000) - 10 * 60 * 1000
    for t in txs:
        tid = str(t.get("transactionId", ""))
        if tid != txid and not tid.endswith(txid):
            continue
        if t.get("currency") != "USDT":
            return False, f"العملة {t.get('currency')} وليست USDT"
        got = Decimal(str(t.get("amount", "0")))
        if got <= 0:
            return False, "العملية صادرة وليست واردة"
        if int(t.get("transactionTime", 0)) < since_ms:
            return False, "العملية أقدم من طلب الشحن"
        recv = (t.get("receiverInfo") or {}).get("binanceId")
        if pay_id and recv and str(recv) != str(pay_id):
            return False, "المستلم ليس معرّف الدفع الخاص بالمتجر"
        if got != amount:
            return False, f"المبلغ المستلم {got} USDT لا يطابق المطلوب {amount} USDT"
        return True, "تطابق تام"
    return False, "لم يتم العثور على العملية بعد"


async def verify_incoming(core: Core, txid: str, amount: Decimal, created_at: datetime) -> tuple[bool, str]:
    from .system import setting
    start_ms = int(created_at.timestamp() * 1000) - 60 * 60 * 1000
    txs = await fetch_transactions(core, start_ms)
    return match(txs, txid, amount, created_at, await setting(core, "binance_pay_id"))
