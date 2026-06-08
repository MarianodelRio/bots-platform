import os

from cryptography.fernet import Fernet


def _load_key() -> bytes:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY env var is required")
    return key.encode()


def encrypt(plaintext: str) -> str:
    return Fernet(_load_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return Fernet(_load_key()).decrypt(ciphertext.encode()).decode()
