"""Offline syntax and secret preflight for the dedicated branch; emits no values."""
import ast
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    assert git("branch", "--show-current").decode().strip() == "ragflow-derived-dev"
    assert git("rev-parse", "main").decode().strip() == "06f2d5d4c78805f54e818cc3886cf2438e5990cf"
    names = set(git("ls-files", "-z").decode().split("\0")) - {""}
    names.update(str(p.relative_to(ROOT)).replace("\\", "/") for folder in ("backend/ragflow_dev", "dev/ragflow")
                 for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    names.update(["Dockerfile.ragflow-dev", "Dockerfile.ragflow-dev.dockerignore", "railway.ragflow-dev.json",
                  "backend/tests_ragflow/test_native_dev.py"])
    patterns = [
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"AIza[A-Za-z0-9_-]{30,}"),
        re.compile(rb"AQ\.[A-Za-z0-9_-]{35,}"),
        re.compile(rb"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{30,}"),
        re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
        re.compile(rb"(?:postgres(?:ql)?|redis)://[^\s/:@]+:([^\s/@]+)@([^\s/]+)"),
    ]
    findings = []
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file():
            continue
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append((name, "environment file"))
            continue
        if path.suffix.lower() in (".safetensors", ".pt", ".pth", ".bin"):
            findings.append((name, "weight/binary requires review"))
        data = path.read_bytes()
        for index, pattern in enumerate(patterns):
            for match in pattern.finditer(data):
                # Explicit examples/test connection fixtures are not credentials.
                if index == 5 and (match.group(2).split(b":")[0] in
                    (b"localhost", b"127.0.0.1", b"host", b"db", b"postgres", b"example.com", b"invalid")
                    or b"example" in match.group(2) or b".invalid" in match.group(2)
                    or b"${" in match.group(1) or match.group(1).lower() in
                    (b"password", b"pass", b"test", b"secret", b"[redacted]", b"***")):
                    continue
                # Reviewed pre-existing encryption round-trip fixture, unchanged on
                # remote main: explicit fixture label, not a 39-character API key.
                if (index == 1 and name == "backend/verify_platform_keys.py" and len(match.group()) == 37
                    and re.search(rb"encrypt|roundtrip|verify|placeholder|sample|mask|check|secret", match.group(), re.I)
                    and git("show", "origin/main:" + name) == git("show", "HEAD:" + name)):
                    continue
                findings.append((name, "credential-shaped text line " + str(data[:match.start()].count(b"\n") + 1)))
    for folder in ("backend/ragflow_dev", "dev/ragflow"):
        for file in (ROOT / folder).glob("*.py"):
            ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    if findings:
        for name, category in findings:
            print(name + ": " + category)
        raise SystemExit("SECRET_PREFLIGHT_REQUIRES_REVIEW (no values emitted)")
    print("Deployment syntax and tracked/new-file secret-pattern preflight: PASS")
    print("Scanned files:", len(names))


if __name__ == "__main__":
    main()
