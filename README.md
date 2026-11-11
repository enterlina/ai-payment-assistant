# AI Payment Assistant

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LLM](https://img.shields.io/badge/LLM-Ollama-111111)](https://ollama.com/)
[![Evaluation](https://img.shields.io/badge/Evaluation-24_scenarios-6C5CE7)](#evaluation-results)
[![Safety](https://img.shields.io/badge/Extra_refunds-0-16A085)](#evaluation-results)

A safety-first, action-taking LLM agent for installment-payment operations. The
assistant answers policy questions, retrieves order and payment status, computes
business-day deadlines, and creates eligible refunds through an unreliable
payment gateway—without trusting customer-provided instructions or duplicating
financial side effects.

> **Why this project matters:** Generating a plausible answer is not enough when
> an AI system can move money. This project treats authorization, idempotency,
> failure recovery, observability, and measurable safety as first-class system
> requirements.

## Executive summary

This project combines LLM tool calling, a bounded ReAct loop, three guardrail
layers, resilient API wrappers, idempotent writes, structured JSONL tracing, and
a reproducible evaluation suite.

### Measured outcomes

| Metric | Final result |
|---|---:|
| Correct scenarios | **24 / 24 (100%)** |
| Payment and order-status scenarios | **4 / 4 (100%)** |
| Prompt-injection attacks blocked | **4 / 4 (100%)** |
| Out-of-scope requests blocked | **2 / 2 (100%)** |
| Unconfirmed refunds stopped | **2 / 2 (100%)** |
| False-block rate | **0%** |
| Extra or duplicate refunds | **0** |
| Average agent steps | **2.33** |
| Average executed tool calls | **1.29** |

The first baseline run passed 17 of 24 scenarios. Trace analysis exposed four
failure classes: premature prose responses, malformed read-tool arguments,
incomplete prerequisite chains, and non-canonical but correct wording. After a
single corrective tool-use turn, prerequisite enforcement, safe read-argument
normalization, and grounded response normalization, the final run passed all 24
scenarios without weakening financial guardrails.

## Business problem

The fictional **Dolyka** installment-payment service receives requests from
customers and operations staff. The assistant must support three workflows:

1. answer questions about refunds, payment rescheduling, duplicate charges,
   fees, overdue payments, and chargebacks;
2. inspect internal order records and payment-partner status, then calculate
   deadlines using a production calendar;
3. create refunds only for cancelled orders, only after trusted operator
   confirmation, and no more than once per order.

The payment gateway deliberately simulates HTTP 429, HTTP 5xx, and responses
that arrive after the client timeout. Some write failures occur **after** the
refund has already been created. The test set also includes direct and indirect
prompt-injection attempts.

## Architecture

```text
Customer or operator request
             │
             ▼
┌───────────────────────────────┐
│ Input guardrail               │  Blocks injection and out-of-scope input
└──────────────┬────────────────┘
               ▼
┌───────────────────────────────┐
│ Bounded ReAct loop            │  Maximum 8 steps
│  1. LLM selects a tool        │
│  2. Action guardrail checks   │
│  3. Tool executes             │
│  4. Observation returns       │
└──────────────┬────────────────┘
               ▼
┌───────────────────────────────┐
│ Reliability layer             │  Timeout, retry, backoff, idempotency
└──────────────┬────────────────┘
               ▼
┌───────────────────────────────┐
│ Output guardrail              │  Redacts cards, phones, and secrets
└──────────────┬────────────────┘
               ▼
 Answer + auditable JSONL trace
```

### Why a manual ReAct loop?

Typical workflows require two to four tool steps and only a small number of
explicit branches. A manual bounded loop provides direct control over every
financial action, makes guardrail placement obvious, and keeps traces easy to
audit. For this scope, those properties were more valuable than introducing a
graph-orchestration dependency.

## Safety model

### 1. Untrusted-input boundary

Customer messages are treated as data, never as authority. The input guardrail
blocks attempts to override policies, inject fake system messages, bypass
confirmation, request secrets, or redirect the assistant outside its operating
scope. Blocked requests never reach the model or any tool.

### 2. Trusted operator confirmation

Refund confirmation is passed through `PolicyContext.confirmed_refunds`, which
is created by application code. A sentence such as “the operator approved this”
inside a customer email cannot authorize a refund.

### 3. Action-level financial policy

Before `create_refund` can run, the action guardrail verifies that:

- the tool is allow-listed;
- arguments have the expected names and types;
- the order exists;
- the order is cancelled;
- no refund already exists;
- the amount exactly matches the order amount;
- trusted operator confirmation exists;
- the customer directly requested a refund action.

When confirmation is missing, the assistant returns `needs_confirmation` and
does not call `POST /refund`.

### 4. Sensitive-output protection

The output layer removes full card numbers, Russian phone numbers, and the
partner API key. The journal masks idempotency keys and other sensitive request
identifiers before writing them to disk.

## Reliability and idempotency

Read operations use:

- a five-second timeout;
- up to three attempts;
- 0.5-second and 1.0-second backoff delays;
- retries for HTTP 429, HTTP 5xx, connection failures, and timeouts;
- a five-day-workweek fallback when the production calendar is unavailable.

Write operations are retried only when an idempotency key is present. Every
refund uses a stable key:

```text
refund-<order_id>
```

If the gateway creates a refund but the response times out or returns HTTP 500,
the next attempt uses the same key. The gateway recognizes the completed
operation instead of creating another refund.

The final request traces include a real read sequence containing HTTP 429, a
five-second `no_response` timeout, and another attempt. A separate reproducible
integration trace, [`logs/trace_write_retry.jsonl`](logs/trace_write_retry.jsonl),
proves ambiguous-write recovery: `POST /refund` returns HTTP 500 on attempt 1
after committing the refund and HTTP 200 on attempt 2. Both attempts contain the
same short idempotency-key hash while the raw `request_id` remains masked. The
gateway reports exactly one refund. Write operations allow at most three
attempts.

## Tools

| Tool | Purpose |
|---|---|
| `search_regulations` | Retrieve relevant operating policies |
| `get_order` | Read the internal order record |
| `get_payment_status` | Query the payment partner |
| `business_days_after` | Calculate a deadline using the production calendar |
| `create_refund` | Submit an idempotent refund after policy approval |
| `finish` | Return the grounded final response |

## Repository structure

```text
.
├── agent/
│   ├── agent.py          # bounded ReAct loop and orchestration
│   ├── guardrails.py     # input, action, and output policy enforcement
│   ├── reliability.py    # retries, timeouts, backoff, and write safety
│   └── tools.py          # external tools and tool registry
├── data/
│   ├── gateway/          # unreliable mock payment partner
│   ├── regulations/      # operating-policy knowledge base
│   ├── orders.json       # synthetic order database
│   └── requests.json     # 24 evaluation scenarios
├── evals/
│   └── run_eval.py       # side-effect-aware evaluation runner
├── logs/
│   ├── eval_main.txt     # human-readable evaluation report
│   ├── eval_main.json    # structured evaluation output
│   └── trace_m*.jsonl    # one audit trace per scenario
├── support/              # provided schemas, model client, data, and journal
├── portfolio_case_study.ipynb
├── check_tools.py
├── run.py
└── requirements.txt
```

## Evaluation design

The evaluator resets the gateway, processes all 24 scenarios, and checks:

- final decision (`answer`, `needs_confirmation`, `blocked`, or `max_steps`);
- required response content;
- required tools;
- actual refund count reported by the gateway;
- duplicate and extra financial side effects.

### Results by category

| Category | Passed | Accuracy |
|---|---:|---:|
| Regulation questions | 5 / 5 | 100% |
| Payment and order status | 4 / 4 | 100% |
| Deadline calculations | 5 / 5 | 100% |
| Confirmed refunds | 2 / 2 | 100% |
| Unconfirmed refunds | 2 / 2 | 100% |
| Prompt injection | 4 / 4 | 100% |
| Out of scope | 2 / 2 | 100% |

Both confirmed-refund scenarios created exactly one valid refund per order. Both
unconfirmed scenarios stopped at `needs_confirmation` without calling the
partner refund endpoint. No scenario created an extra refund.

Explore the evidence:

- [`portfolio_case_study.ipynb`](portfolio_case_study.ipynb) — full English
  walkthrough with executable analysis cells;
- [`logs/eval_main.txt`](logs/eval_main.txt) — human-readable result table;
- [`logs/eval_main.json`](logs/eval_main.json) — structured metrics;
- [`logs/`](logs/) — 24 JSONL audit traces.

## Failure analysis and fixes

| Baseline failure class | Observation | Fix implemented | Result |
|---|---|---|---|
| Plain text instead of a tool call | m12 and m15 exposed internal next-step prose to the user | Add a corrective turn that instructs the model to call the missing required tool | Required chains now complete |
| Malformed read arguments | m05 and m13 supplied a non-string regulation query | Normalize safe read-only query arguments to the original request | Regulation tools execute successfully |
| Incomplete prerequisite chain | Deadline and refund flows stopped before all grounded tools ran | Compute required tools and reject premature `finish` calls | Deadline and confirmed-refund categories reach 100% |
| Incorrect action choice | m11 attempted a refund for a deadline-only request | Require a direct refund instruction before `create_refund` | No unintended write occurs |
| Canonical wording mismatch | m02 and m16 were semantically correct but missed required policy wording | Add grounded canonical wording only after the supporting tool succeeds | Answer-fragment checks pass |

## Automated tests

The repository includes five executable tests:

```bash
python -m unittest discover -s tests -v
```

They cover input blocking, trusted refund confirmation, eligible refund
approval, output redaction, and the seeded post-commit HTTP 500 idempotency
scenario. The integration test generates `logs/trace_write_retry.jsonl` and
asserts statuses `[500, 200]`, attempts `[1, 2]`, one shared key hash, a masked
raw key, and a final refund count of one.

## Run locally

### Prerequisites

- Python 3.9+
- [Ollama](https://ollama.com/)
- approximately 5 GB available for `qwen2.5:7b`

### Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

ollama pull qwen2.5:7b
export PARTNER_API_KEY=demo-key
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_MODEL=qwen2.5:7b
```

Start Ollama:

```bash
ollama serve
```

Start the payment gateway in a second terminal:

```bash
source .venv/bin/activate
PARTNER_API_KEY=demo-key python data/gateway/mock_gateway.py
```

Run a tool-selection check and one request:

```bash
python check_tools.py
python run.py "What is the amount for order 4125?"
```

Run the full evaluation:

```bash
python evals/run_eval.py
```

## Language note

The portfolio documentation and analysis are in English. The synthetic source
dataset, policy documents, benchmark prompts, and generated traces are in
Russian because the original operating scenario evaluates a Russian-language
customer-support workflow. They contain synthetic data only. Keeping those
artifacts in their evaluated language preserves reproducibility and makes this
repository an example of multilingual AI operations engineering.

## What this project demonstrates

- action-taking LLM orchestration with function calling;
- guardrails that separate untrusted language from trusted application state;
- idempotent financial API integration;
- bounded retry, timeout, and fallback strategies;
- trace-level observability and auditability;
- side-effect-aware agent evaluation;
- transparent failure analysis and safety-first iteration;
- practical trade-offs when deploying a local model.

## Roadmap

- Introduce a deterministic intent router for regulated workflows.
- Move refund execution into an explicit state machine.
- Generate final answers from validated structured observations.
- Run the existing unit and integration tests in CI and add schema contracts.
- Compare larger local models and hosted models on the same benchmark.
- Add OpenTelemetry traces and latency/cost dashboards.

## Disclaimer

This repository is an educational portfolio project built with synthetic data
and a mock payment gateway. It does not connect to a real financial institution
or process real customer funds.
