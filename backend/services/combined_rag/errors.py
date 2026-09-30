class CombinedRetrievalError(RuntimeError):
    """A compact technical category, never a provider payload or customer text."""

    def __init__(self, category):
        self.category = category
        super().__init__("Combined retrieval failed: " + category)
