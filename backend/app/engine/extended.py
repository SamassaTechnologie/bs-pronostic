"""Marchés étendus (catalogue « bookmaker ») calculés à partir du modèle de buts SAM.

Seuls les marchés que l'on sait à la fois CALCULER (modèle de buts par mi-temps) et RÉGLER (scores final et
mi-temps des sources gratuites) sont proposés. Ceux qui exigent la chronologie des buts (prochain but, minute du
premier but, équipe menée au score…) ne le sont pas : aucune source gratuite ne fournit ces données de façon fiable.

Représentation : grille des buts par mi-temps (h1, a1, h2, a2) = domicile/extérieur en 1re et 2e mi-temps.
* Marchés sur le score final : matrice Dixon-Coles du moteur (h1 = a1 = 0, h2/a2 = score final).
* Marchés par mi-temps : lois de Poisson indépendantes 1re mi-temps (buts attendus avant la pause, propres au
  championnat) et 2e mi-temps (le reste).
Chaque marché renvoie, pour chaque case, 1 (gagné), 0 (perdu) ou -1 (remboursé, lignes asiatiques entières).
Probabilités issues du modèle, NON calibrées par backtest (contrairement aux marchés principaux) : à afficher ainsi.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from scipy.stats import poisson

N = 7  # 0..6 buts par équipe et par mi-temps (masse résiduelle négligeable)

Grid = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


@dataclass(frozen=True)
class XMarket:
    key: str  # ≤ 16 caractères, préfixe « e: »
    label: str  # {E1} / {E2} remplacés par les noms des équipes
    family: str
    fn: Callable[..., np.ndarray]
    halves: bool = False  # nécessite les buts par mi-temps


FAMILIES = {
    "res_combo": "Résultat + buts",
    "either": "Résultat ou… (l'un ou l'autre)",
    "handicap": "Handicaps",
    "totals_x": "Totaux (toutes lignes)",
    "team": "Buts par équipe",
    "margin": "Écart et victoire sans encaisser",
    "exact": "Score exact",
    "halves": "Mi-temps",
}
FAMILY_ORDER = list(FAMILIES)


def _b(x) -> np.ndarray:
    return np.asarray(x).astype(np.int8)


def _res(h, a, r: str):
    return {"1": h > a, "X": h == a, "2": h < a, "1X": h >= a, "X2": h <= a, "12": h != a}[r]


def _asian(diff: np.ndarray, line: float) -> np.ndarray:
    """diff + line > 0 gagné, = 0 remboursé (lignes entières), < 0 perdu."""
    v = diff + line
    return np.where(v > 0, 1, np.where(v == 0, -1, 0)).astype(np.int8)


def _catalog() -> list[XMarket]:
    M: list[XMarket] = []

    def add(key, label, family, fn, halves=False):
        assert len(key) <= 16, key
        M.append(XMarket(key, label, family, fn, halves))

    def ft(f):  # marché sur le score final
        return lambda h1, a1, h2, a2: f(h1 + h2, a1 + a2)

    res_lbl = {"1": "{E1} gagne", "X": "Match nul", "2": "{E2} gagne", "1X": "1X", "X2": "X2", "12": "12"}

    # Résultat + les deux équipes marquent / + total
    for r in ("1", "X", "2", "1X", "X2", "12"):
        for yes in (True, False):
            add(f"e:{r}&B{'Y' if yes else 'N'}", f"{res_lbl[r]} et les deux marquent : {'oui' if yes else 'non'}",
                "res_combo", ft(lambda h, a, r=r, y=yes: _b(_res(h, a, r) & (((h > 0) & (a > 0)) == y))))
    for r in ("1", "X", "2", "1X", "X2", "12"):
        for over in (True, False):
            add(f"e:{r}&T{'O' if over else 'U'}2.5", f"{res_lbl[r]} et {'plus' if over else 'moins'} de 2,5 buts",
                "res_combo", ft(lambda h, a, r=r, o=over: _b(_res(h, a, r) & (((h + a) > 2.5) == o))))
    # Victoire + total de l'équipe (V1 + Total 1)
    for t, side in (("1", 0), ("2", 1)):
        for line in (1.5, 2.5):
            add(f"e:V{t}&TT{line}", f"{{E{t}}} gagne et marque plus de {str(line).replace('.', ',')} buts", "res_combo",
                ft(lambda h, a, s=side, l=line: _b((h > a) & (h > l)) if s == 0 else _b((a > h) & (a > l))))
    # Double chance + total d'une équipe
    for r in ("1X", "X2", "12"):
        for t in ("1", "2"):
            for over in (True, False):
                add(f"e:{r}&T{t}{'O' if over else 'U'}1.5",
                    f"{r} et {{E{t}}} {'plus' if over else 'moins'} de 1,5 but", "res_combo",
                    ft(lambda h, a, r=r, t=t, o=over: _b(_res(h, a, r) & (((h if t == '1' else a) > 1.5) == o))))

    # « L'un ou l'autre »
    for r in ("1", "X", "2"):
        for over in (True, False):
            add(f"e:{r}|T{'O' if over else 'U'}2.5", f"{res_lbl[r]} ou {'plus' if over else 'moins'} de 2,5 buts",
                "either", ft(lambda h, a, r=r, o=over: _b(_res(h, a, r) | (((h + a) > 2.5) == o))))
        for yes in (True, False):
            add(f"e:{r}|B{'Y' if yes else 'N'}", f"{res_lbl[r]} ou les deux marquent : {'oui' if yes else 'non'}",
                "either", ft(lambda h, a, r=r, y=yes: _b(_res(h, a, r) | (((h > 0) & (a > 0)) == y))))
    for yes in (True, False):
        for over in (True, False):
            add(f"e:B{'Y' if yes else 'N'}|T{'O' if over else 'U'}2.5",
                f"Les deux marquent : {'oui' if yes else 'non'} ou {'plus' if over else 'moins'} de 2,5 buts", "either",
                ft(lambda h, a, y=yes, o=over: _b((((h > 0) & (a > 0)) == y) | (((h + a) > 2.5) == o))))

    # Handicaps européens (3 issues) et asiatiques
    for hc in (-2, -1, 1, 2):
        sign = f"{hc:+d}"
        for out, lbl in (("1", "{E1}"), ("X", "Nul"), ("2", "{E2}")):
            add(f"e:EH{sign}{out}", f"Handicap ({'{E1}'} {sign}) : {lbl}", "handicap",
                ft(lambda h, a, c=hc, o=out: _b(_res(h + c, a, o))))
    for line in (-2.5, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.5):
        s = f"{line:+.1f}".replace("+0.0", "0").replace(".0", "")
        add(f"e:AH1{s}", f"Handicap asiatique {{E1}} {s.replace('.', ',')}", "handicap",
            ft(lambda h, a, l=line: _asian(h - a, l)))
        add(f"e:AH2{s}", f"Handicap asiatique {{E2}} {s.replace('.', ',')}", "handicap",
            ft(lambda h, a, l=line: _asian(a - h, l)))

    # Totaux : lignes supplémentaires, asiatiques, 3 issues, pair/impair, multi-buts, 0-0
    for line in (4.5, 5.5):
        add(f"e:TO{line}", f"Plus de {str(line).replace('.', ',')} buts", "totals_x", ft(lambda h, a, l=line: _b(h + a > l)))
        add(f"e:TU{line}", f"Moins de {str(line).replace('.', ',')} buts", "totals_x", ft(lambda h, a, l=line: _b(h + a < l)))
    for line in (1, 2, 3, 4):
        add(f"e:ATO{line}", f"Total asiatique plus de {line}", "totals_x", ft(lambda h, a, l=line: _asian(h + a, -l)))
        add(f"e:ATU{line}", f"Total asiatique moins de {line}", "totals_x", ft(lambda h, a, l=line: _asian(-(h + a), l)))
    for line in (1, 2, 3):
        add(f"e:T3L{line}", f"Total 3 issues : moins de {line}", "totals_x", ft(lambda h, a, l=line: _b(h + a < l)))
        add(f"e:T3E{line}", f"Total 3 issues : exactement {line}", "totals_x", ft(lambda h, a, l=line: _b(h + a == l)))
        add(f"e:T3G{line}", f"Total 3 issues : plus de {line}", "totals_x", ft(lambda h, a, l=line: _b(h + a > l)))
    add("e:TEVEN", "Total de buts pair", "totals_x", ft(lambda h, a: _b((h + a) % 2 == 0)))
    add("e:TODD", "Total de buts impair", "totals_x", ft(lambda h, a: _b((h + a) % 2 == 1)))
    add("e:00Y", "Score final 0-0 : oui", "totals_x", ft(lambda h, a: _b((h == 0) & (a == 0))))
    add("e:00N", "Score final 0-0 : non", "totals_x", ft(lambda h, a: _b((h + a) > 0)))
    for lo, hi in ((0, 1), (1, 2), (1, 3), (2, 3), (2, 4), (3, 4), (3, 5), (4, 6)):
        add(f"e:MB{lo}-{hi}", f"Multi-buts : {lo} à {hi} buts", "totals_x", ft(lambda h, a, lo=lo, hi=hi: _b((h + a >= lo) & (h + a <= hi))))

    # Buts par équipe
    for t in ("1", "2"):
        g = (lambda h, a: h) if t == "1" else (lambda h, a: a)
        for line in (0.5, 1.5, 2.5):
            ls = str(line).replace(".", ",")
            add(f"e:T{t}O{line}", f"{{E{t}}} plus de {ls} buts", "team", ft(lambda h, a, g=g, l=line: _b(g(h, a) > l)))
            add(f"e:T{t}U{line}", f"{{E{t}}} moins de {ls} buts", "team", ft(lambda h, a, g=g, l=line: _b(g(h, a) < l)))
        for line in (1, 2):
            add(f"e:AT{t}O{line}", f"{{E{t}}} total asiatique plus de {line}", "team", ft(lambda h, a, g=g, l=line: _asian(g(h, a), -l)))
            add(f"e:AT{t}U{line}", f"{{E{t}}} total asiatique moins de {line}", "team", ft(lambda h, a, g=g, l=line: _asian(-g(h, a), l)))
        for line in (1, 2):
            add(f"e:T{t}3L{line}", f"{{E{t}}} : moins de {line} but(s)", "team", ft(lambda h, a, g=g, l=line: _b(g(h, a) < l)))
            add(f"e:T{t}3E{line}", f"{{E{t}}} : exactement {line} but(s)", "team", ft(lambda h, a, g=g, l=line: _b(g(h, a) == l)))
            add(f"e:T{t}3G{line}", f"{{E{t}}} : plus de {line} but(s)", "team", ft(lambda h, a, g=g, l=line: _b(g(h, a) > l)))
        add(f"e:T{t}EVEN", f"{{E{t}}} : nombre de buts pair", "team", ft(lambda h, a, g=g: _b(g(h, a) % 2 == 0)))
        add(f"e:T{t}ODD", f"{{E{t}}} : nombre de buts impair", "team", ft(lambda h, a, g=g: _b(g(h, a) % 2 == 1)))
        for n in (0, 1, 2):
            add(f"e:T{t}EX{n}", f"{{E{t}}} marque exactement {n} but{'s' if n > 1 else ''}", "team", ft(lambda h, a, g=g, n=n: _b(g(h, a) == n)))
        add(f"e:T{t}EX3+", f"{{E{t}}} marque 3 buts ou plus", "team", ft(lambda h, a, g=g: _b(g(h, a) >= 3)))
        for lo, hi in ((1, 2), (1, 3), (2, 3)):
            add(f"e:T{t}MB{lo}-{hi}", f"{{E{t}}} multi-buts : {lo} à {hi}", "team", ft(lambda h, a, g=g, lo=lo, hi=hi: _b((g(h, a) >= lo) & (g(h, a) <= hi))))

    # Écart et victoire sans encaisser
    for t in ("1", "2"):
        add(f"e:W{t}NIL", f"{{E{t}}} gagne sans encaisser de but", "margin",
            ft(lambda h, a, t=t: _b((h > a) & (a == 0)) if t == "1" else _b((a > h) & (h == 0))))
        for n in (1, 2):
            add(f"e:W{t}BY{n}", f"{{E{t}}} gagne par exactement {n} but{'s' if n > 1 else ''}", "margin",
                ft(lambda h, a, t=t, n=n: _b((h - a) == n) if t == "1" else _b((a - h) == n)))
        add(f"e:W{t}BY3+", f"{{E{t}}} gagne par 3 buts ou plus", "margin",
            ft(lambda h, a, t=t: _b((h - a) >= 3) if t == "1" else _b((a - h) >= 3)))
    add("e:ANYNIL", "Une équipe gagne sans encaisser de but", "margin", ft(lambda h, a: _b(((h > a) & (a == 0)) | ((a > h) & (h == 0)))))
    for n in (1, 2):
        add(f"e:ANYBY{n}", f"Une des équipes gagne par exactement {n} but{'s' if n > 1 else ''}", "margin", ft(lambda h, a, n=n: _b(np.abs(h - a) == n)))
    add("e:ANYBY3+", "Une des équipes gagne par 3 buts ou plus", "margin", ft(lambda h, a: _b(np.abs(h - a) >= 3)))

    # Score exact
    for i in range(5):
        for j in range(5):
            if i + j <= 6:
                add(f"e:CS{i}-{j}", f"Score exact {i}-{j}", "exact", ft(lambda h, a, i=i, j=j: _b((h == i) & (a == j))))
    add("e:CSAUT", "Score exact : autre score", "exact", ft(lambda h, a: _b((h > 4) | (a > 4) | (h + a > 6))))

    # Mi-temps (buts par mi-temps)
    for r1 in ("1", "X", "2"):
        for r2 in ("1", "X", "2"):
            add(f"e:HF{r1}/{r2}", f"Mi-temps/Fin : {r1}/{r2}", "halves",
                lambda h1, a1, h2, a2, r1=r1, r2=r2: _b(_res(h1, a1, r1) & _res(h1 + h2, a1 + a2, r2)), True)
    for r in ("1", "X", "2"):
        add(f"e:2H{r}", f"2e mi-temps : {res_lbl[r]}", "halves", lambda h1, a1, h2, a2, r=r: _b(_res(h2, a2, r)), True)
    for line in (0.5, 1.5):
        ls = str(line).replace(".", ",")
        add(f"e:2HO{line}", f"2e mi-temps : plus de {ls} but", "halves", lambda h1, a1, h2, a2, l=line: _b(h2 + a2 > l), True)
        add(f"e:2HU{line}", f"2e mi-temps : moins de {ls} but", "halves", lambda h1, a1, h2, a2, l=line: _b(h2 + a2 < l), True)
    for t in ("1", "2"):
        g1 = (lambda h1, a1: h1) if t == "1" else (lambda h1, a1: a1)
        add(f"e:SBH{t}Y", f"{{E{t}}} marque dans chaque mi-temps : oui", "halves",
            lambda h1, a1, h2, a2, g=g1: _b((g(h1, a1) > 0) & (g(h2, a2) > 0)), True)
        add(f"e:SBH{t}N", f"{{E{t}}} marque dans chaque mi-temps : non", "halves",
            lambda h1, a1, h2, a2, g=g1: _b(~((g(h1, a1) > 0) & (g(h2, a2) > 0))), True)
        win = (lambda h, a: h > a) if t == "1" else (lambda h, a: a > h)
        add(f"e:WAH{t}", f"{{E{t}}} gagne au moins une mi-temps", "halves",
            lambda h1, a1, h2, a2, w=win: _b(w(h1, a1) | w(h2, a2)), True)
        add(f"e:WBH{t}", f"{{E{t}}} gagne les deux mi-temps", "halves",
            lambda h1, a1, h2, a2, w=win: _b(w(h1, a1) & w(h2, a2)), True)
        add(f"e:W1HNW{t}", f"{{E{t}}} gagne la 1re mi-temps mais pas le match", "halves",
            lambda h1, a1, h2, a2, w=win: _b(w(h1, a1) & ~w(h1 + h2, a1 + a2)), True)
        add(f"e:FG{t}H1", f"{{E{t}}} marque son premier but en 1re mi-temps", "halves",
            lambda h1, a1, h2, a2, g=g1: _b(g(h1, a1) > 0), True)
        add(f"e:FG{t}H2", f"{{E{t}}} marque son premier but en 2e mi-temps", "halves",
            lambda h1, a1, h2, a2, g=g1: _b((g(h1, a1) == 0) & (g(h2, a2) > 0)), True)
        add(f"e:FG{t}NO", f"{{E{t}}} ne marque pas du match", "halves",
            lambda h1, a1, h2, a2, g=g1: _b((g(h1, a1) + g(h2, a2)) == 0), True)
        for k, lbl in (("1", "la 1re"), ("2", "la 2e"), ("X", "autant dans les deux")):
            add(f"e:HM{t}{k}", f"{{E{t}}} : mi-temps la plus prolifique : {lbl}", "halves",
                lambda h1, a1, h2, a2, g=g1, k=k: _b(_res(g(h1, a1), g(h2, a2), k)), True)
    for k, lbl in (("1", "la 1re"), ("2", "la 2e"), ("X", "égalité")):
        add(f"e:HM{k}", f"Mi-temps avec le plus de buts : {lbl}", "halves",
            lambda h1, a1, h2, a2, k=k: _b(_res(h1 + a1, h2 + a2, k)), True)
    add("e:BBHY", "Les deux équipes marquent dans chaque mi-temps : oui", "halves",
        lambda h1, a1, h2, a2: _b((h1 > 0) & (a1 > 0) & (h2 > 0) & (a2 > 0)), True)
    add("e:BBHN", "Les deux équipes marquent dans chaque mi-temps : non", "halves",
        lambda h1, a1, h2, a2: _b(~((h1 > 0) & (a1 > 0) & (h2 > 0) & (a2 > 0))), True)
    both_h = lambda h1, a1, h2, a2: ((h1 > 0) & (h2 > 0)).astype(int) + ((a1 > 0) & (a2 > 0)).astype(int)  # noqa: E731
    add("e:NBHY", "Aucune équipe ne marque dans les deux mi-temps", "halves", lambda *g: _b(both_h(*g) == 0), True)
    add("e:OBHY", "Une seule équipe marque dans les deux mi-temps", "halves", lambda *g: _b(both_h(*g) == 1), True)
    return M


CATALOG = _catalog()
BY_KEY = {m.key: m for m in CATALOG}


def _half_grid(lh1: float, la1: float, lh2: float, la2: float) -> tuple[Grid, np.ndarray]:
    k = np.arange(N)
    p = [poisson.pmf(k, max(l, 1e-6)) for l in (lh1, la1, lh2, la2)]
    h1, a1, h2, a2 = np.meshgrid(k, k, k, k, indexing="ij")
    prob = np.einsum("i,j,k,l->ijkl", *p)
    return (h1, a1, h2, a2), prob / prob.sum()


def _ft_grid(matrix: np.ndarray) -> tuple[Grid, np.ndarray]:
    m = matrix[:N + 4, :N + 4]
    i, j = np.meshgrid(np.arange(m.shape[0]), np.arange(m.shape[1]), indexing="ij")
    z = np.zeros_like(i)
    return (z, z, i, j), m / m.sum()


def compute(matrix: np.ndarray, lam: float, mu: float, ht: Optional[tuple[float, float]]) -> list[dict]:
    """Probabilité de gain, de remboursement et cote juste de chaque marché étendu."""
    ftg, ftp = _ft_grid(matrix)
    hg = hp = None
    if ht:
        lh1, la1 = ht
        hg, hp = _half_grid(lh1, la1, max(lam - lh1, 0.05), max(mu - la1, 0.05))
    out = []
    for mk in CATALOG:
        if mk.halves and hg is None:
            continue
        g, p = (hg, hp) if mk.halves else (ftg, ftp)
        r = mk.fn(*g)
        pw = float(p[r == 1].sum())
        pv = float(p[r == -1].sum())
        if pw <= 0.002:
            continue
        out.append({"key": mk.key, "label": mk.label, "family": mk.family, "probability": round(pw, 4),
                    "void_probability": round(pv, 4), "fair_odds": round((1 - pv) / pw, 3)})
    return out


def settle(key: str, ft_home: Optional[int], ft_away: Optional[int], ht_home: Optional[int],
           ht_away: Optional[int]) -> Optional[str]:
    """« won » / « lost » / « void » ; None si la donnée manque (mi-temps inconnue, score absent)."""
    mk = BY_KEY.get(key)
    if mk is None or ft_home is None or ft_away is None:
        return None
    if mk.halves:
        if ht_home is None or ht_away is None:
            return None
        g = (np.array(ht_home), np.array(ht_away), np.array(ft_home - ht_home), np.array(ft_away - ht_away))
    else:
        z = np.array(0)
        g = (z, z, np.array(ft_home), np.array(ft_away))
    v = int(mk.fn(*g))
    return {1: "won", 0: "lost", -1: "void"}[v]


def label_for(key: str, home: str, away: str) -> Optional[str]:
    mk = BY_KEY.get(key)
    return mk.label.replace("{E1}", home).replace("{E2}", away) if mk else None
