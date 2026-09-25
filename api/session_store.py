"""
Session storage for conversation history and resolved customer_id.

Uses Redis if REDIS_URL is set and reachable (survives server restarts,
works across multiple backend replicas behind a load balancer -- what
you'd actually want in production). Falls back to the in-memory dict from
earlier phases if Redis isn't available, so local development still works
with zero setup. The fallback is logged clearly rather than failing
silently, since silently losing persistence is the kind of thing that
should never happen without you knowing about it.
"""

import json
import logging
import os

logger = logging.getLogger("gsr.session_store")

REDIS_URL = os.environ.get("REDIS_URL")
SESSION_TTL_SECONDS = int(os.environ.get("GSR_SESSION_TTL_SECONDS", 60 * 60 * 4))  # 4 hours


class _InMemoryStore:
    def __init__(self):
        self._data: dict[str, dict] = {}

    def get(self, session_id: str) -> dict | None:
        return self._data.get(session_id)

    def set(self, session_id: str, session: dict):
        self._data[session_id] = session


class _RedisStore:
    def __init__(self, url: str):
        import redis
        self._client = redis.from_url(url, decode_responses=True)
        self._client.ping()  # fail fast here if Redis isn't actually reachable

    def _key(self, session_id: str) -> str:
        return f"gsr:session:{session_id}"

    def get(self, session_id: str) -> dict | None:
        raw = self._client.get(self._key(session_id))
        return json.loads(raw) if raw else None

    def set(self, session_id: str, session: dict):
        self._client.setex(self._key(session_id), SESSION_TTL_SECONDS, json.dumps(session))


def _build_store():
    if REDIS_URL:
        try:
            store = _RedisStore(REDIS_URL)
            logger.info("Session store: using Redis at %s", REDIS_URL)
            return store
        except Exception as e:
            logger.warning(
                "Session store: REDIS_URL is set but Redis is unreachable (%s) -- "
                "falling back to in-memory sessions. Conversation history will NOT "
                "survive a server restart until this is fixed.", e
            )
    else:
        logger.info("Session store: REDIS_URL not set -- using in-memory sessions "
                    "(fine for local dev; won't survive a restart or scale across replicas).")
    return _InMemoryStore()


_store = _build_store()

MAX_HISTORY_STORED = 20  # cap per-session memory growth


def get_session(session_id: str) -> dict:
    session = _store.get(session_id)
    if session is None:
        session = {"customer_id": None, "history": []}
    return session


def save_turn(session_id: str, customer_id: str | None, user_message: str, assistant_message: str) -> dict:
    """Load, update, and persist a session in one call -- the pattern every
    endpoint actually needs, so callers don't have to remember the
    get -> mutate -> set sequence themselves."""
    session = get_session(session_id)
    if customer_id and not session["customer_id"]:
        session["customer_id"] = customer_id
    session["history"].append({"role": "user", "content": user_message})
    session["history"].append({"role": "assistant", "content": assistant_message})
    session["history"] = session["history"][-MAX_HISTORY_STORED:]
    _store.set(session_id, session)
    return session
