"""Analyse d'avant-match rédigée par IA, strictement fondée sur le dossier de données SAM.

Principes :
1. L'IA ne reçoit que des données réelles déjà calculées par SAM (probabilités, forme, confrontations, classement,
   tendances, absences, cotes) et ne doit rien y ajouter.
2. L'IA ne produit aucune probabilité : elle choisit un marché parmi ceux du dossier, et la probabilité affichée
   reste celle du moteur SAM.
3. Chaque nombre écrit par l'IA doit exister dans le dossier, et un pourcentage doit correspondre à un champ
   exprimé en pourcentage ; une phrase contenant un chiffre introuvable est rejetée (une nouvelle rédaction est demandée, puis les phrases fautives sont retirées).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from ..engine.markets import market_label

SCHEMA: dict = {
    "type": "object",
    "properties": {
        "titre": {"type": "string", "description": "Titre accrocheur et sobre, 90 caractères maximum"},
        "resume": {"type": "string", "description": "Synthèse en 2 ou 3 phrases"},
        "contexte": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4,
                     "description": "Classement, dynamique, enjeu visible au classement"},
        "analyse_domicile": {"type": "string", "description": "Forces et faiblesses de l'équipe à domicile"},
        "analyse_exterieur": {"type": "string", "description": "Forces et faiblesses de l'équipe à l'extérieur"},
        "confrontations": {"type": "string", "description": "Lecture des confrontations directes, ou absence de données"},
        "scenario": {"type": "string", "description": "Scénario de match le plus probable selon les données"},
        "pronostic_principal": {
            "type": "object",
            "properties": {"cle": {"type": "string", "description": "Clé exacte d'un marché du dossier"},
                           "argument": {"type": "string"}},
            "required": ["cle", "argument"],
        },
        "alternatives": {
            "type": "array", "maxItems": 2,
            "items": {"type": "object",
                      "properties": {"cle": {"type": "string"}, "argument": {"type": "string"}},
                      "required": ["cle", "argument"]},
        },
        "points_de_vigilance": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
    },
    "required": ["titre", "resume", "contexte", "analyse_domicile", "analyse_exterieur", "confrontations",
                 "scenario", "pronostic_principal", "alternatives", "points_de_vigilance"],
}

SYSTEM_PROMPT = """Tu es l'analyste football de SAM-Prédiction (slogan : « L'analyse avant le pronostic. »).
Tu rédiges en français une analyse d'avant-match professionnelle, claire et structurée, À PARTIR DU SEUL DOSSIER JSON
fourni, produit par le moteur statistique SAM.

Règles absolues :
1. N'utilise aucune information extérieure au dossier : pas de blessure, transfert, entraîneur, météo, enjeu, série
   ou actualité que le dossier ne contient pas. Tes connaissances générales sur les clubs ne comptent pas.
2. N'invente aucun chiffre. Chaque nombre que tu écris doit figurer tel quel dans le dossier (probabilités en %,
   buts attendus, points, positions, scores, fréquences, cotes). Si tu n'es pas sûr d'un nombre, n'en mets pas.
3. Ne calcule pas de nouvelle probabilité et ne modifie pas celles du dossier.
4. Si une donnée manque (par exemple « absences » : « non disponible »), dis-le sobrement sans spéculer.
5. « pronostic_principal.cle » et « alternatives[].cle » doivent être des clés exactes de « marches » ; choisis de
   préférence parmi « pronostics_sam ». Les alternatives doivent porter sur des marchés différents du principal.
6. Ton neutre et prudent : aucune garantie de gain, aucune incitation à parier, pas de superlatifs.
7. Phrases courtes et précises, sans markdown ni émoji. Écris les nombres décimaux avec une virgule (1,85).
8. Si le dossier signale un match à éviter ou une confiance faible, mets-le en avant dans les points de vigilance."""


def _pct(p: Optional[float]) -> Optional[int]:
    return round(p * 100) if p is not None else None


def build_dossier(match: dict, payload: dict, insights: dict, value_keys: set, featured_keys: set) -> dict:
    """Dossier compact (quelques milliers de caractères) transmis à l'IA."""
    home, away = match["home"]["name"], match["away"]["name"]
    markets = [mk for mk in payload.get("markets", []) if mk.get("available")]
    by_key = {mk["key"]: mk for mk in markets}
    picks = payload.get("picks") or []

    def market_row(mk: dict) -> dict:
        row = {"cle": mk["key"], "marche": mk["label"], "probabilite_pct": _pct(mk["probability"]),
               "confiance_sur_100": mk["confidence"]["score"]}
        if mk.get("odds"):
            row["cote_bookmaker"] = round(mk["odds"], 2)
        else:
            row["cote_juste_sam"] = round(1 / mk["probability"], 2)
        return row

    keys_sam = list(dict.fromkeys([*picks, *[k for k in by_key if (match["id"], k) in value_keys | featured_keys]]))
    pronos = []
    for k in keys_sam:
        if k in by_key:
            row = market_row(by_key[k])
            row["statut"] = ("Sélection SAM du jour" if (match["id"], k) in featured_keys else
                             "Pronostic à cote" if (match["id"], k) in value_keys else "Pronostic retenu")
            pronos.append(row)

    main_keys = ["1", "X", "2", "1X", "X2", "12", "O1.5", "O2.5", "U2.5", "O3.5", "U3.5", "BTTS_Y", "BTTS_N",
                 "HT_O0.5", "HT_U1.5", "C_O8.5", "C_O9.5", "K_O3.5", "K_O4.5"]
    marches = [market_row(by_key[k]) for k in main_keys if k in by_key]
    extra = [market_row(mk) for k, mk in by_key.items() if k in keys_sam and k not in main_keys]

    st = payload.get("standings") or {}

    def standing(side: str) -> Any:
        r = st.get(side) if isinstance(st, dict) else None
        if not r:
            return "non disponible"
        return {"position": r.get("position"), "points": r.get("points"), "matchs_joues": r.get("played"),
                "difference_de_buts": r.get("goal_difference")}

    def form(rows: list[dict], n: int = 6) -> dict:
        rows = rows[:n]
        if not rows:
            return {"matchs": "non disponible"}
        res = [r["result"] for r in rows]
        return {
            "derniers_matchs": [{"date": r["date"][:10], "adversaire": r["opponent"]["name"],
                                 "lieu": "domicile" if r["venue"] == "home" else "extérieur",
                                 "score_domicile_exterieur": r["score"], "resultat": r["result"]} for r in rows],
            "bilan": {"matchs": len(rows), "victoires": res.count("V"), "nuls": res.count("N"),
                      "defaites": res.count("D"), "buts_marques": sum(r["goals_for"] for r in rows),
                      "buts_encaisses": sum(r["goals_against"] for r in rows)},
        }

    inj = payload.get("injuries")
    if inj is None:
        absences: Any = "non disponible (source non configurée)"
    else:
        absences = {name: ([f"{i['player']} ({i.get('reason') or i.get('type') or 'absent'})" for i in inj.get(side) or []]
                           or "aucune absence signalée")
                    for side, name in (("home", home), ("away", away))}

    h2h = insights.get("h2h") or {}
    eg = payload.get("expected_goals") or {}
    ec = payload.get("expected_corners")
    ek = payload.get("expected_cards")
    kickoff = datetime.fromisoformat(match["kickoff"])
    return {
        "match": {"domicile": home, "exterieur": away, "competition": match["competition"]["name"],
                  "pays": match["competition"]["country"], "date_utc": kickoff.strftime("%Y-%m-%d"),
                  "heure_utc": kickoff.strftime("%H:%M")},
        "modele": {
            "buts_attendus": {home: round(eg["home"], 2), away: round(eg["away"], 2)} if eg else "non disponible",
            "corners_attendus": ({home: round(ec["home"], 1), away: round(ec["away"], 1),
                                  "total": round(ec["home"] + ec["away"], 1)} if ec else "non disponible"),
            "cartons_attendus": ({"total": round(ek["home"] + ek["away"], 1)} if ek else "non disponible"),
            "scores_les_plus_probables": [{"score": s["score"], "probabilite_pct": _pct(s["probability"])}
                                          for s in (payload.get("top_scores") or [])[:3]],
            "confiance_globale_sur_100": payload.get("match_confidence"),
            "match_a_eviter": payload.get("avoid_reasons") or "non",
        },
        "pronostics_sam": pronos or "aucun pronostic retenu par SAM pour ce match",
        "marches": marches + extra,
        "classement": {home: standing("home"), away: standing("away")},
        "forme": {home: form((insights.get("form") or {}).get("home") or []),
                  away: form((insights.get("form") or {}).get("away") or [])},
        "confrontations_directes": ({"matchs": h2h["n"], f"victoires_{home}": h2h["home_wins"], "nuls": h2h["draws"],
                                     f"victoires_{away}": h2h["away_wins"], "moyenne_buts": h2h["avg_goals"],
                                     "plus_de_2_5_buts_pct": _pct(h2h["over25"]), "les_deux_marquent_pct": _pct(h2h["btts"]),
                                     "scores": [f"{x['home']} {x['score']} {x['away']} ({x['date'][:10]})"
                                                for x in h2h.get("matches", [])[:5]]}
                                    if h2h.get("n") else "aucune confrontation en base"),
        "tendances": [t["text"] for t in (insights.get("trends") or [])[:8]] or "aucune tendance marquante",
        "absences": absences,
        "limites_des_donnees": (payload.get("data_quality") or {}).get("limits", []),
    }


# ---------------------------------------------------------------------------
# Vérification des nombres

_NUM = re.compile(r"(?<![\w])(\d+(?:[.,]\d+)?)")
ALWAYS_OK = {"0", "1", "2", "3", "0.5", "1.5", "2.5", "3.5", "4.5", "5.5", "6.5", "7.5", "8.5", "9.5", "10.5", "100"}


def _norm(n: str) -> str:
    n = n.replace(",", ".")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    return n


def allowed_numbers(dossier: Any) -> set[str]:
    out: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                walk(k)
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, bool) or v is None:
            return
        elif isinstance(v, (int, float)):
            v = abs(v)  # le signe « - » n'est pas lu avec le nombre (« -7 » → « 7 »)
            out.add(_norm(f"{v}"))
            if isinstance(v, float):
                out.add(_norm(f"{v:.1f}"))
                out.add(_norm(f"{v:.2f}"))
        elif isinstance(v, str):
            for m in _NUM.findall(v):
                out.add(_norm(m))
    walk(dossier)
    return out | ALWAYS_OK


_PCT = re.compile(r"(?<![\w])(\d+(?:[.,]\d+)?)\s?%")


def allowed_percents(dossier: Any) -> set[str]:
    """Valeurs autorisées devant un « % » : uniquement les champs exprimés en pourcentage dans le dossier."""
    out: set[str] = set()

    def walk(v: Any, key: str = "") -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, str(k))
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x, key)
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and ("pct" in key or "confiance" in key):  # confiance /100 lisible en %
            out.add(_norm(f"{v}"))
        elif isinstance(v, str):
            out.update(_norm(m) for m in _PCT.findall(v))
    walk(dossier)
    return out | {"0", "100"}


def unverified_numbers(text: str, allowed: set[str], percents: Optional[set[str]] = None) -> list[str]:
    bad = [m for m in _NUM.findall(text) if _norm(m) not in allowed]
    if percents is not None:
        bad += [f"{m} %" for m in _PCT.findall(text) if _norm(m) not in percents and _norm(m) in allowed]
    return bad


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def check_output(out: dict, dossier: dict, market_keys: set[str]) -> list[str]:
    """Problèmes détectés (liste vide = conforme)."""
    problems: list[str] = []
    for f in SCHEMA["required"]:
        if f not in out:
            problems.append(f"champ manquant : {f}")
    allowed, percents = allowed_numbers(dossier), allowed_percents(dossier)
    for txt in iter_texts(out):
        bad = unverified_numbers(txt, allowed, percents)
        if bad:
            problems.append(f"chiffres absents du dossier ({', '.join(sorted(set(bad)))}) dans : « {txt[:90]} »")
    pp = out.get("pronostic_principal") or {}
    if pp.get("cle") not in market_keys:
        problems.append(f"pronostic_principal.cle « {pp.get('cle')} » n'est pas une clé de « marches »")
    for alt in out.get("alternatives") or []:
        if alt.get("cle") not in market_keys:
            problems.append(f"alternative « {alt.get('cle')} » n'est pas une clé de « marches »")
    return problems


def iter_texts(out: dict):
    for k in ("titre", "resume", "analyse_domicile", "analyse_exterieur", "confrontations", "scenario"):
        if isinstance(out.get(k), str):
            yield out[k]
    for k in ("contexte", "points_de_vigilance"):
        for x in out.get(k) or []:
            if isinstance(x, str):
                yield x
    for x in [out.get("pronostic_principal") or {}, *(out.get("alternatives") or [])]:
        if isinstance(x, dict) and isinstance(x.get("argument"), str):
            yield x["argument"]


def sanitize(out: dict, dossier: dict, market_keys: set[str]) -> tuple[dict, int]:
    """Retire les phrases aux chiffres invérifiables et les marchés inconnus. Renvoie (contenu, nb retiré)."""
    allowed, percents = allowed_numbers(dossier), allowed_percents(dossier)
    removed = 0
    dropped: list[dict] = []

    def clean(text: Any) -> str:
        nonlocal removed
        if not isinstance(text, str):
            return ""
        keep = []
        for s in _sentences(text):
            bad = unverified_numbers(s, allowed, percents)
            if bad:
                removed += 1
                dropped.append({"phrase": s, "chiffres": bad})
            else:
                keep.append(s)
        return " ".join(keep).strip()

    res: dict = {}
    for k in ("titre", "resume", "analyse_domicile", "analyse_exterieur", "confrontations", "scenario"):
        res[k] = clean(out.get(k))
    for k in ("contexte", "points_de_vigilance"):
        res[k] = [c for c in (clean(x) for x in (out.get(k) or [])) if c]
    pp = out.get("pronostic_principal") or {}
    res["pronostic_principal"] = ({"cle": pp["cle"], "argument": clean(pp.get("argument"))}
                                  if pp.get("cle") in market_keys else None)
    if res["pronostic_principal"] is None and pp:
        removed += 1
    alts = []
    for a in out.get("alternatives") or []:
        if isinstance(a, dict) and a.get("cle") in market_keys and a.get("cle") != (pp or {}).get("cle"):
            alts.append({"cle": a["cle"], "argument": clean(a.get("argument"))})
        else:
            removed += 1
    res["alternatives"] = alts[:2]
    res["_retire"] = dropped  # passages écartés, conservés pour l'audit (non affichés)
    return res, removed


def user_prompt(dossier: dict, feedback: Optional[list[str]] = None) -> str:
    txt = ("Dossier du match (seule source autorisée) :\n```json\n"
           + json.dumps(dossier, ensure_ascii=False, separators=(",", ":"))
           + "\n```\nRédige l'analyse d'avant-match en respectant le schéma et les règles.")
    if feedback:
        txt += ("\n\nTa réponse précédente a été refusée pour ces raisons, corrige-les :\n- "
                + "\n- ".join(feedback[:8]))
    return txt


def enrich_for_display(content: dict, payload: dict) -> dict:
    """Ajoute à chaque marché cité la probabilité, la confiance et la cote calculées par SAM (jamais par l'IA)."""
    by_key = {mk["key"]: mk for mk in payload.get("markets", []) if mk.get("available")}

    def pick(x: Optional[dict]) -> Optional[dict]:
        if not x or x.get("cle") not in by_key:
            return None
        mk = by_key[x["cle"]]
        return {"market_key": mk["key"], "label": market_label(mk["key"]), "argument": x.get("argument", ""),
                "probability": mk["probability"], "confidence": mk["confidence"],
                "odds": mk.get("odds"), "fair_odds": round(1 / mk["probability"], 2),
                "is_pick": mk["key"] in (payload.get("picks") or [])}

    out = {k: v for k, v in content.items() if k not in ("pronostic_principal", "alternatives") and not k.startswith("_")}
    out["pronostic_principal"] = pick(content.get("pronostic_principal"))
    out["alternatives"] = [a for a in (pick(x) for x in content.get("alternatives") or []) if a]
    return out
