"""Text-only OpenRouter client. No publishing, payment or shell tools."""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE = "https://openrouter.ai/api/v1"
ROOT = Path(__file__).resolve().parents[2]


class OpenRouterError(RuntimeError):
    pass


def configuration() -> dict:
    path = ROOT / "config.json"
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def setting(name: str, default):
    return os.environ.get(name.upper(), configuration().get(name, default))


def provider_name() -> str:
    name = str(setting("llm_provider", "ollama")).lower()
    if name not in {"ollama", "openrouter"}:
        raise OpenRouterError("LLM_PROVIDER must be ollama or openrouter.")
    return name


def configured_model() -> str:
    if provider_name() == "openrouter":
        return str(setting("openrouter_model", "auto"))
    return str(setting("ollama_model", ""))


def money(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OpenRouterError("A price or budget is missing or invalid.") from None
    if not result.is_finite() or result < 0:
        raise OpenRouterError("Unknown, sentinel or negative prices are not eligible.")
    return result


class OpenRouterClient:
    def __init__(self):
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        self.monthly_limit = min(money(setting("openrouter_monthly_usd", "50")), Decimal("50"))
        self.request_limit = money(setting("openrouter_max_request_usd", "0.05"))
        self.prompt_rate = money(setting("openrouter_max_prompt_per_million", "1"))
        self.completion_rate = money(setting("openrouter_max_completion_per_million", "2"))
        self.allow_paid = str(setting("openrouter_allow_paid", "false")).lower() == "true"
        self.max_tokens = int(setting("openrouter_max_tokens", "2048"))
        if not 1 <= self.max_tokens <= 8192:
            raise OpenRouterError("OPENROUTER_MAX_TOKENS must be between 1 and 8192.")
        self._catalog = None
        self.last_receipt = None

    def _request(self, path: str, payload=None, authenticated: bool = True) -> dict:
        if authenticated and not self.key:
            raise OpenRouterError("Set OPENROUTER_API_KEY in the runtime secret store.")
        headers = {"Accept": "application/json", "X-Title": "MoneyPrinterV2 task worker"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.key}"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        try:
            with urlopen(Request(API_BASE + path, data=data, headers=headers), timeout=120) as response:
                result = json.load(response)
        except HTTPError as error:
            # Provider error bodies may contain prompts. Keep them out of logs.
            raise OpenRouterError(f"OpenRouter HTTP {error.code}; no automatic POST retry.") from None
        except (URLError, TimeoutError, OSError):
            raise OpenRouterError("OpenRouter connection failed; completion outcome may be unknown.") from None
        except (ValueError, UnicodeError):
            raise OpenRouterError("OpenRouter returned an unreadable response.") from None
        if not isinstance(result, dict) or result.get("error"):
            raise OpenRouterError("OpenRouter did not return a successful response.")
        return result

    def catalog(self) -> list[dict]:
        if self._catalog is None:
            data = self._request("/models", authenticated=False).get("data")
            if not isinstance(data, list):
                raise OpenRouterError("OpenRouter model catalog is unavailable.")
            self._catalog = data
        return self._catalog

    @staticmethod
    def _prices(model: dict) -> tuple[Decimal, Decimal, Decimal]:
        pricing = model.get("pricing", {})
        return money(pricing.get("prompt")), money(pricing.get("completion")), money(pricing.get("request", 0))

    def eligible_models(self) -> list[dict]:
        eligible = []
        for model in self.catalog():
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            architecture = model.get("architecture", {})
            if "text" not in architecture.get("input_modalities", []) or architecture.get("output_modalities") != ["text"]:
                continue
            endpoints = model.get("endpoints")
            if endpoints and "/api/v1/chat/completions" not in endpoints:
                continue
            try:
                prompt, completion, request = self._prices(model)
            except OpenRouterError:
                continue
            free = prompt == completion == request == 0
            if not free and (not self.allow_paid or prompt * 1000000 > self.prompt_rate or completion * 1000000 > self.completion_rate):
                continue
            eligible.append(model)
        return sorted(eligible, key=lambda model: (sum(self._prices(model)), -int(model.get("created") or 0), model["id"]))

    def _paid_budget(self, estimated_cost: Decimal) -> None:
        if not self.allow_paid or self.monthly_limit <= 0 or estimated_cost > self.request_limit:
            raise OpenRouterError("Paid generation is outside the configured request budget.")
        info = self._request("/key").get("data", {})
        # A provider-enforced cap survives cron restarts, cache expiry and parallel clients.
        budgets = list(info.get("budgets") or [])
        if info.get("limit_reset") == "monthly" and info.get("limit") is not None:
            budgets.append({"reset_interval": "monthly", "limit_usd": info["limit"],
                            "remaining_usd": info.get("limit_remaining"), "spend_usd": info.get("usage_monthly")})
        monthly = []
        for budget in budgets:
            if budget.get("reset_interval") != "monthly":
                continue
            try:
                limit = money(budget.get("limit_usd"))
                remaining = money(budget.get("remaining_usd"))
                used = money(budget.get("spend_usd"))
            except OpenRouterError:
                continue
            if 0 < limit <= self.monthly_limit:
                monthly.append((remaining, used))
        if not monthly:
            raise OpenRouterError("Set this dedicated OpenRouter key to a monthly credit limit of at most $50 before paid generation.")
        if any(estimated_cost > remaining or used + estimated_cost > self.monthly_limit for remaining, used in monthly):
            raise OpenRouterError("The monthly OpenRouter budget has no room for this request.")

    def generate(self, prompt: str, model_name: str = "auto", kind: str = "routine") -> str:
        self.last_receipt = None
        if not isinstance(prompt, str) or not prompt.strip():
            raise OpenRouterError("A non-empty prompt is required.")
        if len(prompt.encode("utf-8")) > 100000:
            raise OpenRouterError("Split this input into smaller tasks (maximum 100KB per prompt).")
        if not self.key:
            raise OpenRouterError("Set OPENROUTER_API_KEY in the runtime secret store.")
        models = self.eligible_models()
        input_bound = len(prompt.encode("utf-8")) + 1024
        models = [model for model in models if not model.get("context_length") or input_bound + self.max_tokens <= int(model["context_length"])]
        models.sort(key=lambda model: (any(self._prices(model)),
                    self._prices(model)[0] * input_bound + self._prices(model)[1] * self.max_tokens + self._prices(model)[2],
                    -int(model.get("created") or 0), model["id"]))
        preferences = configuration().get("openrouter_routes", {}).get(kind, [])
        if not isinstance(preferences, list):
            raise OpenRouterError("Each openrouter_routes entry must be a list of model IDs.")
        if model_name and model_name != "auto":
            models = [model for model in models if model["id"] == model_name]
        elif preferences:
            order = {name: index for index, name in enumerate(preferences)}
            models.sort(key=lambda model: (any(self._prices(model)), order.get(model["id"], len(order)), sum(self._prices(model)), -int(model.get("created") or 0)))
        if not models:
            raise OpenRouterError("No text model matches the requested model and pricing policy.")
        model = models[0]
        prompt_rate, completion_rate, request_price = self._prices(model)
        free = prompt_rate == completion_rate == request_price == 0
        estimated = prompt_rate * input_bound + completion_rate * self.max_tokens + request_price
        if not free:
            self._paid_budget(estimated)
        result = self._request("/chat/completions", {
            "model": model["id"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "provider": {"sort": "price", "allow_fallbacks": True, "max_price": {
                "prompt": 0 if free else float(prompt_rate * 1000000),
                "completion": 0 if free else float(completion_rate * 1000000),
                "request": 0 if free else float(request_price), "image": 0,
            }},
            "stream": False,
        })
        usage = result.get("usage", {})
        cost = money(usage["cost"]) if usage.get("cost") is not None else None
        self.last_receipt = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "generation_id": result.get("id"), "requested_model": model["id"],
            "model": result.get("model", model["id"]), "kind": kind,
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "cost_usd": str(cost) if cost is not None else None, "free_requested": free,
        }
        state_dir = ROOT / ".mp"
        state_dir.mkdir(mode=0o700, exist_ok=True)
        receipt_path = state_dir / "openrouter_receipts.jsonl"
        with receipt_path.open("a", encoding="utf-8") as handle:
            os.chmod(receipt_path, 0o600)
            handle.write(json.dumps(self.last_receipt) + "\n")
        try:
            choice = result["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise OpenRouterError("Generation returned no text; retain its receipt before another attempt.") from None
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterError("Generation returned empty text; retain its receipt before another attempt.")
        if choice.get("finish_reason") == "length":
            raise OpenRouterError("Generation hit its output limit; retain its receipt and split the task.")
        if cost is not None and ((free and cost > 0) or cost > self.request_limit):
            raise OpenRouterError("Unexpected generation charge; retain its receipt and stop this run.")
        return content.strip()
