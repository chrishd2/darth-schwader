# Implementation Plan: Darth Schwader — Migrate from Anthropic + OpenAI to OpenRouter

**Feature:** openrouter-migration
**Project:** `/Users/chd2/Claude Sandbox/software/darth-schwader`
**Planned:** 2026-04-18

---

## ⚠️ Security Note

The user shared an OpenRouter API key in chat. **Rotate it after migration** at https://openrouter.ai/keys. This plan treats the key as a placeholder and reads the real value from `.env` only (never committed, never hardcoded).

---

## Task Type

- [ ] Frontend
- [x] **Backend** (config + LLM integration)
- [ ] Fullstack

No UI changes. Scheduler wiring is optional (marked `P2`).

---

## Current State Summary

| Component | Status |
|-----------|--------|
| `config.py` | Defines `ai_provider: Literal["claude","openai","none"]`, `anthropic_api_key`, `openai_api_key` |
| `ai/llm/claude_provider.py` | `ClaudeStrategySelector` uses `anthropic.AsyncAnthropic`, model `claude-3-5-sonnet-latest` |
| `ai/llm/selector.py` | `LLMStrategySelector` Protocol + `NullLLMSelector` |
| `ai/llm/` | **No `openai_provider.py`** — "openai" is unimplemented dead config |
| `ai/llm/prompts/strategy_selection.md` | **Referenced but doesn't exist** — would raise `FileNotFoundError` at runtime |
| `lifespan.py` | **Never instantiates any selector**; scheduler `signal_runner=None` |
| `pyproject.toml` | Pins both `anthropic>=0.40.0` and `openai>=1.57.0` |
| `.env.example` | Exports `ANTHROPIC_API_KEY=`, `OPENAI_API_KEY=`, `AI_PROVIDER=claude` |

---

## Technical Solution

**OpenRouter is OpenAI-API compatible** — use the official `openai` Python SDK with `base_url="https://openrouter.ai/api/v1"` and the OpenRouter API key. This gives access to Anthropic, OpenAI, Google, Mistral, Meta, etc. models through a single endpoint.

### Anthropic via OpenRouter (confirmed supported)
Yes — **all current Claude models are available through OpenRouter** and work out of the box with this plan. Examples of model IDs you can drop into `OPENROUTER_MODEL`:

| Model ID | Use case |
|----------|----------|
| `anthropic/claude-opus-4.7` | Deepest reasoning (latest Opus) |
| `anthropic/claude-sonnet-4.6` | Default — best price/performance for trading strategy |
| `anthropic/claude-haiku-4.5` | Fast, cheap; good for low-latency signals |
| `anthropic/claude-3.5-sonnet` | Stable fallback, mature tooling |
| `openai/gpt-4o` | Cross-check via OpenAI |
| `google/gemini-2.5-pro` | Cross-check via Google |
| `openrouter/auto` | Let OpenRouter pick based on prompt |

**Switching models is now config-only** — no code changes needed. Just update `OPENROUTER_MODEL` in `.env` and restart.

### Provider Strategy
- **Single provider**: `OpenRouterStrategySelector` using `openai.AsyncOpenAI` with custom `base_url`
- Use `chat.completions.create` (OpenRouter supports this across all routed models, including Anthropic)
- **JSON enforcement via prompt, not `response_format`**: OpenRouter's Anthropic-routed models do **not** reliably honor the OpenAI-style `response_format={"type":"json_object"}` parameter. Instead, the system prompt instructs the model to return only JSON, and the parser extracts the first JSON object/array from the response text (stripping ```json fences, leading prose, etc.)
- Pass OpenRouter's recommended attribution headers (`HTTP-Referer`, `X-Title`) via `default_headers` — optional but improves rate-limit tier

### Default Model
- Default: `anthropic/claude-sonnet-4.6` — best balance of quality, cost, and JSON-compliance for Anthropic users
- User-configurable via `OPENROUTER_MODEL` env var

### Dependencies
- **Keep** `openai>=1.57.0` (used for OpenRouter client)
- **Remove** `anthropic>=0.40.0` (no longer needed)

---

## Implementation Steps

### Phase 1 — Core migration (P0, required)

**Step 1.1 — Update `config.py`**
- Change: `ai_provider: Literal["openrouter", "none"] = "openrouter"` (remove "claude", "openai")
- Add fields:
  - `openrouter_api_key: SecretStr | None = None`
  - `openrouter_model: str = "anthropic/claude-sonnet-4.6"`
  - `openrouter_base_url: str = "https://openrouter.ai/api/v1"`
  - `openrouter_http_referer: str | None = None` (optional attribution)
  - `openrouter_app_title: str | None = "Darth Schwader"` (optional attribution)
- Remove fields: `anthropic_api_key`, `openai_api_key`
- Expected deliverable: settings object exposes `openrouter_*` fields; old fields gone

**Step 1.2 — Create `src/darth_schwader/ai/llm/openrouter_provider.py`**
- Class: `OpenRouterStrategySelector` implementing `LLMStrategySelector` Protocol
- Constructor signature: `__init__(self, *, api_key: str, model: str, base_url: str, http_referer: str | None = None, app_title: str | None = None)`
- Instantiate `openai.AsyncOpenAI(api_key=api_key, base_url=base_url, default_headers={...})`
- `select()` method:
  1. Read prompt from `PROMPT_PATH` (unchanged path)
  2. Build same JSON payload as current `claude_provider.py` (features + context)
  3. Call `client.chat.completions.create(model=..., messages=[{role:"system", content:prompt},{role:"user", content:payload}], max_tokens=2048, response_format={"type":"json_object"})`
  4. Parse `response.choices[0].message.content` as JSON
  5. If response is `{"signals": [...]}` unwrap to list; if top-level list, use as-is
  6. `return [StrategySignal.model_validate(item) for item in payload_list]`
- Expected deliverable: new file, ~60 lines, mirrors claude_provider structure

**Pseudo-code:**
```python
import json
import re
from pathlib import Path
from openai import AsyncOpenAI
from darth_schwader.ai.contracts import AiRunContext, StrategySignal
from darth_schwader.quant.features import Features

MAX_TOKENS = 2048
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "strategy_selection.md"

class OpenRouterStrategySelector:
    def __init__(self, *, api_key, model, base_url, http_referer=None, app_title=None):
        headers = {}
        if http_referer: headers["HTTP-Referer"] = http_referer
        if app_title: headers["X-Title"] = app_title
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, default_headers=headers or None)
        self._model = model

    async def select(self, features, context):
        if not PROMPT_PATH.exists():
            raise FileNotFoundError(f"missing prompt file: {PROMPT_PATH}")
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        payload = json.dumps({"features": {...}, "context": context.model_dump(mode="json")})
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": payload},
            ],
        )
        text = response.choices[0].message.content or ""
        data = _extract_json(text)  # strips ```json fences, leading prose
        items = data.get("signals", []) if isinstance(data, dict) else data
        return [StrategySignal.model_validate(item) for item in items]


_JSON_BLOCK_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)

def _extract_json(text: str) -> dict | list:
    """Extract first JSON object/array from model output.

    Tolerates: ```json fences, leading/trailing prose, whitespace.
    """
    if not text or not text.strip():
        return {}
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        raise ValueError(f"no JSON object/array found in model output: {text[:200]!r}")
    return json.loads(match.group(1))
```

**Step 1.3 — Delete `claude_provider.py`**
- Remove `src/darth_schwader/ai/llm/claude_provider.py` entirely
- No current imports reference it (verified via grep)
- Expected deliverable: file removed

**Step 1.4 — Create missing prompt file**
- Write `src/darth_schwader/ai/llm/prompts/strategy_selection.md`
- Must instruct model to emit JSON matching `StrategySignal` schema (see `ai/contracts.py`)
- System prompt explicitly requests: `{"signals": [<StrategySignal>...]}` envelope for `response_format=json_object` compatibility
- Expected deliverable: new prompt file with schema spec + few-shot example

**Step 1.5 — Update `ai/llm/__init__.py` with factory**
- Add: `from darth_schwader.ai.llm.openrouter_provider import OpenRouterStrategySelector`
- Add factory function:
  ```python
  def build_selector(settings: Settings) -> LLMStrategySelector:
      if settings.ai_provider == "none" or not settings.openrouter_api_key:
          return NullLLMSelector()
      return OpenRouterStrategySelector(
          api_key=settings.openrouter_api_key.get_secret_value(),
          model=settings.openrouter_model,
          base_url=settings.openrouter_base_url,
          http_referer=settings.openrouter_http_referer,
          app_title=settings.openrouter_app_title,
      )
  ```
- Update `__all__` to include `OpenRouterStrategySelector` and `build_selector`
- Expected deliverable: clean factory; callers don't branch on provider

**Step 1.6 — Update `pyproject.toml`**
- Remove line: `"anthropic>=0.40.0,<1.0.0",`
- Keep: `"openai>=1.57.0,<2.0.0",`
- Expected deliverable: slimmer deps; reinstall via `pip install -e ".[dev]"`

**Step 1.7 — Update `.env.example`**
- Remove: `ANTHROPIC_API_KEY=`, `OPENAI_API_KEY=`
- Add:
  ```
  # OpenRouter (gives access to Anthropic, OpenAI, Google, Meta, etc. via one key)
  # Get key: https://openrouter.ai/keys
  OPENROUTER_API_KEY=
  # Examples: anthropic/claude-sonnet-4.6, anthropic/claude-opus-4.7, anthropic/claude-haiku-4.5,
  #           openai/gpt-4o, google/gemini-2.5-pro, openrouter/auto
  OPENROUTER_MODEL=anthropic/claude-sonnet-4.6
  OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
  OPENROUTER_HTTP_REFERER=
  OPENROUTER_APP_TITLE=Darth Schwader
  ```
- Change: `AI_PROVIDER=openrouter`
- Expected deliverable: updated template

**Step 1.8 — Add tests**
- New file: `tests/unit/test_openrouter_selector.py`
- Uses `respx` (already in dev deps) to mock `https://openrouter.ai/api/v1/chat/completions`
- Tests:
  - `test_select_returns_parsed_signals` — mock response → verify `list[StrategySignal]`
  - `test_select_raises_on_missing_prompt` — tmpdir with no prompt file → FileNotFoundError
  - `test_select_unwraps_signals_envelope` — `{"signals": [...]}` → extracted correctly
  - `test_select_accepts_top_level_list` — `[...]` → used as-is
  - `test_select_strips_code_fences` — response wrapped in ```json ... ``` → parsed correctly (real-world Anthropic output pattern)
  - `test_select_tolerates_leading_prose` — "Here is the result:\n{...}" → extracted correctly
- New file: `tests/unit/test_llm_factory.py`
  - `test_build_selector_returns_null_when_no_api_key`
  - `test_build_selector_returns_null_when_provider_is_none`
  - `test_build_selector_returns_openrouter_when_configured`
- Expected deliverable: 5+ passing unit tests; `pytest --cov=src/darth_schwader/ai/llm` ≥ 80%

### Phase 2 — Wire into app runtime (P1, recommended)

**Step 2.1 — Wire selector in `lifespan.py`**
- Import: `from darth_schwader.ai.llm import build_selector`
- Import: `from darth_schwader.ai.service import SignalGenerator`
- Import: `from darth_schwader.quant.features import QuantModule` (or wherever the quant impl lives)
- After settings/session_factory setup:
  ```python
  llm_selector = build_selector(settings)
  signal_generator = SignalGenerator(
      quant=<quant_module>,
      selector=llm_selector,
      repos={"session_factory": session_factory},
      settings=settings,
  )
  app.state.llm_selector = llm_selector
  app.state.signal_generator = signal_generator
  ```
- Expected deliverable: selector + generator available in `app.state`; `NullLLMSelector` is safe default if key missing

**Step 2.2 — (Optional) Wire scheduler signal_runner**
- Currently `signal_runner=None` in `register_jobs` deps
- Replace with an async callable that invokes `signal_generator.run(context)` with a built `AiRunContext`
- Out of scope for this migration unless user explicitly requests it (context building is a separate feature)
- Marked **P2** — defer to follow-up PR

### Phase 3 — Cleanup & verification (P0)

**Step 3.1 — Verify removal of dead code paths**
- Grep for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `anthropic_api_key`, `openai_api_key`, `ClaudeStrategySelector`, `from anthropic`, `import anthropic` across repo
- Should return zero hits (except possibly in docs/README)
- Expected deliverable: clean grep

**Step 3.2 — Update README if needed**
- If `README.md` mentions Anthropic/OpenAI setup, update to OpenRouter instructions
- Expected deliverable: docs in sync

**Step 3.3 — Run full verification**
```bash
cd software/darth-schwader
pip install -e ".[dev]"
ruff check src tests
mypy src
pytest --cov=src --cov-report=term-missing
```
- Expected deliverable: lint green, mypy green, all tests pass, coverage ≥ 80% for `ai/llm/`

---

## Key Files

| File | Operation | Description |
|------|-----------|-------------|
| `src/darth_schwader/config.py:52-54` | Modify | Swap provider enum + API-key fields for OpenRouter equivalents |
| `src/darth_schwader/ai/llm/claude_provider.py` | **Delete** | No longer used |
| `src/darth_schwader/ai/llm/openrouter_provider.py` | **Create** | `OpenRouterStrategySelector` using `openai.AsyncOpenAI` |
| `src/darth_schwader/ai/llm/prompts/strategy_selection.md` | **Create** | Missing prompt file (current code would crash without it) |
| `src/darth_schwader/ai/llm/__init__.py` | Modify | Add `build_selector()` factory; export new class |
| `src/darth_schwader/ai/llm/selector.py` | Unchanged | Protocol stays the same |
| `src/darth_schwader/ai/service.py` | Unchanged | Already provider-agnostic via Protocol |
| `src/darth_schwader/lifespan.py:33-91` | Modify (P1) | Instantiate selector + SignalGenerator |
| `pyproject.toml:25-26` | Modify | Remove `anthropic`, keep `openai` |
| `.env.example:19-20,44` | Modify | Swap env var names + default provider |
| `tests/unit/test_openrouter_selector.py` | **Create** | Mock HTTP via `respx`, parse + error paths |
| `tests/unit/test_llm_factory.py` | **Create** | Factory returns Null vs OpenRouter based on settings |

---

## Risks and Mitigation

| Risk | Severity | Mitigation |
|------|----------|------------|
| Anthropic-routed models don't honor OpenAI's `response_format` param | Medium | Drop the param; enforce JSON via system prompt; use tolerant `_extract_json()` parser that strips ```json fences and leading prose. Works for all model families (Anthropic, OpenAI, Google). |
| API key leaked in chat history | **High** | User rotates key at https://openrouter.ai/keys after migration; plan uses placeholders only |
| Breaking change for anyone with existing `.env` using `ANTHROPIC_API_KEY` | Low | Document in commit message / README; single-tenant app per pyproject description, low blast radius |
| `openai` SDK version drift with OpenRouter endpoints | Low | Pin current range `>=1.57.0,<2.0.0`; integration tested via `respx` unit tests |
| Rate limiting from OpenRouter without attribution headers | Low | Optional `HTTP-Referer` / `X-Title` headers configurable via env; defaults populated |
| Missing prompt file currently causes runtime crash (latent bug) | **High** | Phase 1.4 creates it; without this, any call to `select()` raises `FileNotFoundError` — this plan fixes a pre-existing bug |

---

## Verification Checklist

Before marking complete:
- [ ] `grep -r "anthropic\|ANTHROPIC" src/ tests/` returns zero matches
- [ ] `grep -r "OPENAI_API_KEY\|openai_api_key" src/ tests/` returns zero matches (OpenRouter uses `openrouter_api_key`)
- [ ] `ruff check src tests` passes
- [ ] `mypy src` passes
- [ ] `pytest` passes with ≥ 80% coverage on `src/darth_schwader/ai/llm/`
- [ ] `.env.example` has new `OPENROUTER_*` vars and no `ANTHROPIC_*`/`OPENAI_API_KEY`
- [ ] `pyproject.toml` no longer depends on `anthropic`
- [ ] New prompt file emits valid JSON schema instructions
- [ ] User has rotated the leaked API key

---

## User Setup Steps (after code merge)

```bash
cd software/darth-schwader
pip install -e ".[dev]"                        # Reinstall to drop anthropic
# Edit .env:
#   OPENROUTER_API_KEY=sk-or-v1-<NEW_ROTATED_KEY>
#   OPENROUTER_MODEL=anthropic/claude-3.5-sonnet  (or openai/gpt-4o, google/gemini-2.0-flash-exp, etc.)
pytest                                         # verify green
```

---

## SESSION_ID (for /ccg:execute use)
- CODEX_SESSION: (not invoked — task is focused backend config migration)
- GEMINI_SESSION: (not invoked — no frontend impact)

---
