"""Platform routing: resolve a model name to its target platform."""


class UnknownPlatform(Exception):
    def __init__(self, model: str):
        super().__init__(f"no platform rule matches model '{model}'")
        self.model = model


def resolve_platform(model: str) -> str:
    """Return the platform identifier for *model*.

    Rules (evaluated in order):
    1. Empty string → UnknownPlatform.
    2. ``":"`` present in model → ``"local"`` (ollama ``name:tag`` pattern).
    3. model starts with ``"glm-"`` → ``"z.ai"``.
    4. Otherwise → UnknownPlatform.
    """
    if not model:
        raise UnknownPlatform(model)
    if ":" in model:
        return "local"
    if model.startswith("glm-"):
        return "z.ai"
    raise UnknownPlatform(model)
