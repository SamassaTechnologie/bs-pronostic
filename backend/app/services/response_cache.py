"""Cache mémoire des réponses publiques coûteuses (tableau de bord, bilan, statistiques…).

Le serveur gratuit ne dispose que de 0,15 processeur : recalculer le tableau de bord à chaque clic prend plusieurs
secondes. Les réponses sont gardées 90 secondes au plus et effacées dès qu'une analyse, un règlement ou une
synchronisation modifie les données. Le direct, l'assistant, les paris et l'administration ne sont jamais mis en cache.
"""
from __future__ import annotations

import re
import threading
import time

TTL = 90.0
MAX_ITEMS = 300
CACHEABLE = re.compile(
    r"^/api/(dashboard|meta|track-record|public-summary|calibration|competitions(/[A-Za-z0-9_-]+)?|stats(/[a-z0-9-]+)?"
    r"|predictions|matches|history|performance|recent-results|teams/\d+|matches/\d+(/insights)?)$")
_lock = threading.Lock()
_store: dict[str, tuple[float, int, bytes, str]] = {}
_gen = 0


def ttl() -> float:
    from ..config import get_settings
    return float(get_settings().response_cache_seconds)


def get(key: str):
    if ttl() <= 0:
        return None
    with _lock:
        hit = _store.get(key)
        if hit and time.monotonic() - hit[0] < ttl():
            return hit
        _store.pop(key, None)
        return None


def put(key: str, status: int, body: bytes, ctype: str, gen: int) -> None:
    if ttl() <= 0:
        return
    with _lock:
        if gen != _gen:  # données modifiées pendant le calcul : on ne garde pas une réponse périmée
            return
        if len(_store) >= MAX_ITEMS:
            for k in sorted(_store, key=lambda k: _store[k][0])[: MAX_ITEMS // 3]:
                _store.pop(k, None)
        _store[key] = (time.monotonic(), status, body, ctype)


def generation() -> int:
    return _gen


def clear() -> None:
    global _gen
    with _lock:
        _store.clear()
        _gen += 1
