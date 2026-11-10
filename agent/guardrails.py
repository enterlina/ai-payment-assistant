"""Input, action, and output guardrails for the operations assistant."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from support.data import ORDERS


@dataclass
class PolicyContext:
    """Trusted state supplied by the application, never by customer text."""

    confirmed_refunds: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.confirmed_refunds = {str(value) for value in self.confirmed_refunds}


INJECTION_PATTERNS = (
    r"игнорир\w*\s+(?:все\s+)?(?:правил|регламент|инструкц)",
    r"системн\w*\s+(?:сообщен|промпт|инструкц)",
    r"подтвержден\w*\s+не\s+треб",
    r"без\s+подтвержден\w*\s+оператор",
    r"вызов\w*\s+create_refund",
    r"нов\w*\s+регламент",
    r"ключ\w*\s+доступ",
    r"вывед\w*.*(?:промпт|инструкц|ключ)",
)

SCOPE_WORDS = (
    "заказ", "платеж", "платёж", "возврат", "рассроч", "списан",
    "комис", "регламент", "чарджб", "магазин", "карта", "выписк",
    "просроч", "отмен", "перенос", "срок", "деньг",
)


def check_input(text: str) -> dict:
    """Reject prompt injection and clearly unrelated requests."""
    if not isinstance(text, str) or not text.strip():
        return {"decision": "block", "reason": "Пустое обращение."}
    lowered = text.lower().replace("ё", "е")
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lowered, flags=re.DOTALL):
            return {
                "decision": "block",
                "reason": "Обнаружена недоверенная инструкция в тексте обращения.",
            }
    if not any(word.replace("ё", "е") in lowered for word in SCOPE_WORDS):
        return {
            "decision": "block",
            "reason": "Обращение вне компетенции операционного ассистента.",
        }
    return {"decision": "allow", "reason": "Обращение допустимо."}


TOOL_ARGUMENTS = {
    "search_regulations": {"query": str},
    "get_order": {"order_id": str},
    "get_payment_status": {"order_id": str},
    "business_days_after": {"start_date": str, "days": int},
    "create_refund": {"order_id": str, "amount": int},
    "finish": {"answer": str},
}


def _deny(reason: str) -> dict:
    return {"decision": "deny", "reason": reason}


def validate_tool_call(name: str, arguments: dict,
                       context: PolicyContext) -> dict:
    """Validate allow-list, argument shape, order state, and refund policy."""
    required = TOOL_ARGUMENTS.get(name)
    if required is None:
        return _deny("Инструмент не разрешён.")
    if not isinstance(arguments, dict):
        return _deny("Аргументы инструмента должны быть объектом.")
    supplied = {key for key in arguments if key != "thought"}
    if supplied != set(required):
        return _deny("Неверный набор аргументов инструмента.")
    for key, expected_type in required.items():
        value = arguments.get(key)
        if expected_type is int and isinstance(value, bool):
            return _deny(f"Неверный тип аргумента {key}.")
        if not isinstance(value, expected_type):
            return _deny(f"Неверный тип аргумента {key}.")

    if name == "business_days_after":
        try:
            from datetime import date
            date.fromisoformat(arguments["start_date"])
        except (TypeError, ValueError):
            return _deny("Дата должна быть в формате ГГГГ-ММ-ДД.")
        if not 1 <= arguments["days"] <= 30:
            return _deny("Число рабочих дней должно быть от 1 до 30.")

    if "order_id" in required:
        order_id = str(arguments["order_id"])
        order = ORDERS.get(order_id)
        if order is None:
            return _deny(f"Заказ {order_id} не найден.")
        if name == "create_refund":
            if order["status"] != "cancelled":
                return _deny("Возврат разрешён только для отменённого заказа.")
            if order["refund_created"]:
                return _deny("По заказу уже был создан возврат.")
            if arguments["amount"] != order["amount"]:
                return _deny("Сумма возврата не совпадает с суммой заказа.")
            if order_id not in context.confirmed_refunds:
                return {
                    "decision": "needs_confirmation",
                    "reason": "Требуется подтверждение оператора в системе.",
                }
    return {"decision": "allow", "reason": "Вызов разрешён."}


CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s(\-]*\d{3}[)\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")


def check_output(text: str) -> str:
    """Redact card numbers, Russian phone numbers, and the partner key."""
    safe = str(text or "")
    safe = PHONE_RE.sub("[телефон скрыт]", safe)
    safe = CARD_RE.sub("[номер карты скрыт]", safe)
    api_key = os.getenv("PARTNER_API_KEY", "demo-key")
    if api_key:
        safe = safe.replace(api_key, "[ключ скрыт]")
    return safe
