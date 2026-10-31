"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { MatchSummary } from "@/lib/types";
import { flag } from "@/lib/flags";
import { pct, time } from "@/lib/format";

type PickState = { market_key: string; market_label: string; probability: number; featured: boolean; state: string; result: string };
type Item = {
  match: MatchSummary;
  live: { status: string; minute: number | null; home: number | null; away: number | null } | null;
  covered: boolean;
  picks: PickState[];
};
type Board = { live: Item[]; upcoming: Item[]; finished: Item[]; refreshed_at: string | null; error: string | null };
type Tab = "live" | "upcoming" | "finished";

const STATE_STYLE: Record<string, string> = {
  "Déjà validé": "bg-pitch text-white",
  "Gagné": "bg-pitch text-white",
  "Gagnant si le score ne bouge plus": "bg-pitch-soft text-pitch-deep",
  "Perdant si le score ne bouge plus": "bg-brick-soft text-brick",
  "Perdu": "bg-brick text-white",
  "Résultat en attente": "bg-amber-soft text-amber",
};

function groupByCompetition(items: Item[]) {
  const map = new Map<string, { name: string; country: string; code: string; items: Item[] }>();
  for (const it of items) {
    const c = it.match.competition;
    const g = map.get(c.code) ?? { name: c.name, country: c.country, code: c.code, items: [] };
    g.items.push(it);
    map.set(c.code, g);
  }
  return [...map.values()];
}

function Score({ it, tab }: { it: Item; tab: Tab }) {
  if (tab === "finished" && it.match.score) return <>{it.match.score.home} – {it.match.score.away}</>;
  if (tab === "live" && it.live && it.live.home !== null) return <>{it.live.home} – {it.live.away}</>;
  return <>– –</>;
}

export function LiveBoard({ tz }: { tz: string }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab | null>(null);
  const [onlyPicks, setOnlyPicks] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/proxy/live?tz=${encodeURIComponent(tz)}`, { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Erreur");
      setBoard({ live: d.live ?? d.items ?? [], upcoming: d.upcoming ?? [], finished: d.finished ?? [], refreshed_at: d.refreshed_at, error: d.error });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  }, [tz]);

  useEffect(() => {
    load();
    const t = setInterval(() => document.visibilityState === "visible" && load(), 60000);
    return () => clearInterval(t);
  }, [load]);

  // Onglet par défaut : « En cours » s'il y a des matchs, sinon « À venir ».
  const current: Tab = tab ?? (board && board.live.length === 0 ? (board.upcoming.length ? "upcoming" : "finished") : "live");
  const items = useMemo(() => {
    const list = board ? board[current] : [];
    return onlyPicks ? list.filter((i) => i.picks.length) : list;
  }, [board, current, onlyPicks]);

  if (!board && !error) return <p className="px-1 text-sm text-steel">Chargement de la journée…</p>;
  const counts = { live: board?.live.length ?? 0, upcoming: board?.upcoming.length ?? 0, finished: board?.finished.length ?? 0 };
  const tabs: [Tab, string][] = [["live", "En cours"], ["upcoming", "À venir"], ["finished", "Terminés"]];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-1 rounded-lg bg-white p-1" role="tablist">
        {tabs.map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={current === k} onClick={() => setTab(k)}
            className={`flex items-center justify-center gap-1.5 rounded-md py-2 text-sm font-bold ${current === k ? "bg-night text-white" : "text-steel"}`}>
            {k === "live" && counts.live > 0 && <span className="h-2 w-2 animate-pulse rounded-full bg-brick" aria-hidden />}
            {l} <span className={`text-xs font-semibold ${current === k ? "text-white/70" : "text-steel/70"}`}>{counts[k]}</span>
          </button>
        ))}
      </div>
      <div className="flex items-center justify-between gap-3 px-1">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyPicks} onChange={(e) => setOnlyPicks(e.target.checked)} className="h-4 w-4" />
          Seulement les matchs avec pronostic
        </label>
        <button type="button" onClick={load} className="shrink-0 text-sm font-semibold text-sky">Actualiser</button>
      </div>
      {(error || board?.error) && (
        <p className="rounded-lg bg-amber-soft px-3 py-2 text-sm">Scores en direct indisponibles pour le moment : {error || board?.error}</p>
      )}
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line bg-white/60 px-4 py-6 text-center">
          <p className="font-semibold">
            {current === "live" ? "Aucun match en cours" : current === "upcoming" ? "Plus de match à venir aujourd'hui" : "Aucun match terminé aujourd'hui"}
            {onlyPicks ? " avec pronostic" : ""}
          </p>
          <p className="mt-1 text-sm text-steel">Championnats suivis uniquement.</p>
        </div>
      ) : (
        groupByCompetition(items).map((g) => (
          <section key={g.code} className="overflow-hidden rounded-xl border border-line bg-white">
            <Link href={`/ligues/${g.code}`} className="flex items-center gap-2 border-b border-line bg-night/[0.03] px-4 py-2.5">
              <span className="text-lg" aria-hidden>{flag(g.country)}</span>
              <span className="truncate text-sm font-bold">{g.name}</span>
              <span className="text-xs text-steel">{g.country}</span>
            </Link>
            <ul className="divide-y divide-line">
              {g.items.map((it) => (
                <li key={it.match.id}>
                  <Link href={`/matchs/${it.match.id}`} className="block px-4 py-3">
                    <div className="flex items-center justify-between text-xs text-steel">
                      <span>{time(it.match.kickoff, tz)}</span>
                      {current === "live" ? (
                        it.live ? (
                          <span className="flex items-center gap-1.5 font-semibold text-brick">
                            <span className="h-2 w-2 animate-pulse rounded-full bg-brick" aria-hidden />
                            {it.live.status}{it.live.minute ? ` ${it.live.minute}'` : ""}
                          </span>
                        ) : <span>Score en direct non couvert</span>
                      ) : current === "finished" ? <span className="font-semibold">Terminé</span> : null}
                    </div>
                    <div className="mt-1 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                      <span className="truncate text-[15px] font-semibold">{it.match.home.name}</span>
                      <span className={`rounded-lg px-2.5 py-0.5 font-display text-lg font-bold ${current === "upcoming" ? "bg-mist text-steel" : "bg-night text-white"}`}>
                        <Score it={it} tab={current} />
                      </span>
                      <span className="truncate text-right text-[15px] font-semibold">{it.match.away.name}</span>
                    </div>
                  </Link>
                  {it.picks.length > 0 && (
                    <ul className="space-y-1.5 px-4 pb-3">
                      {it.picks.map((p) => (
                        <li key={p.market_key} className="flex items-center justify-between gap-2 text-sm">
                          <span className="min-w-0 truncate">
                            {p.market_label} <span className="text-steel">{pct(p.probability)}</span>
                            {p.featured && <span className="ml-1 text-[11px] font-bold text-pitch-deep">SAM</span>}
                          </span>
                          {current !== "upcoming" && (
                            <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${STATE_STYLE[p.state] ?? "bg-mist text-steel"}`}>{p.state}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
      <p className="px-1 text-xs text-steel">
        Actualisation automatique chaque minute{board?.refreshed_at ? `, dernière à ${time(board.refreshed_at, tz)}` : ""}. Scores
        football-data.org légèrement différés ; certains championnats ne sont pas couverts en direct.
      </p>
    </div>
  );
}
