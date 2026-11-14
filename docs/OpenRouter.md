# OpenRouter task worker

MoneyPrinterV2 can generate text through OpenRouter while retaining the local
Ollama path. The worker also produces draft files from a small JSON queue on a
schedule. It does not publish, send messages, place trades or wagers, transfer
money, or call tools on behalf of the generated text.

## Add the key

In this repository, open **Settings → Secrets and variables → Actions → New
repository secret**:

<https://github.com/s-os-agency/MoneyPrinterV2/settings/secrets/actions/new>

Name the secret exactly `OPENROUTER_API_KEY` and paste the key into its **Secret**
field. Never put it in a source file, issue, workflow input, chat, task prompt or
`config.example.json`.

For a local runtime, provide the same name as a process environment variable or
through the runtime's secret store. The client does not read a key from config.

## Model routing and the $50 monthly ceiling

- `auto` discovers the current `/models` catalogue instead of using a stale list
  of model names. Text-in/text-out chat models are supported by this adapter;
  image/audio generation need their own adapters.
- Free pricing is preferred. Newer free models are selected ahead of older ones
  at equal price. Non-numeric, missing, negative and sentinel prices are rejected.
- Optional preferences by task kind are lists of actual model IDs in
  `openrouter_routes`. Free models remain ahead of paid preferences in auto mode.
- A specific `OPENROUTER_MODEL` or task `model` selects that model if its pricing
  fits the policy. It does not bypass the price or context limits.
- The default is free-only: `OPENROUTER_ALLOW_PAID=false`. A server-side
  `provider.max_price` of zero prevents a fallback provider charging a fee.
- To allow cheap paid text, use a **dedicated key** with an OpenRouter-enforced
  monthly credit limit of **$50 or less**, then set `OPENROUTER_ALLOW_PAID=true`.
  In OpenRouter's key settings, choose a monthly reset for that key's credit
  limit. A supported applicable monthly guardrail of $50 or less also qualifies.
- Before paid generation, the client reads `/key` and requires that provider-side
  monthly cap and enough remaining budget. A missing/unreadable budget stops
  paid generation. A local counter or GitHub cache is not treated as enforcement.
- Application defaults are also capped at $50/month, $0.05 estimated per request,
  $1 per million input tokens, $2 per million output tokens and 2,048 output
  tokens. A higher monthly config value cannot raise the application's $50 cap.
  Lower configured values are honored. Provider rate limits and insufficient
  credits can still stop a request; free availability is not guaranteed.
- Provider fallback is limited to the same selected model and the request's
  maximum rates. The client never retries a failed completion POST automatically.
  It does not silently switch a rejected free request to a paid model.

Free models may have different data policies from paid models. Only send content
that the owner has authorized for the selected provider. The committed sample
queue contains public-safe instructions and no private customer material.

## Existing interactive and social-content flows

Set `llm_provider` in your private `config.json`, or use the `LLM_PROVIDER`
environment variable. Existing configurations without this field retain Ollama.
New configurations copied from `config.example.json` select OpenRouter.

```bash
# With the key supplied by the runtime secret store:
LLM_PROVIDER=openrouter python3 src/main.py
```

Twitter, YouTube and affiliate text already use the common `generate_text`
interface, so provider selection applies there. Their existing publishing flows
are not invoked by the new task worker. The old social-posting `src/cron.py`
remains a separate, explicit action and can use the configured provider model.

## Produce queued drafts

```bash
python3 scripts/openrouter_tasks.py --list-models
python3 scripts/openrouter_tasks.py --queue tasks/openrouter_tasks.json --limit 3
```

The first command reads public model metadata; it does not generate text.
The worker needs only Python 3.12's standard library, not Selenium, video tools,
Ollama or the application's full dependency set.

Each queue entry has a unique `id`, a `prompt`, optional `kind` and `model`, a
boolean `enabled`, and `repeat` set to `once`, `hourly` or `daily`. Example task
kinds are `routine`, `copywriting` and `formatting`. The default queue contains
one enabled proposal-outline draft and one disabled daily service-copy example.
This is a local/repository JSON queue; it does not automatically read the shared
Google Sheet or inherit ChatGPT connectors. Keep the Sheet as the owner record;
export only authorized public-safe task prompts to this public repository.

The worker writes outputs under `.mp/openrouter/outputs/`, receipts under
`.mp/openrouter_receipts.jsonl`, and state in `.mp/openrouter/runs.sqlite3`.
These files are ignored by Git. Receipts contain generation IDs, model, token
counts and actual cost if returned. Missing cost is recorded as unknown, not
zero. No prompts, generated text or key-budget details are printed in job logs.

Task slots use `Asia/Dubai` by default (`TASK_TIMEZONE` overrides it). The worker
claims a slot transactionally in SQLite before inference. Existing completed,
stopped or in-flight slots are not run again. If a prompt is changed under an
existing once-only ID, the worker reports the changed input and keeps the slot;
use a new ID for an intentionally new task.

A timeout can leave billing uncertain. The recorded stopped slot is retained
rather than retried automatically. A truncated generation also stops and retains
its receipt; split the task instead of repeatedly paying for an incomplete result.

## Scheduled production

`.github/workflows/openrouter-tasks.yml` supports a manual dispatch and an hourly
cron at minute 17 UTC. GitHub schedules run from the default branch and may be
delayed. A feature branch or a draft PR does not activate that schedule.

After the workflow is on the default branch and the secret is present, add the
repository **Actions variable** `OPENROUTER_TASKS_ENABLED` with value `true`:

<https://github.com/s-os-agency/MoneyPrinterV2/settings/variables/actions>

The workflow remains idle until that variable is set. `OPENROUTER_ALLOW_PAID`
is a separate repository Actions variable; leave it `false` for free-only or set
it to `true` after setting the dedicated key's enforced monthly limit.

The workflow restores and saves the SQLite state using GitHub's cache and
serializes runs. Caches can be evicted or expire: deduplication is best-effort
across fresh runners, not a permanent financial ledger. The provider-side
monthly limit remains the budget boundary even after a cache loss. For durable
exact once-only processing, run the same worker on an existing persistent host
with its `.mp` directory retained.

Generated files from the committed **public-safe** JSON queue are uploaded as
seven-day Actions artifacts. This repository is public: do not place private
client prompts or generated private work in that queue or its artifacts. Private
work must use an existing authorized private runtime/destination instead.

## Operational state of this change

Implementation and scheduling configuration can be prepared without the key.
No inference, earned revenue, deployment or active scheduled runtime should be
claimed until its actual receipt exists. Missing credentials require setting the
secret, not pasting it into the conversation.

Repository owner instructions prohibit adding or running tests. This change
does not add a test suite, test workflow or inspection stage.

Official API references used:
- <https://openrouter.ai/docs/api_reference/models>
- <https://openrouter.ai/docs/guides/routing/provider-selection#max-price>
- <https://openrouter.ai/docs/api_reference/limits>
