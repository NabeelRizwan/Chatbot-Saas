from pathlib import Path
import socket
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Reuse existing platform dependencies only for boundary tests; never install or
# alter packages in the accepted backend environment.
sys.path.append(str(Path(__file__).resolve().parents[1] / ".venv/Lib/site-packages"))


def pytest_configure(config):
    config.addinivalue_line("markers", "p1: upstream priority-one regression")
    config.addinivalue_line("markers", "p2: upstream priority-two regression")


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    original_connect = socket.socket.connect
    def denied(sock, address):
        # Windows asyncio uses a loopback socketpair internally. Permit only
        # that stdlib call site, never arbitrary localhost/remote connections.
        import inspect
        caller = inspect.currentframe().f_back
        if (caller.f_code.co_name == "_fallback_socketpair" and
                caller.f_globals.get("__name__") == "socket" and address[0] == "127.0.0.1"):
            return original_connect(sock, address)
        raise AssertionError("No network/provider/database access in offline port tests")
    monkeypatch.setattr(socket.socket, "connect", denied)
    from ragflow_derived.upstream import context, chunking
    # No tiktoken asset download in deterministic offline tests.
    monkeypatch.setattr(context, "num_tokens_from_string", lambda text: len(text.split()))
    monkeypatch.setattr(chunking, "num_tokens_from_string", lambda text: len(text.split()))
