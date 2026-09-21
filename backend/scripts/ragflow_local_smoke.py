"""Provider-free end-to-end smoke using labeled doubles, NOT native search acceptance."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from tests_ragflow.fixtures import engine, scope
    from ragflow_derived.upstream import context
    s, e = scope(), engine()
    try:
        with patch.object(context, "num_tokens_from_string", lambda text: len(text.split())):
            e.ingest(s, "manual", "# Service manual\nEmail support responds within one business day.\n\n| Package | Price |\n| --- | --- |\n| Basic | $12 |", kind="md", title="Service manual")
            e.ingest(s, "terms", "# Terms\nCancel before renewal.", kind="md", title="Terms")
            found = asyncio.run(e.retrieve(s, "Compare price and cancellation terms"))
            pack = e.build_context(s, found)
            assert pack["sources"] and all(item.text for item in pack["evidence"])
            print(json.dumps({"mode": "synthetic fixture doubles; no native ES/tokenizer claim",
                              "ingest": "PASS", "retrieval": "PASS", "context": "PASS",
                              "citations": len(pack["sources"]), "provider_calls": 0}))
    finally:
        e.close()


if __name__ == "__main__":
    main()
