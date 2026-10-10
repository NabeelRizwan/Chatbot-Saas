import unittest

from services.llama_rag.streaming import EvidenceStream


class EvidenceStreamTests(unittest.TestCase):
    def test_incomplete_destination_is_held_and_final_matches(self):
        events, checks = [], []
        validate = lambda text: text.replace("https://untrusted.test/bad", "")
        stream = EvidenceStream(events.append, validate, lambda: checks.append(True))
        stream.feed("First paragraph.\n\nMore at https://untrusted")
        self.assertEqual(events, ["First paragraph.\n\n"])
        stream.feed(".test/bad\n\nLast part.")
        stream.finish(validate(stream.raw))
        self.assertEqual("".join(events), validate(stream.raw))
        self.assertNotIn("untrusted", "".join(events))
        self.assertEqual(len(checks), 3)

    def test_revoked_scope_prevents_next_paragraph(self):
        events = []
        revoked = [False]
        def check():
            if revoked[0]:
                raise RuntimeError("revoked")
        stream = EvidenceStream(events.append, lambda text: text, check)
        stream.feed("One.\n\n")
        revoked[0] = True
        with self.assertRaisesRegex(RuntimeError, "revoked"):
            stream.feed("Two.\n\n")
        self.assertEqual(events, ["One.\n\n"])

    def test_rewritten_final_is_an_error_not_false_success(self):
        stream = EvidenceStream(lambda _: None, lambda text: text, lambda: None)
        stream.feed("One.\n\n")
        with self.assertRaisesRegex(RuntimeError, "stream_prefix_changed"):
            stream.finish("Different.")

    def test_single_paragraph_remains_buffered(self):
        events = []
        stream = EvidenceStream(events.append, lambda text: text, lambda: None)
        stream.feed("A short answer.")
        self.assertEqual(events, [])
        stream.finish("A short answer.")
        self.assertEqual(events, ["A short answer."])
