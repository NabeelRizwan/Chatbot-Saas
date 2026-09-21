"""Offline safety tests for the deployment-only HTTP acceptance launcher."""
import base64
import hashlib
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def job(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "dev" / "ragflow"))
    module = importlib.import_module("acceptance_job")
    from ragflow_dev.config import Settings
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: object()))
    monkeypatch.setenv("RAGFLOW_DEV_ACCEPTANCE_URL", "https://synthetic-dev.up.railway.app")
    for name, char in (("TOKEN_A", "A"), ("TOKEN_B", "B"), ("ADMIN_TOKEN", "C")):
        monkeypatch.setenv("RAGFLOW_DEV_" + name, char * 64)
    return module


def test_job_requires_explicit_phase(job, monkeypatch):
    monkeypatch.delenv("RAGFLOW_DEV_ACCEPTANCE_PHASE", raising=False)
    with pytest.raises(RuntimeError, match="EXPLICIT_ACCEPTANCE_PHASE_REQUIRED"):
        job.main()


def test_job_emits_reconstructible_bounded_nonsecret_artifact(job, monkeypatch, capsys):
    monkeypatch.setenv("RAGFLOW_DEV_ACCEPTANCE_PHASE", "initial")
    monkeypatch.setattr(job, "initial", lambda client: {"synthetic": "test " * 2000})
    job.main()
    lines = capsys.readouterr().out.splitlines()
    header = json.loads(lines[0].split(" ", 1)[1])
    parts = [line.split(" ", 3)[3] for line in lines if line.startswith("NATIVE_ACCEPTANCE_DATA ")]
    raw = base64.b64decode("".join(parts))
    assert len(parts) == header["pieces"] and all(len(p) <= 1400 for p in parts)
    assert hashlib.sha256(raw).hexdigest() == header["sha256"]
    assert json.loads(raw)["synthetic"] == "test " * 2000
    assert lines[-1] == "NATIVE_ACCEPTANCE_END initial"


def test_job_refuses_credential_in_result_before_any_output(job, monkeypatch, capsys):
    monkeypatch.setenv("RAGFLOW_DEV_ACCEPTANCE_PHASE", "initial")
    monkeypatch.setattr(job, "initial", lambda client: {"accident": "A" * 64})
    with pytest.raises(AssertionError):
        job.main()
    assert capsys.readouterr().out == ""


def test_persistence_checks_identical_context_and_citations(job, monkeypatch):
    monkeypatch.setenv("RAGFLOW_DEV_ACCEPTANCE_PHASE", "persistence")
    monkeypatch.setenv("RAGFLOW_DEV_SENTINEL_EXPECTED", json.dumps({"context": "original", "citations": []}))
    monkeypatch.setattr(job.Client, "call", lambda *args, **kw: {"context": "changed", "citations": []})
    monkeypatch.setattr(job, "verify_pack", lambda *args: None)
    with pytest.raises(AssertionError):
        job.main()
