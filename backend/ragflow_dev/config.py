"""Explicit new-project configuration; no application settings or dotenv imports."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

FORBIDDEN_PROJECT = "4ca162fa-755c-4c70-b3aa-7f4166a1fb36"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANK_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
PROFILE = "minilm-l6-v2-1110a243-384"
DIMENSION = 384
TENANTS = {"a": ("synthetic-org-a", "synthetic-bot-a"),
           "b": ("synthetic-org-b", "synthetic-bot-b")}


@dataclass(frozen=True)
class Settings:
    es_url: str
    token_a: str
    token_b: str
    admin_token: str
    project_id: str

    @classmethod
    def from_env(cls):
        project = os.environ.get("RAILWAY_PROJECT_ID", "")
        expected = os.environ.get("RAGFLOW_DEV_PROJECT_ID", "")
        if not project or project == FORBIDDEN_PROJECT or project != expected:
            raise RuntimeError("ISOLATED_PROJECT_REQUIRED")
        if os.environ.get("RAGFLOW_DEV_ENGINE") != "ragflow-derived":
            raise RuntimeError("EXPLICIT_DEV_ENGINE_REQUIRED")
        url = os.environ.get("RAGFLOW_DEV_ES_URL", "")
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "ragflow-dev-elasticsearch.railway.internal"
                or parsed.port != 9200 or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise RuntimeError("PRIVATE_DEV_ELASTICSEARCH_REQUIRED")
        tokens = [os.environ.get(n, "") for n in
                  ("RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN")]
        if any(len(t) < 43 for t in tokens) or len(set(tokens)) != 3:
            raise RuntimeError("THREE_DISTINCT_STRONG_DEV_CREDENTIALS_REQUIRED")
        return cls(url, *tokens, project)
