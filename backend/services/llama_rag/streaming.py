"""Optional paragraph delivery using the existing evidence and URL checks."""

from .client import RetrievalError


class EvidenceStream:
    def __init__(self, on_delta, validate, check):
        self.on_delta = on_delta
        self.validate = validate
        self.check = check
        self.raw = ""
        self.published = ""

    def feed(self, delta):
        self.raw += delta
        if len(self.raw) > 200_000:
            raise RetrievalError("generation_response_too_large")
        boundary = self.raw.rfind("\n\n")
        if boundary >= 0:
            # A complete paragraph cannot expose a half-written destination.
            # Validate the complete prefix so URL canonicalization stays equal
            # to the ordinary final-answer path.
            self._publish(self.validate(self.raw[:boundary + 2]))

    def _publish(self, text):
        if not text.startswith(self.published):
            raise RetrievalError("stream_prefix_changed")
        delta = text[len(self.published):]
        if delta:
            self.check()
            self.on_delta(delta)
            self.published = text

    def finish(self, validated_answer):
        self._publish(validated_answer)
