class SummarizationMiddleware:
    def __init__(self, threshold_chars: int = 4000):
        self.threshold_chars = threshold_chars

    def before_invoke(self, messages: list[str]) -> list[str]:
        joined = "\n".join(messages)
        if len(joined) <= self.threshold_chars:
            return messages
        return ["[summary] " + joined[: self.threshold_chars // 2]]
