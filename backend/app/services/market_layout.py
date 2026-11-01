"""Organisation des marchés d'un match en onglets, blocs et grilles de cotes (présentation « bookmaker »).

Chaque marché est rangé dans un onglet (Populaires, Résultat, Buts…), un bloc (« Total », « Handicap asiatique »…),
puis sur une ligne (ex. la ligne 2,5) et dans une colonne (ex. « Plus »). Les blocs « flow » sont des listes
d'issues sans grille.
"""
from __future__ import annotations

import re
from typing import Optional

TABS = [("populaires", "Populaires"), ("resultat", "Résultat"), ("buts", "Buts"), ("handicaps", "Handicaps"),
        ("mi_temps", "Mi-temps"), ("equipes", "Équipes"), ("combines", "Combinés"), ("score", "Score exact"),
        ("corners", "Corners"), ("cartons", "Cartons")]

RES = {"1": "{E1}", "X": "Nul", "2": "{E2}", "1X": "1X", "X2": "X2", "12": "12"}


def _line(v: str) -> str:
    return v.replace(".", ",")


def place(key: str) -> Optional[tuple]:
    """(onglet, bloc, ligne, colonne) ; colonne None = bloc « flow » (ligne = libellé de l'issue)."""
    m = re.fullmatch
    if key in ("1", "X", "2"):
        return ("resultat", "1X2", "", RES[key])
    if key in ("1X", "12", "X2"):
        return ("resultat", "Double chance", "", key)
    if x := m(r"([OU])(\d\.5)", key):
        return ("buts", "Total de buts", _line(x[2]), "Plus" if x[1] == "O" else "Moins")
    if key in ("BTTS_Y", "BTTS_N"):
        return ("buts", "Les deux équipes marquent", "", "Oui" if key.endswith("Y") else "Non")
    if x := m(r"HT_([1X2])", key):
        return ("mi_temps", "1re mi-temps : résultat", "", RES[x[1]])
    if x := m(r"HT_([OU])(\d\.5)", key):
        return ("mi_temps", "1re mi-temps : total", _line(x[2]), "Plus" if x[1] == "O" else "Moins")
    if x := m(r"C_([OU])(\d+\.5)", key):
        return ("corners", "Total de corners", _line(x[2]), "Plus" if x[1] == "O" else "Moins")
    if x := m(r"K_([OU])(\d\.5)", key):
        return ("cartons", "Total de cartons", _line(x[2]), "Plus" if x[1] == "O" else "Moins")
    if not key.startswith("e:"):
        return None
    k = key[2:]
    # Combinés
    if x := m(r"(1X|X2|12|1|X|2)&B([YN])", k):
        return ("combines", "Résultat + les deux équipes marquent", RES[x[1]], "Oui" if x[2] == "Y" else "Non")
    if x := m(r"(1X|X2|12|1|X|2)&T([OU])2\.5", k):
        return ("combines", "Résultat + total 2,5", RES[x[1]], "Plus" if x[2] == "O" else "Moins")
    if x := m(r"V([12])&TT(\d\.5)", k):
        return ("combines", "Victoire + buts de l'équipe", f"{{E{x[1]}}} gagne", f"Plus de {_line(x[2])}")
    if x := m(r"(1X|X2|12)&T([12])([OU])1\.5", k):
        return ("combines", "Double chance + buts d'une équipe", f"{x[1]} et {{E{x[2]}}}",
                "Plus de 1,5" if x[3] == "O" else "Moins de 1,5")
    if x := m(r"([1X2])\|T([OU])2\.5", k):
        return ("combines", "Résultat OU total 2,5", RES[x[1]], "Plus" if x[2] == "O" else "Moins")
    if x := m(r"([1X2])\|B([YN])", k):
        return ("combines", "Résultat OU les deux marquent", RES[x[1]], "Oui" if x[2] == "Y" else "Non")
    if x := m(r"B([YN])\|T([OU])2\.5", k):
        return ("combines", "Les deux marquent OU total 2,5", "Oui" if x[1] == "Y" else "Non",
                "Plus" if x[2] == "O" else "Moins")
    # Handicaps
    if x := m(r"EH([+-]\d)([1X2])", k):
        return ("handicaps", "Handicap européen", f"{{E1}} ({x[1]})", RES[x[2]])
    if x := m(r"AH1(.+)", k):
        return ("handicaps", "Handicap asiatique", _line(x[1]) if x[1] != "0" else "0", "{E1}")
    if x := m(r"AH2(.+)", k):
        inv = {"0": "0"}.get(x[1]) or (x[1].replace("-", "+") if x[1].startswith("-") else x[1].replace("+", "-"))
        return ("handicaps", "Handicap asiatique", _line(inv), "{E2}")
    # Buts
    if x := m(r"T([OU])(\d\.5)", k):
        return ("buts", "Total de buts", _line(x[2]), "Plus" if x[1] == "O" else "Moins")
    if x := m(r"AT([OU])(\d)", k):
        return ("buts", "Total asiatique", x[2], "Plus" if x[1] == "O" else "Moins")
    if x := m(r"T3([LEG])(\d)", k):
        return ("buts", "Total 3 issues", x[2], {"L": "Moins", "E": "Exactement", "G": "Plus"}[x[1]])
    if k in ("TEVEN", "TODD"):
        return ("buts", "Total pair / impair", "", "Pair" if k == "TEVEN" else "Impair")
    if k in ("00Y", "00N"):
        return ("buts", "Score final 0-0", "", "Oui" if k == "00Y" else "Non")
    if x := m(r"MB(\d)-(\d)", k):
        return ("buts", "Multi-buts", f"{x[1]} à {x[2]} buts", None)
    # Équipes
    if x := m(r"T([12])([OU])(\d\.5)", k):
        return ("equipes", f"Total {{E{x[1]}}}", _line(x[3]), "Plus" if x[2] == "O" else "Moins")
    if x := m(r"AT([12])([OU])(\d)", k):
        return ("equipes", f"Total asiatique {{E{x[1]}}}", x[3], "Plus" if x[2] == "O" else "Moins")
    if x := m(r"T([12])3([LEG])(\d)", k):
        return ("equipes", f"{{E{x[1]}}} : total 3 issues", x[3], {"L": "Moins", "E": "Exactement", "G": "Plus"}[x[2]])
    if x := m(r"T([12])(EVEN|ODD)", k):
        return ("equipes", f"{{E{x[1]}}} : pair / impair", "", "Pair" if x[2] == "EVEN" else "Impair")
    if x := m(r"T([12])EX(\d\+?)", k):
        return ("equipes", f"{{E{x[1]}}} : nombre exact de buts", "", x[2])
    if x := m(r"T([12])MB(\d)-(\d)", k):
        return ("equipes", f"{{E{x[1]}}} : multi-buts", f"{x[2]} à {x[3]} buts", None)
    # Résultat (écart, sans encaisser)
    if x := m(r"W([12])NIL", k):
        return ("resultat", "Victoire sans encaisser", f"{{E{x[1]}}}", None)
    if k == "ANYNIL":
        return ("resultat", "Victoire sans encaisser", "Une des deux équipes", None)
    if x := m(r"W([12])BY(\d\+?)", k):
        return ("resultat", "Écart de victoire", f"{{E{x[1]}}}", f"{x[2].replace('+', ' et +')} but{'s' if x[2] != '1' else ''}")
    if x := m(r"ANYBY(\d\+?)", k):
        return ("resultat", "Écart de victoire", "Une des équipes", f"{x[1].replace('+', ' et +')} but{'s' if x[1] != '1' else ''}")
    # Score exact : trois colonnes (victoire domicile, nul, victoire extérieur)
    if x := m(r"CS(\d)-(\d)", k):
        i, j = int(x[1]), int(x[2])
        return ("score", "Score exact", None, "{E1}" if i > j else ("Nul" if i == j else "{E2}"), f"{i}-{j}")
    if k == "CSAUT":
        return ("score", "Score exact", "Autre score", None)
    # Mi-temps
    if x := m(r"HF([1X2])/([1X2])", k):
        return ("mi_temps", "Mi-temps / fin du match", f"Mi-temps {x[1]}", f"Fin {x[2]}")
    if x := m(r"2H([1X2])", k):
        return ("mi_temps", "2e mi-temps : résultat", "", RES[x[1]])
    if x := m(r"2H([OU])(\d\.5)", k):
        return ("mi_temps", "2e mi-temps : total", _line(x[2]), "Plus" if x[1] == "O" else "Moins")
    if x := m(r"SBH([12])([YN])", k):
        return ("mi_temps", "Marque dans chaque mi-temps", f"{{E{x[1]}}}", "Oui" if x[2] == "Y" else "Non")
    if k in ("BBHY", "BBHN"):
        return ("mi_temps", "Marque dans chaque mi-temps", "Les deux équipes", "Oui" if k == "BBHY" else "Non")
    if x := m(r"W([AB])H([12])", k):
        return ("mi_temps", "Gagne une ou les deux mi-temps", f"{{E{x[2]}}}", "Au moins une" if x[1] == "A" else "Les deux")
    if x := m(r"W1HNW([12])", k):
        return ("mi_temps", "Gagne la 1re mi-temps mais pas le match", f"{{E{x[1]}}}", None)
    if x := m(r"FG([12])(H1|H2|NO)", k):
        return ("mi_temps", "Premier but de l'équipe", f"{{E{x[1]}}}", {"H1": "1re MT", "H2": "2e MT", "NO": "Aucun but"}[x[2]])
    if x := m(r"HM([12])([12X])", k):
        return ("mi_temps", "Mi-temps la plus prolifique", f"{{E{x[1]}}}", {"1": "1re", "2": "2e", "X": "Égalité"}[x[2]])
    if x := m(r"HM([12X])", k):
        return ("mi_temps", "Mi-temps la plus prolifique", "Match", {"1": "1re", "2": "2e", "X": "Égalité"}[x[1]])
    if k in ("NBHY", "OBHY"):
        return ("mi_temps", "Équipes qui marquent dans les deux mi-temps",
                "Aucune" if k == "NBHY" else "Une seule", None)
    return None


def _num_key(label: str):
    try:
        return (0, float(label.replace(",", ".").split()[0].replace("(", "").replace(")", "")))
    except (ValueError, IndexError):
        return (1, label)


POPULAR_BLOCKS = ["1X2", "Double chance", "Total de buts", "Les deux équipes marquent"]


def build(rows: list[dict], home: str, away: str) -> list[dict]:
    """rows : marchés (clé, cote, probabilité…). Renvoie les onglets avec leurs blocs."""
    def names(s: str) -> str:
        return s.replace("{E1}", home).replace("{E2}", away)

    blocks: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for r in rows:
        p = place(r["key"])
        if p is None:
            continue
        tab, title = p[0], p[1]
        bk = (tab, title)
        if bk not in blocks:
            blocks[bk] = {"title": names(title), "rows": {}, "cols": [], "flow": [], "score": {}}
            order.append(bk)
        b = blocks[bk]
        if tab == "score" and p[2] is None:
            b["score"].setdefault(names(p[3]), []).append({"label": p[4], "market": r})
            continue
        row_label, col = names(p[2]), p[3]
        if col is None:
            b["flow"].append({"label": row_label, "market": r})
            continue
        col = names(col)
        if col not in b["cols"]:
            b["cols"].append(col)
        b["rows"].setdefault(row_label, {})[col] = r

    def finalize(b: dict) -> dict:
        if b["score"]:
            cols = [c for c in (home, "Nul", away) if c in b["score"]]
            for c in cols:
                b["score"][c].sort(key=lambda x: (sum(map(int, x["label"].split("-"))), x["label"]))
            depth = max(len(b["score"][c]) for c in cols)
            grid = [{"label": "", "cells": [
                ({"label": b["score"][c][i]["label"], **b["score"][c][i]["market"]} if i < len(b["score"][c]) else None)
                for c in cols]} for i in range(depth)]
            out = {"title": b["title"], "kind": "grid", "columns": cols, "rows": grid, "labelled_cells": True}
            if b["flow"]:
                out["extra"] = [{"label": f["label"], **f["market"]} for f in b["flow"]]
            return out
        if b["cols"]:
            labels = list(b["rows"])
            if all(lbl and _num_key(lbl)[0] == 0 for lbl in labels):
                labels.sort(key=_num_key)
            return {"title": b["title"], "kind": "grid", "columns": b["cols"],
                    "rows": [{"label": lbl, "cells": [b["rows"][lbl].get(c) for c in b["cols"]]} for lbl in labels]}
        return {"title": b["title"], "kind": "flow", "cells": [{"label": f["label"], **f["market"]} for f in b["flow"]]}

    final = {bk: finalize(blocks[bk]) for bk in order}
    tabs = []
    picks = [r for r in rows if r.get("is_pick")]
    popular = []
    if picks:
        popular.append({"title": "Pronostics SAM", "kind": "flow", "highlight": True,
                        "cells": [{"label": r["label"], **r} for r in sorted(picks, key=lambda r: -r["probability"])]})
    popular += [final[("resultat" if t in ("1X2", "Double chance") else "buts", t)] for t in POPULAR_BLOCKS
                if ("resultat" if t in ("1X2", "Double chance") else "buts", t) in final]
    if popular:
        tabs.append({"id": "populaires", "label": "Populaires", "blocks": popular})
    for tid, tlabel in TABS[1:]:
        bl = [final[bk] for bk in order if bk[0] == tid]
        if bl:
            tabs.append({"id": tid, "label": tlabel, "count": sum(
                (len(b.get("rows", [])) * len(b.get("columns", [])) if b["kind"] == "grid" else len(b["cells"])) for b in bl),
                "blocks": bl})
    return tabs
