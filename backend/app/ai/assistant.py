"""Assistant IA conversationnel de SAM-Prédiction.

L'IA répond aux questions des membres (« propose-moi le meilleur combiné », « analyse tel match »…) en appelant les
outils du moteur SAM : elle ne calcule rien elle-même. Les combinés qu'elle présente sont ceux calculés par les
outils (référencés [[C1]], [[C2]]…) et affichés avec leurs vrais chiffres ; chaque nombre du texte est contrôlé
contre les résultats des outils et la question.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.combos import generate_combos
from ..engine.markets import FAMILY_LABELS
from ..engine.value import target_combos
from ..models import Analysis, Match, Prediction, utcnow
from .analyst import _sentences, allowed_numbers, allowed_percents, build_dossier, unverified_numbers

FAMILIES = {"resultat": "result", "double_chance": "double_chance", "buts": "goals", "les_deux_marquent": "btts",
            "mi_temps_buts": "halftime", "mi_temps_resultat": "halftime_result", "corners": "corners",
            "cartons": "cards"}

SYSTEM = """Tu es l'Assistant IA de SAM-Prédiction (« L'analyse avant le pronostic. »), en français.
Tu aides les membres à comprendre les matchs et à construire des pronostics et combinés à partir du moteur
statistique SAM, auquel tu accèdes UNIQUEMENT par les outils fournis.

Règles absolues :
1. Toute donnée (match, probabilité, cote, forme, classement) doit venir d'un outil appelé dans cette conversation.
   N'utilise jamais tes connaissances générales sur les clubs, joueurs ou l'actualité.
2. Tu ne calcules aucune probabilité ni aucune cote : pour un combiné, appelle « combine_cote_cible »,
   « combine_automatique » ou « evaluer_combine ». Pour montrer un combiné, écris sa référence seule sur une
   ligne, par exemple [[C1]] : l'application affiche alors la carte complète avec les vrais chiffres.
3. Pour citer un match, écris [[M:identifiant]] (exemple [[M:9296]]) : l'application affiche un lien vers sa fiche.
4. N'écris que des nombres présents dans les résultats des outils ou dans la question. Décimaux avec une virgule.
5. Pour « tous les marchés », utilise « selections » sans filtre de famille, puis compare les familles.
6. Préfère peu de matchs dans un combiné : à cote égale, moins de sélections signifie moins de marge et moins
   de surprises. Dis-le quand c'est utile.
7. Aucune garantie de gain, aucune incitation à parier plus ; rappelle les risques avec sobriété.
8. Si les outils ne renvoient rien d'exploitable, dis-le simplement (« Données insuffisantes ») sans inventer.
9. Réponse claire et structurée : une phrase d'introduction, puis des points courts (lignes commençant par « - »),
   gras possible avec **texte**. Pas de tableau, pas de titre markdown. 180 mots au plus hors cartes.
10. Questions sans rapport avec le football ou les pronostics : réponds en une phrase que tu ne traites que ce sujet."""

TOOLS: list[dict] = [
    {"name": "lister_matchs",
     "description": "Matchs à venir analysés par SAM (identifiant, équipes, championnat, horaire, confiance, "
                    "pronostics retenus). Filtrer par équipe ou championnat si la question en cite un.",
     "parameters": {"type": "object", "properties": {
         "periode_heures": {"type": "integer", "description": "Fenêtre à partir de maintenant (6 à 72, défaut 48)"},
         "equipe": {"type": "string", "description": "Nom (partiel) d'une équipe"},
         "championnat": {"type": "string", "description": "Nom ou pays du championnat"},
         "limite": {"type": "integer", "description": "Nombre maximum (défaut 25)"}}}},
    {"name": "dossier_match",
     "description": "Dossier complet d'un match : probabilités de tous les marchés, forme, classement, "
                    "confrontations, tendances, absences, cotes.",
     "parameters": {"type": "object", "properties": {"match_id": {"type": "integer"}}, "required": ["match_id"]}},
    {"name": "selections",
     "description": "Meilleures sélections sur TOUS les matchs et marchés (résultat, double chance, buts, les deux "
                    "marquent, mi-temps, corners, cartons), triées par solidité. Filtres facultatifs.",
     "parameters": {"type": "object", "properties": {
         "periode_heures": {"type": "integer", "description": "6 à 72, défaut 48"},
         "familles": {"type": "array", "items": {"type": "string", "enum": list(FAMILIES)},
                      "description": "Familles de marchés à garder (vide = toutes)"},
         "probabilite_min_pct": {"type": "integer", "description": "Défaut 60"},
         "confiance_min": {"type": "integer", "description": "Sur 100, défaut 60"},
         "cote_min": {"type": "number"}, "cote_max": {"type": "number"},
         "equipe": {"type": "string"}, "championnat": {"type": "string"},
         "limite": {"type": "integer", "description": "Défaut 25"}}}},
    {"name": "combine_cote_cible",
     "description": "Combinés de 2 à 4 matchs différents visant une cote totale (par exemple 2), classés par chance "
                    "de passer. Renvoie des références C1, C2… à afficher.",
     "parameters": {"type": "object", "properties": {
         "cote_cible": {"type": "number", "description": "Entre 1,3 et 6"},
         "matchs_max": {"type": "integer", "description": "2 à 4, défaut 3"},
         "periode_heures": {"type": "integer", "description": "6 à 72, défaut 48"},
         "familles": {"type": "array", "items": {"type": "string", "enum": list(FAMILIES)}},
         "championnat": {"type": "string"}}, "required": ["cote_cible"]}},
    {"name": "combine_automatique",
     "description": "Combinés de N matchs : approche « prudent » (probabilité maximale) ou « valeur » (cote "
                    "supérieure à la cote juste). Renvoie des références C1, C2…",
     "parameters": {"type": "object", "properties": {
         "nb_matchs": {"type": "integer", "description": "2 à 5"},
         "approche": {"type": "string", "enum": ["prudent", "valeur"]},
         "periode_heures": {"type": "integer"}}, "required": ["nb_matchs"]}},
    {"name": "evaluer_combine",
     "description": "Calcule la probabilité réelle d'un combiné choisi (match_id + clé de marché). Deux marchés d'un "
                    "même match sont calculés ensemble, ou refusés si leur lien n'est pas modélisé.",
     "parameters": {"type": "object", "properties": {"selections": {"type": "array", "items": {
         "type": "object", "properties": {"match_id": {"type": "integer"}, "cle": {"type": "string"}},
         "required": ["match_id", "cle"]}}}, "required": ["selections"]}},
    {"name": "bilan_sam",
     "description": "Bilan réel des pronostics SAM déjà joués (réussite globale, Sélection SAM, pronostics à cote).",
     "parameters": {"type": "object", "properties": {}}},
]


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


class Toolbox:
    """Exécute les outils pour une question ; mémorise combinés et matchs cités pour l'affichage."""

    def __init__(self, db: Session):
        self.db = db
        self.now = utcnow()
        self.combos: dict[str, dict] = {}
        self.matches: dict[int, dict] = {}
        self.results: list[Any] = []
        self._settings = None

    # -- utilitaires
    @property
    def s(self) -> dict:
        if self._settings is None:
            from ..services.settings_service import get_selection_settings
            self._settings = get_selection_settings(self.db)
        return self._settings

    def _analyses(self, hours: Any) -> list[Analysis]:
        h = max(6, min(72, int(hours or 48)))
        return self.db.scalars(select(Analysis).join(Match, Analysis.match_id == Match.id).where(
            Match.kickoff > self.now + timedelta(minutes=10), Match.kickoff < self.now + timedelta(hours=h),
            Analysis.status == "ok").order_by(Match.kickoff)).unique().all()

    @staticmethod
    def _match_ok(a: Analysis, equipe: Optional[str], championnat: Optional[str]) -> bool:
        m = a.payload.get("match") or {}
        if equipe and _fold(equipe) not in _fold(f"{m['home']['name']} {m['away']['name']}"):
            return False
        if championnat:
            c = m.get("competition") or {}
            if _fold(championnat) not in _fold(f"{c.get('name')} {c.get('country')} {c.get('code')}"):
                return False
        return True

    def _remember(self, a: Analysis) -> dict:
        m = a.payload.get("match") or {}
        info = {"id": a.match_id, "home": m["home"]["name"], "away": m["away"]["name"],
                "competition": m["competition"]["name"], "kickoff": m["kickoff"]}
        self.matches[a.match_id] = info
        return info

    def _keys(self) -> tuple[set, set]:
        rows = self.db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
            Match.kickoff > self.now, (Prediction.featured.is_(True)) | (Prediction.value_pick.is_(True)))).unique().all()
        return ({(p.match_id, p.market_key) for p in rows if p.value_pick},
                {(p.match_id, p.market_key) for p in rows if p.featured})

    def _store_combo(self, c: dict) -> dict:
        ref = f"C{len(self.combos) + 1}"
        self.combos[ref] = c
        for leg in c.get("legs", []):
            mid = leg["match_id"]
            if mid not in self.matches:
                a = self.db.scalar(select(Analysis).where(Analysis.match_id == mid))
                if a:
                    self._remember(a)
        out = {"ref": ref, "nb_matchs": c.get("n_legs"), "probabilite_pct": round((c.get("probability") or 0) * 100),
               "risque": c.get("risk"),
               "selections": [{"match_id": l["match_id"], "match": l["match_label"], "marche": l["label"],
                               "probabilite_pct": round(l["probability"] * 100),
                               **({"cote": round(l["odds"], 2)} if l.get("odds") else
                                  {"cote_juste_sam": round(1 / l["probability"], 2)})} for l in c.get("legs", [])]}
        if c.get("total_odds"):
            out["cote_totale_bookmaker"] = c["total_odds"]
        if c.get("reference_odds"):
            out["cote_totale_reference"] = c["reference_odds"]
        elif c.get("fair_odds"):
            out["cote_juste_totale"] = c["fair_odds"]
        if c.get("warnings"):
            out["avertissements"] = c["warnings"][:3]
        return out

    # -- outils
    def lister_matchs(self, periode_heures=48, equipe=None, championnat=None, limite=25) -> dict:
        out = []
        for a in self._analyses(periode_heures):
            if not self._match_ok(a, equipe, championnat):
                continue
            p = a.payload
            info = self._remember(a)
            picks = [mk for mk in p.get("markets", []) if mk.get("available") and mk["key"] in (p.get("picks") or [])]
            out.append({"match_id": a.match_id, "match": f"{info['home']} – {info['away']}",
                        "championnat": info["competition"], "coup_envoi_utc": info["kickoff"][:16].replace("T", " "),
                        "confiance_sur_100": p.get("match_confidence"), "a_eviter": bool(p.get("avoid_reasons")),
                        "pronostics_sam": [{"cle": mk["key"], "marche": mk["label"],
                                            "probabilite_pct": round(mk["probability"] * 100)} for mk in picks]})
            if len(out) >= max(1, min(40, int(limite or 25))):
                break
        return {"matchs": out} if out else {"matchs": [], "note": "Aucun match analysé ne correspond"}

    def dossier_match(self, match_id) -> dict:
        from ..api.catalog import match_insights
        a = self.db.scalar(select(Analysis).where(Analysis.match_id == int(match_id)))
        if a is None or a.status != "ok":
            return {"erreur": "Données insuffisantes pour ce match"}
        self._remember(a)
        vk, fk = self._keys()
        d = build_dossier(a.payload["match"], a.payload, match_insights(a.match_id, self.db), vk, fk)
        d["match_id"] = a.match_id
        return d

    def selections(self, periode_heures=48, familles=None, probabilite_min_pct=60, confiance_min=60, cote_min=None,
                   cote_max=None, equipe=None, championnat=None, limite=25) -> dict:
        fams = {FAMILIES[f] for f in (familles or []) if f in FAMILIES}
        vk, fk = self._keys()
        rows = []
        for a in self._analyses(periode_heures):
            p = a.payload
            if p.get("avoid_reasons") or not self._match_ok(a, equipe, championnat):
                continue
            for mk in p.get("markets", []):
                if not mk.get("available") or (fams and mk["family"] not in fams):
                    continue
                prob, conf = mk["probability"], mk["confidence"]["score"]
                odds = mk.get("odds") or 1 / prob
                if prob * 100 < float(probabilite_min_pct or 0) or conf < int(confiance_min or 0):
                    continue
                if (cote_min and odds < float(cote_min)) or (cote_max and odds > float(cote_max)):
                    continue
                rows.append((prob * (0.5 + conf / 200), a, mk))
        rows.sort(key=lambda t: t[0], reverse=True)
        out = []
        for _, a, mk in rows[: max(1, min(40, int(limite or 25)))]:
            info = self._remember(a)
            key = (a.match_id, mk["key"])
            r = {"match_id": a.match_id, "match": f"{info['home']} – {info['away']}", "championnat": info["competition"],
                 "cle": mk["key"], "marche": mk["label"], "famille": FAMILY_LABELS.get(mk["family"], mk["family"]),
                 "probabilite_pct": round(mk["probability"] * 100), "confiance_sur_100": mk["confidence"]["score"]}
            if mk.get("odds"):
                r["cote_bookmaker"] = round(mk["odds"], 2)
            else:
                r["cote_juste_sam"] = round(1 / mk["probability"], 2)
            if key in fk:
                r["statut"] = "Sélection SAM du jour"
            elif key in vk:
                r["statut"] = "Pronostic à cote"
            out.append(r)
        return {"selections": out} if out else {"selections": [], "note": "Aucune sélection ne remplit ces critères"}

    def combine_cote_cible(self, cote_cible, matchs_max=3, periode_heures=48, familles=None, championnat=None) -> dict:
        from ..api.public import _target_legs
        target = max(1.3, min(6.0, float(cote_cible)))
        analyses = [a for a in self._analyses(periode_heures) if self._match_ok(a, None, championnat)]
        legs = _target_legs(analyses, self.s, self.now)
        fams = {FAMILIES[f] for f in (familles or []) if f in FAMILIES}
        if fams:
            fam_of = {(a.match_id, mk["key"]): mk["family"] for a in analyses for mk in a.payload.get("markets", [])}
            legs = [l for l in legs if fam_of.get((l.match_id, l.market_key)) in fams]
        combos = target_combos(legs, target, 2, max(2, min(4, int(matchs_max or 3))), max_results=3)
        if not combos:
            return {"combines": [], "note": "Aucune combinaison assez solide n'atteint cette cote"}
        return {"combines": [self._store_combo(c) for c in combos]}

    def combine_automatique(self, nb_matchs=3, approche="prudent", periode_heures=48) -> dict:
        from ..api.public import _leg
        legs = []
        for a in self._analyses(periode_heures):
            p = a.payload
            for mk in p.get("markets", []):
                if mk.get("available") and mk["key"] in (p.get("picks") or []):
                    legs.append(_leg(p, mk))
        mode = approche if approche in ("prudent", "valeur") else "prudent"
        combos = generate_combos(legs, max(2, min(5, int(nb_matchs))), mode, max_results=3, min_confidence=55)
        if not combos:
            return {"combines": [], "note": "Pas assez de sélections indépendantes répondant aux critères"}
        return {"combines": [self._store_combo(c) for c in combos]}

    def evaluer_combine(self, selections) -> dict:
        from ..api.public import evaluate_selections
        try:
            sel = [(int(x["match_id"]), str(x["cle"])) for x in selections or []]
        except (KeyError, TypeError, ValueError):
            return {"erreur": "Sélections invalides : match_id et cle attendus"}
        if len(sel) < 2:
            return {"erreur": "Un combiné compte au moins 2 sélections"}
        try:
            res = evaluate_selections(self.db, sel)
        except ValueError as exc:
            return {"erreur": str(exc)}
        if not res.get("valid"):
            return {"erreur": " ; ".join(res.get("errors") or ["Combinaison refusée"])}
        return {"combine": self._store_combo(res)}

    def bilan_sam(self) -> dict:
        from ..services.performance import performance

        def part(d: dict) -> dict:
            return {"pronostics_regles": d["n"], "gagnes": d["won"],
                    "reussite_pct": round(d["hit_rate"] * 100) if d["hit_rate"] is not None else None,
                    "probabilite_moyenne_annoncee_pct": round(d["avg_probability"] * 100) if d["avg_probability"] else None}
        return {"tous": part(performance(self.db)["overall"]),
                "selection_sam": part(performance(self.db, featured=True)["overall"]),
                "pronostics_a_cote": part(performance(self.db, value=True)["overall"])}

    def run(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None) if name in {t["name"] for t in TOOLS} else None
        if fn is None:
            out: dict = {"erreur": f"Outil inconnu : {name}"}
        else:
            try:
                out = fn(**{k: v for k, v in (args or {}).items() if v is not None})
            except TypeError as exc:
                out = {"erreur": f"Paramètres invalides ({exc})"}
            except Exception as exc:  # un outil en erreur ne doit pas casser la conversation
                self.db.rollback()
                out = {"erreur": f"Outil indisponible ({exc.__class__.__name__})"}
        self.results.append(out)
        return out


# ---------------------------------------------------------------------------
# Contrôle de la réponse

_REF = re.compile(r"\[\[(C\d+|M:\d+)\]\]")


def check_answer(text: str, box: Toolbox, question_context: list[str]) -> tuple[str, list[dict]]:
    """Retire les phrases aux chiffres invérifiables et les références inconnues."""
    corpus = {"outils": box.results, "contexte": question_context}
    allowed, percents = allowed_numbers(corpus), allowed_percents(corpus)
    dropped: list[dict] = []
    lines_out = []
    for line in text.splitlines():
        refs = _REF.findall(line)
        bare = _REF.sub("", line)
        bad_ref = [r for r in refs if (r.startswith("C") and r not in box.combos)
                   or (r.startswith("M:") and int(r[2:]) not in box.matches)]
        if bad_ref:
            dropped.append({"phrase": line, "references": bad_ref})
            line = _REF.sub(lambda m: "" if m.group(1) in bad_ref else m.group(0), line)
            bare = _REF.sub("", line)
        if not bare.strip():
            if line.strip():
                lines_out.append(line.strip())
            elif lines_out and lines_out[-1] != "":
                lines_out.append("")
            continue
        prefix = re.match(r"^\s*(-|\d+\.)\s+", line)
        body = line[prefix.end():] if prefix else line
        keep = []
        for s in _sentences(body):
            bad = unverified_numbers(_REF.sub("", s), allowed, percents)
            if bad:
                dropped.append({"phrase": s, "chiffres": bad})
            else:
                keep.append(s)
        if keep:
            lines_out.append(((prefix.group(0).strip() + " ") if prefix else "") + " ".join(keep))
    return "\n".join(lines_out).strip(), dropped


def references(text: str, box: Toolbox) -> dict:
    combos, matches = {}, {}
    for r in _REF.findall(text):
        if r.startswith("C") and r in box.combos:
            combos[r] = box.combos[r]
        elif r.startswith("M:") and int(r[2:]) in box.matches:
            matches[r[2:]] = box.matches[int(r[2:])]
    return {"combos": combos, "matches": matches}
