import re


class PIIMiddleware:
    EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+")
    PHONE_RE = re.compile(r"\b\d{2,4}-\d{3,4}-\d{4}\b")

    def mask(self, text: str) -> str:
        text = self.EMAIL_RE.sub("[MASKED_EMAIL]", text)
        text = self.PHONE_RE.sub("[MASKED_PHONE]", text)
        return text
