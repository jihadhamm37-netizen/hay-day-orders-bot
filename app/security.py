"""Encryption of farm credentials, password hashing and reference numbers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken


class Vault:
    """Encrypts farm login IDs/passwords. The DB only ever sees ciphertext."""

    def __init__(self, key: str):
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        # separate key for duplicate-detection hashes, derived from the main key
        self._hkey = hashlib.sha256(b"login-hash:" + key.encode()).digest()

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode("utf-8")
        except InvalidToken as e:  # wrong key or tampered data
            raise ValueError("cannot decrypt credential — check ENCRYPTION_KEY") from e

    def login_hash(self, login: str) -> str:
        norm = login.strip().lower()
        return hmac.new(self._hkey, norm.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def hint(login: str) -> str:
        login = login.strip()
        if len(login) <= 3:
            return login[:1] + "•••"
        return login[:3] + "•••" + login[-1:]


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()


# ----------------------------------------------------------- admin passwords
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        # run a dummy hash so timing does not reveal unknown users
        hashlib.scrypt(b"x", salt=b"0" * 16, **_SCRYPT)
        return False
    _, salt_b64, dk_b64 = stored.split("$", 2)
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def hash_code(code: str, secret: str) -> str:
    return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------ references
_ALPH = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_ref(prefix: str) -> str:
    """Human-friendly unique reference, e.g. ORD-261013-7KQ2M9."""
    day = datetime.now(timezone.utc).strftime("%y%m%d")
    tail = "".join(secrets.choice(_ALPH) for _ in range(6))
    return f"{prefix}-{day}-{tail}"
