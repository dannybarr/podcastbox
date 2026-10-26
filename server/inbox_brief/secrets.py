"""Encrypt settings secrets with a key that stays in the data directory.

The key file is created on first use and is never sent anywhere. API keys and
OAuth refresh tokens are stored as ciphertext in SQLite, not in the settings JSON.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets

from inbox_brief.config import data_dir
from inbox_brief.db import connect


def write_secret(name: str, value: str) -> None:
    payload = _seal(value.encode("utf-8"))
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO secrets (name, payload) VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET payload = excluded.payload
            """,
            (name, payload),
        )


def read_secret(name: str) -> str:
    with connect() as connection:
        row = connection.execute("SELECT payload FROM secrets WHERE name = ?", (name,)).fetchone()
    if row is None or not row["payload"]:
        return ""
    try:
        return _open(row["payload"]).decode("utf-8")
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return ""


def delete_secret(name: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM secrets WHERE name = ?", (name,))


def _key() -> bytes:
    path = data_dir() / ".secret"
    if path.exists():
        return path.read_bytes()
    raw = secrets.token_bytes(32)
    path.write_bytes(raw)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return raw


def _seal(plain: bytes) -> str:
    nonce = secrets.token_bytes(16)
    stream = _stream(_key(), nonce, len(plain))
    cipher = bytes(left ^ right for left, right in zip(plain, stream))
    mac = hmac.new(_key(), nonce + cipher, hashlib.sha256).hexdigest()
    return json.dumps({"nonce": nonce.hex(), "cipher": cipher.hex(), "mac": mac})


def _open(payload: str) -> bytes:
    data = json.loads(payload)
    nonce = bytes.fromhex(data["nonce"])
    cipher = bytes.fromhex(data["cipher"])
    expected = hmac.new(_key(), nonce + cipher, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, data["mac"]):
        raise ValueError("The stored secret could not be read.")
    stream = _stream(_key(), nonce, len(cipher))
    return bytes(left ^ right for left, right in zip(cipher, stream))


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    chunks = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < size:
        chunks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:size]
