"""Cache mémoire des réponses publiques coûteuses (tableau de bord, bilan, statistiques…).

Le serveur gratuit ne dispose que de 0,15 processeur : recalculer le tableau de bord prend plusieurs secondes.
* Réponse récente (moins de 90 s, données inchangées) : servie telle quelle.
* Données modifiées (analyse, règlement, synchronisation) ou réponse plus ancienne : la version précédente est servie
  immédiatement (au plus 10 minutes d'âge) et recalculée en arrière-plan ; au-delà, le calcul est attendu.
* Les pages les plus consultées sont recalculées d'avance après chaque modification.
Le direct, l'assistant, les paris et l'administration ne sont jamais mis en cache.
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

MAX_STALE = 600.0
MAX_ITEMS = 300
CACHEABLE = re.compile(
    r"^/api/(dashboard|meta|track-record|public-summary|calibration|competitions(/[A-Za-z0-9_-]+)?|stats(/[a-z0-9-]+)?"
    r"|predictions|matches|history|performance|recent-results|teams/\d+|matches/\d+(/insights)?)$")
_lock = threading.Lock()
_store: dict[str, tuple[float, int, bytes, str, int]] = {}  # clé → (instant, statut, corps, type, génération)
_refreshing: set[str] = set()
_popular: "OrderedDict[str, float]" = OrderedDict()  # clés récemment demandées (recalcul anticipé)
_gen = 0


def ttl() -> float:
    from ..config import get_settings
    return float(get_settings().response_cache_seconds)


def lookup(key: str):
    """(entrée, état) avec état ∈ {"fresh", "stale", None}."""
    if ttl() <= 0:
        return None, None
    with _lock:
        _popular[key] = time.monotonic()
        _popular.move_to_end(key)
        while len(_popular) > 40:
            _popular.popitem(last=False)
        hit = _store.get(key)
        if not hit:
            return None, None
        age = time.monotonic() - hit[0]
        if hit[4] == _gen and age < ttl():
            return hit, "fresh"
        if age < MAX_STALE:
            return hit, "stale"
        _store.pop(key, None)
        return None, None


def claim_refresh(key: str) -> bool:
    with _lock:
        if key in _refreshing:
            return False
        _refreshing.add(key)
        return True


def release_refresh(key: str) -> None:
    with _lock:
        _refreshing.discard(key)


def put(key: str, status: int, body: bytes, ctype: str, gen: int) -> None:
    if ttl() <= 0:
        return
    with _lock:
        if gen != _gen and key in _store:  # données modifiées pendant le calcul : on garde l'ancienne marquée périmée
            return
        if len(_store) >= MAX_ITEMS:
            for k in sorted(_store, key=lambda k: _store[k][0])[: MAX_ITEMS // 3]:
                _store.pop(k, None)
        _store[key] = (time.monotonic(), status, body, ctype, gen)


def generation() -> int:
    return _gen


def popular_keys(limit: int = 8) -> list[str]:
    with _lock:
        now = time.monotonic()
        return [k for k, t in reversed(_popular.items()) if now - t < 1800][:limit]


def clear() -> None:
    """Données modifiées : les réponses deviennent périmées (servies le temps d'être recalculées), puis les pages
    les plus consultées sont recalculées d'avance."""
    global _gen
    with _lock:
        _gen += 1
    if ttl() > 0:
        try:
            from ..main import app, warm_popular
            warm_popular(app)
        except Exception:
            pass


def reset() -> None:
    global _gen
    with _lock:
        _store.clear()
        _popular.clear()
        _gen += 1
