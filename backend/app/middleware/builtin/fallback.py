class ModelFallbackMiddleware:
    def __init__(self, fallback_models: list[str] | None = None):
        self.fallback_models = fallback_models or []

    async def run(self, invoke_fn, primary_model: str, *args, **kwargs):
        errors = []
        for model_name in [primary_model] + self.fallback_models:
            try:
                return await invoke_fn(model_name, *args, **kwargs)
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")
        raise RuntimeError("All models failed: " + " | ".join(errors))
