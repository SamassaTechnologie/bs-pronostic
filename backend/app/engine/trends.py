"""Tendances factuelles (« X n'a pas perdu lors de ses 7 derniers matchs », « +2,5 buts dans 8 des 10 derniers
matchs »…). Chaque phrase est calculée sur des matchs réels présents en base ; aucune n'est inventée.
Seules les tendances marquantes sont retenues (série d'au moins 3 matchs, ou fréquence ≥ 70 % / ≤ 20 % sur ≥ 6 matchs)."""
from __future__ import annotations

from typing import Callable, Hashable, Optional, Sequence

from .types import MatchData


def _res(m: MatchData, t: Hashable) -> str:
    gf, ga = m.goals_for(t), m.goals_against(t)
    return "V" if gf > ga else ("N" if gf == ga else "D")


def _streak(ms: Sequence[MatchData], pred: Callable[[MatchData], bool]) -> int:
    n = 0
    for m in ms:  # du plus récent au plus ancien
        if not pred(m):
            break
        n += 1
    return n


def _count(ms: Sequence[MatchData], pred: Callable[[MatchData], Optional[bool]]) -> tuple[int, int]:
    vals = [pred(m) for m in ms]
    vals = [v for v in vals if v is not None]
    return sum(vals), len(vals)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def team_trends(name: str, team: Hashable, ms: Sequence[MatchData], side: str, venue_label: str,
                venue_ms: Sequence[MatchData]) -> list[dict]:
    """Tendances d'une équipe. `ms` : derniers matchs toutes compétitions (récent d'abord) ;
    `venue_ms` : derniers matchs au même lieu (domicile ou extérieur) que le match analysé."""
    out: list[dict] = []
    if len(ms) < 5:
        return out

    def add(text: str, strength: float, market: Optional[str] = None, kind: str = "forme"):
        out.append({"text": text, "side": side, "strength": round(strength, 3), "market": market, "kind": kind})

    # Séries (toutes compétitions)
    s = _streak(ms, lambda m: _res(m, team) == "V")
    if s >= 3:
        add(f"{name} a gagné ses {s} derniers matchs", 0.6 + 0.05 * s, "1" if side == "home" else "2", "série")
    s = _streak(ms, lambda m: _res(m, team) != "D")
    if s >= 5 and not (out and out[-1]["kind"] == "série"):
        add(f"{name} est invaincu lors de ses {s} derniers matchs", 0.55 + 0.04 * s, "1X" if side == "home" else "X2", "série")
    s = _streak(ms, lambda m: _res(m, team) == "D")
    if s >= 3:
        add(f"{name} a perdu ses {s} derniers matchs", 0.6 + 0.05 * s, "X2" if side == "home" else "1X", "série")
    s = _streak(ms, lambda m: _res(m, team) != "V")
    if s >= 5 and not any(t["text"].startswith(f"{name} a perdu") for t in out):
        add(f"{name} n'a gagné aucun de ses {s} derniers matchs", 0.55 + 0.04 * s, "X2" if side == "home" else "1X", "série")
    s = _streak(ms, lambda m: m.goals_for(team) > 0)
    if s >= 6:
        add(f"{name} a marqué lors de chacun de ses {s} derniers matchs", 0.5 + 0.03 * s, "BTTS_Y", "buts")
    s = _streak(ms, lambda m: m.goals_against(team) > 0)
    if s >= 6:
        add(f"{name} a encaissé au moins un but lors de ses {s} derniers matchs", 0.5 + 0.03 * s, "BTTS_Y", "buts")

    # Au même lieu (domicile / extérieur)
    if len(venue_ms) >= 4:
        s = _streak(venue_ms, lambda m: _res(m, team) != "D")
        if s >= 4:
            add(f"{name} est invaincu lors de ses {s} derniers matchs {venue_label}", 0.55 + 0.04 * s,
                "1X" if side == "home" else "X2", "série")
        s = _streak(venue_ms, lambda m: _res(m, team) != "V")
        if s >= 4:
            add(f"{name} n'a gagné aucun de ses {s} derniers matchs {venue_label}", 0.55 + 0.04 * s,
                "X2" if side == "home" else "1X", "série")

    # Fréquences sur les 10 derniers
    last = list(ms[:10])
    n = len(last)
    checks = [
        (lambda m: m.hg + m.ag > 2.5, "plus de 2,5 buts", "moins de 3 buts", "O2.5", "U2.5"),
        (lambda m: m.hg > 0 and m.ag > 0, "les deux équipes ont marqué", "au moins une équipe n'a pas marqué", "BTTS_Y", "BTTS_N"),
        (lambda m: m.hg + m.ag > 1.5, "au moins 2 buts", "moins de 2 buts", "O1.5", None),
    ]
    for pred, yes_txt, no_txt, mk_yes, mk_no in checks:
        k, tot = _count(last, pred)
        if tot >= 6 and k / tot >= 0.7:
            add(f"{yes_txt.capitalize()} dans {k} des {tot} derniers matchs de {name}", k / tot, mk_yes, "buts")
        elif tot >= 6 and k / tot <= 0.2 and mk_no:
            add(f"{no_txt.capitalize()} dans {tot - k} des {tot} derniers matchs de {name}", 1 - k / tot, mk_no, "buts")
    k, tot = _count(last, lambda m: m.goals_against(team) == 0)
    if tot >= 6 and k / tot >= 0.5:
        add(f"{name} n'a pas encaissé de but dans {k} de ses {tot} derniers matchs", 0.5 + k / tot / 2, "BTTS_N", "buts")
    k, tot = _count(last, lambda m: m.goals_for(team) == 0)
    if tot >= 6 and k / tot >= 0.4:
        add(f"{name} n'a pas marqué dans {k} de ses {tot} derniers matchs", 0.5 + k / tot / 2, "BTTS_N", "buts")
    k, tot = _count(last, lambda m: (m.hthg + m.htag > 0) if m.hthg is not None else None)
    if tot >= 6 and k / tot >= 0.8:
        add(f"Au moins un but en 1re mi-temps dans {k} des {tot} derniers matchs de {name}", k / tot, "HT_O0.5", "mi-temps")

    # Corners et cartons (moyennes)
    cm = [m.total_corners for m in last if m.total_corners is not None]
    if len(cm) >= 6:
        avg = sum(cm) / len(cm)
        k = sum(c > 9.5 for c in cm)
        if k / len(cm) >= 0.7:
            add(f"Plus de 9,5 corners dans {k} des {len(cm)} derniers matchs de {name} ({avg:.1f} en moyenne)".replace(".", ","),
                k / len(cm), "C_O9.5", "corners")
        elif k / len(cm) <= 0.2:
            add(f"Moins de 10 corners dans {len(cm) - k} des {len(cm)} derniers matchs de {name} ({avg:.1f} en moyenne)".replace(".", ","),
                1 - k / len(cm), "C_U10.5", "corners")
    km = [m.total_cards for m in last if m.total_cards is not None]
    if len(km) >= 6:
        avg = sum(km) / len(km)
        k = sum(c > 4.5 for c in km)
        if k / len(km) >= 0.6:
            add(f"Au moins 5 cartons dans {k} des {len(km)} derniers matchs de {name} ({avg:.1f} en moyenne)".replace(".", ","),
                0.4 + k / len(km) / 2, "K_O4.5", "cartons")
    return out


def h2h_trends(home_name: str, away_name: str, home: Hashable, ms: Sequence[MatchData]) -> list[dict]:
    out: list[dict] = []
    n = len(ms)
    if n < 3:
        return out
    hw = sum(m.goals_for(home) > m.goals_against(home) for m in ms)
    d = sum(m.hg == m.ag for m in ms)
    aw = n - hw - d

    def add(text: str, strength: float, market: Optional[str]):
        out.append({"text": text, "side": "h2h", "strength": round(strength, 3), "market": market, "kind": "confrontations"})

    if hw == 0 and n >= 4:
        add(f"{home_name} n'a battu {away_name} lors d'aucune de leurs {n} dernières confrontations", 0.5 + 0.05 * n, "X2")
    if aw == 0 and n >= 4:
        add(f"{away_name} n'a battu {home_name} lors d'aucune de leurs {n} dernières confrontations", 0.5 + 0.05 * n, "1X")
    if hw / n >= 0.7:
        add(f"{home_name} a remporté {hw} des {n} dernières confrontations", hw / n, "1")
    if aw / n >= 0.7:
        add(f"{away_name} a remporté {aw} des {n} dernières confrontations", aw / n, "2")
    k = sum(m.hg + m.ag > 2.5 for m in ms)
    if k / n >= 0.7:
        add(f"Plus de 2,5 buts dans {k} des {n} dernières confrontations", k / n, "O2.5")
    elif k / n <= 0.2:
        add(f"Moins de 3 buts dans {n - k} des {n} dernières confrontations", 1 - k / n, "U2.5")
    k = sum(m.hg > 0 and m.ag > 0 for m in ms)
    if k / n >= 0.7:
        add(f"Les deux équipes ont marqué dans {k} des {n} dernières confrontations", k / n, "BTTS_Y")
    elif k / n <= 0.2:
        add(f"Au moins une équipe est restée muette dans {n - k} des {n} dernières confrontations", 1 - k / n, "BTTS_N")
    return out
