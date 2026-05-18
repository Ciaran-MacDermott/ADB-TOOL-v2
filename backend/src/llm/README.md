# `src/llm/` — LLM client

One transport layer between the deck pipeline and whichever model you're using. The pipeline (`acc_deck_pkg`, `acc_deck_fs_pkg`) NEVER imports `requests`, `groq`, `openai`, or `anthropic` directly — it only ever calls `llm.complete(profile=..., messages=...)`. That means switching providers is a single-file change.

## Quick mental model

```
pipeline code  →  llm.complete("writer", messages=[...])
                                │
                                ▼
                         profiles.py        ← named profiles map "writer" → (provider, model, defaults)
                                │
                                ▼
                       providers/__init__.py ← registry: instantiate one provider per name
                                │
                                ▼
            providers/{openai_compat, moonshot, internal_stub}.py   ← actual HTTP call
```

## Files

| File | What it does | Edit when |
|---|---|---|
| `__init__.py` | `complete()` public surface | basically never |
| `errors.py` | `ProviderError` hierarchy | adding a new error class |
| `retries.py` | shared exponential-backoff helper | tuning the retry schedule |
| `profiles.py` | named profiles → (provider, model, sampling defaults) | **changing which provider answers a profile** |
| `providers/base.py` | `Provider` Protocol | basically never |
| `providers/openai_compat.py` | generic `POST /v1/chat/completions` impl | basically never |
| `providers/moonshot.py` | Moonshot Kimi quirks (thinking disabled, locked temperature) | adding Moonshot-specific tweaks |
| `providers/internal_stub.py` | placeholder for the internal endpoint | **wiring the internal provider** |
| `providers/__init__.py` | provider registry | adding a brand-new provider |

## Migrating to internally-hosted models — the 5-minute version

> The receiving team only needs to touch **two files**: `providers/internal_stub.py` and `profiles.py`.

### Step 1 — wire the internal endpoint

Open `providers/internal_stub.py`. Replace the body of `make_internal_provider()` with the right shape for your endpoint.

**If your endpoint speaks OpenAI Chat Completions** (vLLM, TGI, Ollama, FastChat, LM Studio, Anyscale, Together, Fireworks, most internal stacks):

```python
from llm.providers.openai_compat import OpenAICompatProvider

def make_internal_provider() -> Provider:
    return OpenAICompatProvider(
        name="internal",
        base_url="https://llm.internal.circana.com/v1/chat/completions",
        env_var="INTERNAL_LLM_API_KEY",
    )
```

**If your endpoint has a bespoke shape**, subclass `OpenAICompatProvider` and override one method. See `moonshot.py` for the canonical pattern (it overrides `_build_payload` to inject Moonshot's `thinking: {"type": "disabled"}` field). You can override:

- `_build_payload(messages, model, temperature, top_p, max_tokens) -> dict` — control the request body.
- `_parse_response(data: dict) -> str` — control how you extract assistant text from the response.
- `_resolve_key(override) -> str` — control auth header construction.

### Step 2 — repoint profiles

Open `profiles.py`. Each profile (`brief`, `writer`, `cleanup`, `fast_writer`, `total_subheader`, `fs_insight`) currently points at `groq` or `moonshot`. To send any/all to your internal endpoint, change the `provider` and `model` fields:

```python
"writer": Profile(
    name="writer",
    provider="internal",                    # was: "moonshot"
    model="circana-llama-70b-instruct",     # was: "kimi-k2.6"
    max_tokens=100,
),
```

You can repoint profiles incrementally — e.g. send the writer to the internal endpoint while leaving the brief stage on Groq during a transition.

### Step 3 — set the env var

```bash
export INTERNAL_LLM_API_KEY=...
```

Add it to `.env.example` so future devs know it's needed.

### Step 4 — done

No pipeline code changes. No `import` swaps. No call-site rewrites.

## How to verify your changes work

```bash
# Quick sanity — instantiate the provider and confirm it auths
python -c "
from llm import complete
print(complete('writer', messages=[
    {'role': 'system', 'content': 'You are a calculator.'},
    {'role': 'user',   'content': 'Reply with only the digits 42.'},
], max_tokens=10))
"
```

Expected output: `42` (or close to it). If you see `ProviderAuthFailed` → check the env var. `ProviderUnavailable` → check the URL / network.

## Why this shape

- **Pipeline code stays oblivious** to provider switches. The receiving team can't accidentally break the deck logic by changing models.
- **System prompts and post-processing stay where they are** (in `acc_deck_pkg/llm_insights_free.py` for ADB and `acc_deck_fs_pkg/prompts/*.md` for foodservice). The handover team doesn't need to read or modify them.
- **One backoff + retry implementation** (`retries.py`) instead of five copies of the same `for attempt in range(4): wait = 10 * (2 ** attempt)` loop scattered across modules.
- **One error vocabulary** — pipeline code catches `ProviderRateLimited` / `ProviderAuthFailed` / `ProviderUnavailable`, not `requests.HTTPError`. Switching providers doesn't ripple through `try/except` blocks.

## Adding a brand-new provider (rare)

If your endpoint is fundamentally different from OpenAI Chat Completions (e.g. Anthropic Messages API, GraphQL, gRPC):

1. Create `providers/<name>.py` implementing the `Provider` Protocol from `base.py` — just `name: str` and `complete(...)`.
2. Register it in `providers/__init__.py`:
   ```python
   _REGISTRY["my_provider"] = MyProvider(...)
   ```
3. Reference it from a profile: `provider="my_provider"`.

That's it.
