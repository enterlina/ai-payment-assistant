"""Tool implementations and registry exposed to the agent."""

from __future__ import annotations

import os
from datetime import date, timedelta

from agent.reliability import read_with_retry, write_with_check
from support.data import MONTHS, get_order, search_regulations

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8010")
CALENDAR_URL = os.getenv("CALENDAR_URL", "https://isdayoff.ru")


def _partner_headers() -> dict:
    return {"X-Api-Key": os.getenv("PARTNER_API_KEY", "")}


def get_payment_status(order_id: str) -> dict:
    result = read_with_retry(
        f"{GATEWAY_URL}/payment_status",
        {"order_id": str(order_id)},
        _partner_headers(),
    )
    return result or {"error": "Платёжный партнёр временно недоступен."}


def _five_day_deadline(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def business_days_after(start_date: str, days: int) -> dict:
    start = date.fromisoformat(start_date)
    current = start
    remaining = days
    calendar_failed = False
    while remaining:
        current += timedelta(days=1)
        if current.weekday() >= 5:
            continue
        result = read_with_retry(f"{CALENDAR_URL}/{current:%Y%m%d}", {}, {})
        if result is None:
            calendar_failed = True
            current = _five_day_deadline(start, days)
            break
        # isdayoff can return a JSON scalar (0/1) or a textual scalar.
        try:
            is_day_off = int(result) == 1
        except (TypeError, ValueError):
            calendar_failed = True
            current = _five_day_deadline(start, days)
            break
        if not is_day_off:
            remaining -= 1

    result = {
        "date": current.isoformat(),
        "text": f"{current.day} {MONTHS[current.month - 1]} {current.year}",
    }
    if calendar_failed:
        result["note"] = "праздники не учтены"
    return result


def create_refund(order_id: str, amount: int) -> dict:
    request_id = f"refund-{order_id}"
    result = write_with_check(
        f"{GATEWAY_URL}/refund",
        {"order_id": str(order_id), "amount": amount},
        request_id,
        _partner_headers(),
    )
    return result or {
        "error": "Не удалось подтвердить результат возврата; передайте оператору.",
        "order_id": str(order_id),
    }


def finish(answer: str) -> dict:
    return {"answer": answer}


TOOL_FUNCTIONS = {
    "search_regulations": search_regulations,
    "get_order": get_order,
    "get_payment_status": get_payment_status,
    "business_days_after": business_days_after,
    "create_refund": create_refund,
    "finish": finish,
}
