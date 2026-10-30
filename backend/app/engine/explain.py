"""Génération des explications et des facteurs favorables / défavorables.

Chaque phrase est construite à partir d'un chiffre calculé sur des données
réelles (modèle, forme récente, confrontations, cotes). Aucun texte générique
n'est inventé."""
from __future__ import annotations

from typing import Optional

from .markets import MARKET_BY_KEY, evaluate_market
from .types import MatchData

NBSP = " "

SWAP = {"1": "2", "2": "1", "1X": "X2", "X2": "1X", "X": "X", "12": "12",
        "HT_1": "HT_2", "HT_2": "HT_1", "HT_X": "HT_X"}

PHRASES = {
    "O0.5": "au moins un but", "O1.5": "au moins 2 buts", "O2.5": "au moins 3 buts",
    "O3.5": "au moins 4 buts", "U2.5": "moins de 3 buts", "U3.5": "moins de 4 buts",
    "BTTS_Y": "les deux équipes ont marqué", "BTTS_N": "au moins une équipe n'a pas marqué",
    "HT_O0.5": "au moins un but en 1re mi-temps", "HT_U1.5": "moins de 2 buts en 1re mi-temps",
    "C_O6.5": "au moins 7 corners", "C_O7.5": "au moins 8 corners", "C_O8.5": "au moins 9 corners",
    "C_O9.5": "au moins 10 corners", "C_U10.5": "moins de 11 corners",
    "K_O2.5": "au moins 3 cartons", "K_O3.5": "au moins 4 cartons", "K_O4.5": "au moins 5 cartons",
}

RESULT_PHRASES = {
    # (côté domicile, côté extérieur)
    "1": ("a gagné {k} de ses {n} derniers matchs à domicile", "a perdu {k} de ses {n} derniers matchs à l'extérieur"),
    "X": ("a fait match nul dans {k} de ses {n} derniers matchs à domicile",
          "a fait match nul dans {k} de ses {n} derniers matchs à l'extérieur"),
    "2": ("a perdu {k} de ses {n} derniers matchs à domicile", "a gagné {k} de ses {n} derniers matchs à l'extérieur"),
    "1X": ("est invaincu dans {k} de ses {n} derniers matchs à domicile",
           "n'a pas gagné {k} de ses {n} derniers matchs à l'extérieur"),
    "X2": ("n'a pas gagné {k} de ses {n} derniers matchs à domicile",
           "est invaincu dans {k} de ses {n} derniers matchs à l'extérieur"),
    "12": ("a connu un vainqueur dans {k} de ses {n} derniers matchs à domicile",
           "a connu un vainqueur dans {k} de ses {n} derniers matchs à l'extérieur"),
}


def fr(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def pct(p: float) -> str:
    return f"{round(p * 100)}{NBSP}%"


def evaluate_for_pair(key: str, m: MatchData, home_id) -> Optional[bool]:
    """Évalue un marché dans une confrontation passée, du point de vue de l'équipe
    qui reçoit aujourd'hui (inverse 1/2 si les rôles étaient inversés)."""
    if m.home_id != home_id and key in SWAP:
        key = SWAP[key]
    return evaluate_market(key, m)


def build_factors(key: str, p: float, ctx: dict) -> tuple[list[str], list[str]]:
    spec = MARKET_BY_KEY[key]
    fam = spec.family
    home, away = ctx["home_name"], ctx["away_name"]
    fav: list[tuple[int, str]] = []
    unf: list[tuple[int, str]] = []

    # 1) Cotes et valeur
    pm = ctx.get("p_market")
    if pm is not None:
        if abs(p - pm) <= 0.05:
            fav.append((1, f"Cohérent avec les cotes du marché (probabilité implicite {pct(pm)})"))
        elif pm > p + 0.05:
            fav.append((1, f"Le marché est encore plus confiant (probabilité implicite {pct(pm)})"))
        elif pm < p - 0.10:
            unf.append((1, f"Le marché est nettement moins confiant (probabilité implicite {pct(pm)})"))
    odds, edge = ctx.get("odds"), ctx.get("edge")
    if odds and edge is not None:
        if edge >= 0.03:
            fav.append((2, f"Valeur positive estimée : +{round(edge * 100)}{NBSP}% à la cote {fr(odds, 2)}"))
        elif edge <= -0.05:
            unf.append((2, f"Cote {fr(odds, 2)} inférieure à la cote juste estimée ({fr(1 / p, 2)})"))

    # 2) Fréquences récentes
    rates = ctx.get("rates") or {}
    for side, team, rate, n in (("home", home, rates.get("home_rate"), rates.get("home_n", 0)),
                                ("away", away, rates.get("away_rate"), rates.get("away_n", 0))):
        if rate is None or n < 5:
            continue
        k = round(rate * n)
        if key in RESULT_PHRASES:
            txt = f"{team} " + RESULT_PHRASES[key][0 if side == "home" else 1].format(k=k, n=n)
        elif key in PHRASES:
            txt = f"{team} : {PHRASES[key]} dans {k} de ses {n} derniers matchs"
        else:
            txt = f"{team} : sélection réalisée dans {k} de ses {n} derniers matchs"
        if rate >= 0.6:
            fav.append((3, txt))
        elif rate < 0.5:
            unf.append((3, txt))

    # 3) Valeurs attendues par le modèle
    lam, mu = ctx.get("lam"), ctx.get("mu")
    if lam is not None and mu is not None:
        tot = lam + mu
        if fam == "goals":
            line = float(key[1:])
            over = key.startswith("O")
            if (over and tot >= line + 0.5) or (not over and tot <= line - 0.4):
                fav.append((4, f"Buts attendus par le modèle : {fr(tot, 2)} au total"))
            elif (over and tot < line + 0.1) or (not over and tot > line - 0.1):
                unf.append((4, f"Buts attendus par le modèle : {fr(tot, 2)} au total (proche de la ligne)"))
        elif fam == "btts":
            low = min(lam, mu)
            if (key == "BTTS_Y" and low >= 1.15) or (key == "BTTS_N" and low <= 0.85):
                fav.append((4, f"Buts attendus : {fr(lam, 2)} pour {home}, {fr(mu, 2)} pour {away}"))
            elif (key == "BTTS_Y" and low <= 0.9) or (key == "BTTS_N" and low >= 1.2):
                unf.append((4, f"Buts attendus : {fr(lam, 2)} pour {home}, {fr(mu, 2)} pour {away}"))
        elif fam in ("result", "double_chance"):
            diff = lam - mu
            pro_home = key in ("1", "1X")
            pro_away = key in ("2", "X2")
            if (pro_home and diff >= 0.5) or (pro_away and diff <= -0.5):
                fav.append((4, f"Écart de buts attendus : {fr(lam, 2)} – {fr(mu, 2)}"))
            elif (pro_home and diff <= 0.0) or (pro_away and diff >= 0.0):
                unf.append((4, f"Écart de buts attendus défavorable : {fr(lam, 2)} – {fr(mu, 2)}"))
    exp_c = ctx.get("exp_corners")
    if fam == "corners" and exp_c:
        tot = exp_c[0] + exp_c[1]
        line = float(key[3:])
        over = key.startswith("C_O")
        if (over and tot >= line + 1.5) or (not over and tot <= line - 1.0):
            fav.append((4, f"Corners attendus : {fr(tot)} au total"))
        elif (over and tot < line + 0.5) or (not over and tot > line - 0.3):
            unf.append((4, f"Corners attendus : {fr(tot)} au total (proche de la ligne)"))
    exp_k = ctx.get("exp_cards")
    if fam == "cards" and exp_k:
        tot = exp_k[0] + exp_k[1]
        line = float(key[3:])
        if tot >= line + 1.0:
            fav.append((4, f"Cartons attendus : {fr(tot)} au total"))
        elif tot < line + 0.4:
            unf.append((4, f"Cartons attendus : {fr(tot)} au total (proche de la ligne)"))
        unf.append((9, "Arbitre non pris en compte par le modèle"))

    # 4) Confrontations directes (poids faible)
    h2h_ms = ctx.get("h2h_matches") or []
    if len(h2h_ms) >= 3:
        vals = [evaluate_for_pair(key, m, ctx["home_id"]) for m in h2h_ms]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 3:
            k = sum(vals)
            txt = f"Confrontations directes : sélection réalisée {k} fois sur {len(vals)}"
            if k / len(vals) >= 0.6:
                fav.append((5, txt))
            elif k / len(vals) < 0.4:
                unf.append((5, txt))

    # 5) Qualité des données
    n_home, n_away = ctx.get("n_home", 0), ctx.get("n_away", 0)
    for team, n in ((home, n_home), (away, n_away)):
        if n < 15:
            unf.append((6, f"Échantillon limité : {n} matchs de {team} dans la fenêtre d'analyse"))
    inj = ctx.get("injuries") or {}
    for team, cnt in ((home, inj.get("home")), (away, inj.get("away"))):
        if cnt:
            unf.append((7, f"{cnt} absence(s) signalée(s) pour {team}"))

    fav.sort(key=lambda t: t[0])
    unf.sort(key=lambda t: t[0])
    return [t for _, t in fav[:4]], [t for _, t in unf[:4]]


def explanation(key: str, p: float, tier: str, conf: dict, ctx: dict) -> str:
    fam = MARKET_BY_KEY[key].family
    home, away = ctx["home_name"], ctx["away_name"]
    tail = f"Probabilité estimée {pct(p)} (niveau {tier}), confiance {conf['level'].lower()} ({conf['score']}/100)."
    if fam in ("halftime", "halftime_result") and ctx.get("ht"):
        lh, la = ctx["ht"]
        return f"Modèle mi-temps : {fr(lh, 2)} – {fr(la, 2)} buts attendus avant la pause. {tail}"
    if fam == "corners" and ctx.get("exp_corners"):
        ch, ca = ctx["exp_corners"]
        return f"Modèle corners (binomiale négative) : {fr(ch)} pour {home}, {fr(ca)} pour {away}. {tail}"
    if fam == "cards" and ctx.get("exp_cards"):
        kh, ka = ctx["exp_cards"]
        return f"Modèle cartons : {fr(kh)} pour {home}, {fr(ka)} pour {away}. {tail}"
    lam, mu = ctx.get("lam"), ctx.get("mu")
    return f"Modèle Dixon-Coles : {fr(lam, 2)} – {fr(mu, 2)} buts attendus ({home} – {away}). {tail}"
