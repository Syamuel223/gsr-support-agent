"""Password authentication and signed, expiring access tokens for the API."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime

import duckdb

from mcp_server.tools import _connect, _run_write_with_retry

TOKEN_TTL_SECONDS = 60 * 60 * 12
PASSWORD_ITERATIONS = 310_000
_secret = os.environ.get("GSR_AUTH_SECRET_KEY")
if not _secret:
    if os.environ.get("RENDER"):
        raise RuntimeError("Set GSR_AUTH_SECRET_KEY in the Render environment before starting the service.")
    # Convenient for local development. Configure a persistent random secret
    # in Render so signed-in cookies remain valid across service restarts.
    _secret = secrets.token_urlsafe(48)
SECRET_KEY = _secret.encode()


def initialize_auth_store():
    con = _connect()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS auth_credentials (
                customer_id VARCHAR PRIMARY KEY,
                email VARCHAR NOT NULL UNIQUE,
                password_hash VARCHAR NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
        """)
    finally:
        con.close()


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_token(customer_id: str) -> str:
    payload = _b64(json.dumps({"sub": customer_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_token(token: str) -> str | None:
    try:
        payload, signature = token.split(".", 1)
        expected = _b64(hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        if int(claims["exp"]) <= int(time.time()) or not claims.get("sub"):
            return None
        return str(claims["sub"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def create_account(name: str, email: str, password: str) -> dict:
    email = email.strip().lower()
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("Enter a name between 1 and 120 characters.")
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Enter a valid email address.")
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Use a password between 12 and 256 characters.")
    password_hash = _password_hash(password)
    customer_id = f"cust_{uuid.uuid4().hex[:8]}"

    def _write():
        con = _connect()
        try:
            con.execute("BEGIN TRANSACTION")
            if con.execute("SELECT 1 FROM customers WHERE lower(email) = ? LIMIT 1", [email]).fetchone():
                con.execute("ROLLBACK")
                raise ValueError("An account with that email already exists.")
            con.execute("""
                INSERT INTO customers (customer_id, name, email, city, state, signup_date, tier)
                VALUES (?, ?, ?, NULL, NULL, ?, 'regular')
            """, [customer_id, name, email, datetime.now()])
            con.execute("""
                INSERT INTO auth_credentials (customer_id, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
            """, [customer_id, email, password_hash, datetime.now()])
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except duckdb.Error:
                pass
            raise
        finally:
            con.close()

    try:
        _run_write_with_retry(_write)
    except ValueError:
        raise
    except duckdb.ConstraintException as exc:
        raise ValueError("An account with that email already exists.") from exc
    return {"customer_id": customer_id, "email": email, "name": name}


def authenticate(email: str, password: str) -> dict | None:
    con = _connect()
    try:
        row = con.execute("""
            SELECT c.customer_id, c.email, c.name, a.password_hash
            FROM auth_credentials a JOIN customers c ON c.customer_id = a.customer_id
            WHERE a.email = ?
        """, [email.strip().lower()]).fetchone()
    finally:
        con.close()
    if not row or not _verify_password(password, row[3]):
        return None
    return {"customer_id": row[0], "email": row[1], "name": row[2]}


def get_account(customer_id: str) -> dict | None:
    con = _connect()
    try:
        row = con.execute("""
            SELECT c.customer_id, c.email, c.name
            FROM auth_credentials a JOIN customers c ON c.customer_id = a.customer_id
            WHERE a.customer_id = ?
        """, [customer_id]).fetchone()
    finally:
        con.close()
    return {"customer_id": row[0], "email": row[1], "name": row[2]} if row else None
