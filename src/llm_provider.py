from classes.OpenRouter import OpenRouterClient, configured_model, provider_name

_selected_model: str | None = None
_openrouter_client: OpenRouterClient | None = None


def _client():
    import ollama
    from config import get_ollama_base_url

    return ollama.Client(host=get_ollama_base_url())


def _openrouter() -> OpenRouterClient:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = OpenRouterClient()
    return _openrouter_client


def list_models() -> list[str]:
    """
    Lists eligible OpenRouter models or the local Ollama models.

    Returns:
        models (list[str]): Sorted list of model names.
    """
    if provider_name() == "openrouter":
        return [model["id"] for model in _openrouter().eligible_models()]
    response = _client().list()
    return sorted(m.model for m in response.models)


def select_model(model: str) -> None:
    """
    Sets the model to use for all subsequent generate_text calls.

    Args:
        model (str): A provider model ID, or auto for OpenRouter routing.
    """
    global _selected_model
    _selected_model = model


def get_active_model() -> str | None:
    """
    Returns the currently selected model, or None if none has been selected.
    """
    return _selected_model


def generate_text(prompt: str, model_name: str = None) -> str:
    """
    Generates text using the configured provider.

    Args:
        prompt (str): User prompt
        model_name (str): Optional model name override

    Returns:
        response (str): Generated text
    """
    model = model_name or _selected_model or configured_model()
    if provider_name() == "openrouter":
        return _openrouter().generate(prompt, model or "auto")
    if not model:
        raise RuntimeError(
            "No Ollama model selected. Call select_model() first or pass model_name."
        )

    response = _client().chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    return response["message"]["content"].strip()
