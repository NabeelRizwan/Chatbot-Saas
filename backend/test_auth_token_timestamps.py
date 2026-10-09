import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from services import auth_service


class AccessTokenTimestampTests(unittest.TestCase):
    def setUp(self):
        secret = patch.object(auth_service, "JWT_SECRET", "test-signing-key-only")
        secret.start()
        self.addCleanup(secret.stop)

    def test_issued_epoch_and_ttl_match_real_clock(self):
        before = int(time.time())
        token, ttl = auth_service.create_access_token(SimpleNamespace(id=7, email="test@example.invalid"))
        after = int(time.time())
        encoded = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        self.assertLessEqual(before, payload["iat"])
        self.assertLessEqual(payload["iat"], after)
        self.assertEqual(ttl, auth_service.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        self.assertEqual(payload["exp"] - payload["iat"], ttl)
        self.assertEqual(auth_service.decode_access_token(token)["sub"], "7")

    def test_independently_signed_real_epoch_expired_token_is_rejected(self):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
        now = int(time.time())
        payload = {"sub": "7", "iss": auth_service.JWT_ISSUER, "iat": now - 100, "exp": now - 1}
        message = encode({"alg": "HS256", "typ": "JWT"}) + "." + encode(payload)
        signature = hmac.new(b"test-signing-key-only", message.encode(), hashlib.sha256).digest()
        token = message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        with self.assertRaises(HTTPException) as caught:
            auth_service.decode_access_token(token)
        self.assertEqual(caught.exception.status_code, 401)

    @unittest.skipUnless(hasattr(time, "tzset"), "Runtime does not support TZ switching")
    def test_epoch_and_expiry_in_non_utc_subprocess(self):
        # POSIX TZ avoids depending on an installed IANA timezone database.
        environment = dict(os.environ, TZ="IST-5:30", DATABASE_URL="sqlite:////tmp/auth-token-epoch-tests.db")
        code = """
import time
import unittest
time.tzset()
assert time.timezone == -19800
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'test_auth_token_timestamps.AccessTokenTimestampTests.test_issued_epoch_and_ttl_match_real_clock',
    'test_auth_token_timestamps.AccessTokenTimestampTests.test_independently_signed_real_epoch_expired_token_is_rejected',
])
result = unittest.TextTestRunner().run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
"""
        result = subprocess.run([sys.executable, "-c", code], env=environment,
                                cwd=Path(__file__).resolve().parent, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
