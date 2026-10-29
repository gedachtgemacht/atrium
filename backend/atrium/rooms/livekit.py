"""LiveKit access tokens (HS256 JWT). Written with the standard library to avoid another dependency."""

import base64
import hashlib
import hmac
import json
import time


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def access_token(api_key: str, api_secret: str, *, identity: str, name: str, room: str, ttl: int = 3600, can_publish: bool = True) -> str:
    now = int(time.time())
    claims = {
        "iss": api_key,
        "sub": identity,
        "name": name,
        "nbf": now - 10,
        "exp": now + ttl,
        "video": {"room": room, "roomJoin": True, "canPublish": can_publish, "canSubscribe": True,
                  "canPublishData": False, "canPublishSources": ["microphone"]},
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(claims, separators=(',', ':')).encode())}"
    sig = hmac.new(api_secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{_b64(sig)}"
