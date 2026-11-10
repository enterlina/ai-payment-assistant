"""Quick check that the configured model can select a tool."""

from support.llm import LLMClient
from support.schemas import TOOL_SCHEMAS

llm = LLMClient()
messages = [{"role": "user", "content": "Какая сумма у заказа 4125?"}]
calls, usage = llm.chat(messages, TOOL_SCHEMAS)
print(calls or usage["content"])
