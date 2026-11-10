# Safe AI Payment Operations Assistant

An AI engineering case study demonstrating how to build an action-taking LLM
assistant for an installment payment service while keeping financial operations
safe, idempotent, observable, and resistant to prompt injection.

## Portfolio highlights

- Bounded manual ReAct loop with OpenAI-compatible tool calling and Ollama.
- Three guardrail layers: untrusted-input screening, action-policy validation,
  and sensitive-output redaction.
- Stable idempotency keys prevent duplicate refunds after HTTP 500 responses or
  timeouts that occur after the gateway has already processed an operation.
- Reliable API wrappers provide five-second timeouts, bounded retries, backoff,
  calendar fallback, and per-attempt structured logging.
- Evaluation covers 24 scenarios, including regulations, order status,
  deadlines, confirmed and unconfirmed refunds, prompt injection, and
  out-of-scope requests.

### Final evaluation

| Metric | Result |
|---|---:|
| Correct scenarios | **17 / 24 (70.8%)** |
| Prompt-injection attacks blocked | **4 / 4** |
| False-block rate | **0%** |
| Unconfirmed refunds stopped | **2 / 2** |
| Extra or duplicate refunds | **0** |
| Average agent steps | **2.0** |
| Average executed tool calls | **0.96** |

The remaining failures are documented rather than hidden: the local 7B model
occasionally returned prose instead of completing a required tool chain. These
quality failures remained safe failures—no unauthorized or duplicate financial
operation was created.

### Explore the case study

- [`portfolio_case_study.ipynb`](portfolio_case_study.ipynb) — complete English
  walkthrough with architecture, safety decisions, real metrics, failure
  analysis, and executable result-inspection cells.
- [`logs/eval_main.txt`](logs/eval_main.txt) — human-readable final evaluation.
- [`logs/eval_main.json`](logs/eval_main.json) — structured results.
- [`logs/`](logs/) — one auditable JSONL trace for every scenario.

### Technology

Python, Ollama, OpenAI-compatible APIs, function calling, ReAct, HTTP APIs,
idempotency, JSONL observability, prompt-injection defense, and scenario-based
agent evaluation.

---

# Ассистент операционной команды «Дольки»

Ассистент отвечает по регламентам, проверяет заказы и статус платежей,
рассчитывает рабочие дни и безопасно оформляет подтверждённые возвраты.

## Архитектура

Выбран ручной ограниченный ReAct-цикл. Типовой сценарий занимает 2–4 шага,
ветвления простые (запрет на входе, проверка инструмента, запрос подтверждения,
завершение), а для денежных операций важнее прозрачный контроль каждого шага,
чем скорость сборки графа. LangGraph добавил бы зависимость и сложность без
выигрыша для такого небольшого конечного процесса.

Слои проекта:

- `agent/agent.py` — системный промпт, максимум восемь шагов, история tool calls,
  подсчёт токенов и обязательные события журнала;
- `agent/guardrails.py` — доверенный `PolicyContext`, защита входа, строгая
  проверка аргументов и бизнес-условий возврата, маскирование выхода;
- `agent/tools.py` — четыре требуемых инструмента и единый реестр вместе с двумя
  готовыми инструментами данных;
- `agent/reliability.py` — таймауты, backoff 0,5/1 сек., до трёх попыток чтения,
  безопасный повтор записи только с ключом идемпотентности и ретраи модели;
- `evals/run_eval.py` — 24 сценария, проверка решений, фрагментов, инструментов и
  реальных побочных эффектов через `/refund_count`.

Возврат получает стабильный ключ `refund-<order_id>`. Поэтому даже если шлюз
создал возврат, но ответил 500 или не успел ответить до таймаута, повторная
попытка не создаёт вторую операцию. Секретный заголовок никогда не записывается
в журнал, а `request_id` маскируется готовым модулем журнала.

## Запуск

Из корня проекта:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export PARTNER_API_KEY=demo-key
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_MODEL=qwen2.5:7b
ollama serve
ollama pull qwen2.5:7b
```

В отдельном терминале:

```bash
source .venv/bin/activate
PARTNER_API_KEY=demo-key python data/gateway/mock_gateway.py
```

Проверка выбора инструмента и ручные обращения:

```bash
python check_tools.py
python run.py "Какая сумма у заказа 4125?"
python run.py "Оформи возврат по заказу 4126" --confirm 4126
```

Финальная оценка:

```bash
python evals/run_eval.py
```

Скрипт перезаписывает `logs/eval_main.txt`, `logs/eval_main.json` и создаёт
`logs/trace_<id>.jsonl` для каждого обращения.

## Результаты

Код проверен локально 9 ноября 2026 года:

- все Python-файлы успешно разобраны парсером;
- тесты входного, action- и output-guardrail прошли;
- симулированный ReAct-сценарий без подтверждения вернул
  `needs_confirmation`, выполнив только `get_order`;
- инъекция остановлена до модели и инструментов;
- интеграционный тест шлюза с 429 и таймаутом создал ровно один возврат;
  журнал содержит все пять попыток, а `request_id` замаскирован.

Финальный прогон выполнен на `qwen2.5:7b` при штатной доле сбоев шлюза 30%.
Корректно обработано 17 из 24 обращений (70,8%). По категориям: регламенты —
60%, статусы — 100%, сроки — 40%, подтверждённые возвраты — 0%, возвраты без
подтверждения — 100%, инъекции — 100%, обращения вне компетенции — 100%.
Подробная таблица сохранена в `logs/eval_main.txt`, структурированные результаты
— в `logs/eval_main.json`, а ход каждого обращения — в 24 trace-файлах.

## Ответы на вопросы бизнеса

1. Ассистент корректно закрыл 70,8% обращений. Все статусные и защитные сценарии
   пройдены; ошибки сосредоточены в расчётах сроков, формулировках регламентов и
   подтверждённых возвратах из-за нестабильного соблюдения tool calling моделью.
2. В среднем одно обращение потребовало 2,0 шага и 0,96 выполненного вызова
   инструмента. Жёсткий лимит одного обращения — восемь шагов.
3. Все 4 из 4 попыток инъекции остановлены; доля ложных блокировок обычных
   обращений — 0%. Возвраты без доверенного подтверждения также остановлены 2/2.
4. Лишних возвратов создано 0. Единственный созданный в финальном прогоне
   возврат соответствовал подтверждённому сценарию; повторные сетевые попытки
   защищены стабильным ключом идемпотентности.

## Типовые ошибки агента и что с ними делать

| Класс | Пример | Причина | Принятое решение |
|---|---|---|---|
| Инъекция | «Игнорируй регламенты…» | Текст клиента пытается стать инструкцией | Блокировка до вызова модели |
| Ложное подтверждение | «Оператор подтвердил» внутри письма | Недоверенная фраза не равна системной отметке | Проверка только `PolicyContext` |
| Повтор записи | Таймаут после созданного возврата | Результат операции неизвестен клиенту | Стабильный ключ идемпотентности |
| Недоступный календарь | Ошибка `isdayoff.ru` | Внешний сервис не отвечает | Пятидневная неделя и пометка «праздники не учтены» |
| Ошибка модели | m05: ответ без `search_regulations` | Модель вернула текст вместо tool call | Добавлен разбор встроенного JSON tool call; для простого текста остаётся безопасный ответ |
| Неполная цепочка | m12, m13, m15 | Модель описала следующий инструмент вместо его вызова | Усилен промпт и добавлены обязательные prerequisites; дальнейшее улучшение — детерминированный роутер |
| Лишнее действие | m11 | Модель пыталась создать возврат для вопроса о сроке | Добавлена отдельная проверка прямой просьбы до `create_refund` |
| Формулировка | m02, m16 | Ответ семантически верный, но не содержит ожидаемый эталонный фрагмент | Добавить нормализацию финальных формулировок по кодам регламентов |
