"""Modèle de force des équipes : Poisson log-linéaire régularisé, option Dixon-Coles.

Pour un match i (domicile) contre j (extérieur) :

    log λ = c + h + off_i - def_j      (valeur attendue côté domicile)
    log μ = c + off_j - def_i          (valeur attendue côté extérieur)

* `off` : capacité offensive (buts, corners obtenus, ou cartons reçus selon l'usage)
* `def` : capacité défensive (plus elle est élevée, moins l'adversaire produit)
* `c`   : niveau moyen du championnat, `h` : avantage du terrain

Estimation par maximum de vraisemblance pondérée (pondération temporelle
exponentielle : les matchs récents comptent davantage) avec un a priori gaussien
(régularisation ridge) sur `off` et `def`. Cette régularisation :
  - rend le modèle identifiable sans contrainte artificielle ;
  - évite les estimations extrêmes pour les équipes avec peu de matchs ;
  - ne favorise aucune équipe : tout le monde est ramené vers la moyenne.

Avec `dixon_coles=True`, la correction τ(x, y) de Dixon & Coles (1997) est
appliquée aux scores 0-0, 1-0, 0-1 et 1-1 (paramètre ρ estimé).

Le gradient est analytique, ce qui rend l'ajustement très rapide (≈ 10-50 ms
pour un championnat de 20 équipes sur deux saisons).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Hashable, Optional, Sequence

import numpy as np
from scipy.optimize import minimize

RHO_BOUNDS = (-0.2, 0.15)


@dataclass
class TeamModel:
    team_ids: list
    off: np.ndarray
    deff: np.ndarray
    intercept: float
    home: float
    rho: float = 0.0
    dispersion: float = 1.0
    n_matches: dict = field(default_factory=dict)
    n_total: int = 0
    converged: bool = True
    index: dict = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.index = {t: i for i, t in enumerate(self.team_ids)}

    def has_team(self, team_id: Hashable) -> bool:
        return team_id in self.index

    def team_matches(self, team_id: Hashable) -> int:
        return int(self.n_matches.get(team_id, 0))

    def rates(self, home_id: Hashable, away_id: Hashable) -> tuple[float, float]:
        i = self.index[home_id]
        j = self.index[away_id]
        lam = math.exp(self.intercept + self.home + self.off[i] - self.deff[j])
        mu = math.exp(self.intercept + self.off[j] - self.deff[i])
        return lam, mu

    def params_vector(self) -> np.ndarray:
        base = [*self.off, *self.deff, self.intercept, self.home]
        return np.array(base + [self.rho], dtype=float)


def make_objective(hi: np.ndarray, ai: np.ndarray, yh: np.ndarray, ya: np.ndarray, w: np.ndarray,
                   n: int, prec: float, dixon_coles: bool):
    """Retourne (fonction objectif -> (nll, gradient), nombre de paramètres)."""
    if dixon_coles:
        m00 = (yh == 0) & (ya == 0)
        m01 = (yh == 0) & (ya == 1)
        m10 = (yh == 1) & (ya == 0)
        m11 = (yh == 1) & (ya == 1)

    n_params = 2 * n + 2 + (1 if dixon_coles else 0)

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        off = theta[:n]
        de = theta[n:2 * n]
        c = theta[2 * n]
        h = theta[2 * n + 1]
        log_lam = c + h + off[hi] - de[ai]
        log_mu = c + off[ai] - de[hi]
        lam = np.exp(log_lam)
        mu = np.exp(log_mu)
        ll = w * (yh * log_lam - lam + ya * log_mu - mu)
        g_lam = w * (yh - lam)  # d ll / d log λ
        g_mu = w * (ya - mu)  # d ll / d log μ
        g_rho = 0.0
        if dixon_coles:
            rho = theta[2 * n + 2]
            if m00.any():
                lm = lam[m00] * mu[m00]
                t = np.maximum(1.0 - lm * rho, 1e-10)
                ll[m00] += w[m00] * np.log(t)
                g_lam[m00] += w[m00] * (-lm * rho / t)
                g_mu[m00] += w[m00] * (-lm * rho / t)
                g_rho += float(np.sum(w[m00] * (-lm / t)))
            if m01.any():
                t = np.maximum(1.0 + lam[m01] * rho, 1e-10)
                ll[m01] += w[m01] * np.log(t)
                g_lam[m01] += w[m01] * (lam[m01] * rho / t)
                g_rho += float(np.sum(w[m01] * lam[m01] / t))
            if m10.any():
                t = np.maximum(1.0 + mu[m10] * rho, 1e-10)
                ll[m10] += w[m10] * np.log(t)
                g_mu[m10] += w[m10] * (mu[m10] * rho / t)
                g_rho += float(np.sum(w[m10] * mu[m10] / t))
            if m11.any():
                t = max(1.0 - rho, 1e-10)
                ll[m11] += w[m11] * math.log(t)
                g_rho += float(np.sum(w[m11] * (-1.0 / t)))
        nll = -float(ll.sum()) + 0.5 * prec * float(off @ off + de @ de)
        grad = np.empty(n_params)
        grad[:n] = -(np.bincount(hi, g_lam, n) + np.bincount(ai, g_mu, n)) + prec * off
        grad[n:2 * n] = (np.bincount(ai, g_lam, n) + np.bincount(hi, g_mu, n)) + prec * de
        grad[2 * n] = -(g_lam.sum() + g_mu.sum())
        grad[2 * n + 1] = -g_lam.sum()
        if dixon_coles:
            grad[2 * n + 2] = -g_rho
        return nll, grad

    return objective, n_params



def fit_team_model(
    home_ids: Sequence[Hashable],
    away_ids: Sequence[Hashable],
    y_home: Sequence[float],
    y_away: Sequence[float],
    weights: Sequence[float],
    *,
    prior_sd: float = 0.5,
    dixon_coles: bool = False,
    warm_start: Optional[TeamModel] = None,
    maxiter: int = 500,
) -> TeamModel:
    """Ajuste le modèle. `y_*` peuvent être non entiers (ex. xG : quasi-vraisemblance)."""
    teams = sorted(set(home_ids) | set(away_ids), key=lambda t: str(t))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.fromiter((idx[t] for t in home_ids), dtype=np.int64, count=len(home_ids))
    ai = np.fromiter((idx[t] for t in away_ids), dtype=np.int64, count=len(away_ids))
    yh = np.asarray(y_home, dtype=float)
    ya = np.asarray(y_away, dtype=float)
    w = np.asarray(weights, dtype=float)
    if len(yh) == 0:
        raise ValueError("Aucun match pour ajuster le modèle")
    prec = 1.0 / (prior_sd ** 2)

    objective, n_params = make_objective(hi, ai, yh, ya, w, n, prec, dixon_coles)

    # Point de départ : moyennes pondérées du championnat (ou ajustement précédent).
    x0 = np.zeros(n_params)
    sw = w.sum()
    mean_h = max(float((w * yh).sum() / sw), 1e-3)
    mean_a = max(float((w * ya).sum() / sw), 1e-3)
    x0[2 * n] = math.log(mean_a)
    x0[2 * n + 1] = math.log(mean_h / mean_a)
    if dixon_coles:
        x0[2 * n + 2] = -0.05
    if warm_start is not None:
        for t, i in idx.items():
            j = warm_start.index.get(t)
            if j is not None:
                x0[i] = warm_start.off[j]
                x0[n + i] = warm_start.deff[j]
        x0[2 * n] = warm_start.intercept
        x0[2 * n + 1] = warm_start.home
        if dixon_coles:
            x0[2 * n + 2] = float(np.clip(warm_start.rho, *RHO_BOUNDS))

    bounds = [(-4.0, 4.0)] * (2 * n) + [(-5.0, 5.0), (-1.5, 1.5)]
    if dixon_coles:
        bounds.append(RHO_BOUNDS)
    res = minimize(objective, x0, jac=True, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": maxiter, "ftol": 1e-10, "gtol": 1e-6})
    theta = res.x
    off = theta[:n].copy()
    de = theta[n:2 * n].copy()
    c = float(theta[2 * n])
    h = float(theta[2 * n + 1])
    rho = float(theta[2 * n + 2]) if dixon_coles else 0.0

    # Surdispersion (Pearson) : >1 => binomiale négative pour les comptages.
    lam = np.exp(c + h + off[hi] - de[ai])
    mu = np.exp(c + off[ai] - de[hi])
    pearson = (w * ((yh - lam) ** 2 / lam + (ya - mu) ** 2 / mu)).sum() / (2.0 * sw)
    dispersion = float(np.clip(pearson, 1.0, 5.0))

    counts: dict = {}
    for t in home_ids:
        counts[t] = counts.get(t, 0) + 1
    for t in away_ids:
        counts[t] = counts.get(t, 0) + 1

    return TeamModel(
        team_ids=teams, off=off, deff=de, intercept=c, home=h, rho=rho,
        dispersion=dispersion, n_matches=counts, n_total=len(yh),
        converged=bool(res.success),
    )
