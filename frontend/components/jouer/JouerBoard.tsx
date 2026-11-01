"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { MatchSummary } from "@/lib/types";
import { kickoffLabel, pct } from "@/lib/format";
import { flag } from "@/lib/flags";
import { CouponBar, JouerHeader, Legend, OddsButton, type OddsRow, type Wallet } from "./JouerUi";

type Row = { match: MatchSummary; markets_count: number; odds: Record<"1" | "X" | "2", OddsRow>; sam: { key: string; label: string; short: string; probability: number } | null; avoid: boolean };
type Group = { code: string; name: string; country: string; matches: Row[] };
type LiveRow = { match: MatchSummary; live: { home: number | null; away: number | null; minute?: string | null; minute_estimated?: boolean } };
type Board = { wallet: Wallet; jour: string; groups: Group[]; live?: LiveRow[] };

const TABS: [string, string][] = [["direct", "Direct"], ["aujourdhui", "Aujourd'hui"], ["demain", "Demain"], ["tout", "3 jours"]];

export function JouerBoard({ tz }: { tz: string }) {
  const [jour, setJour] = useState("aujourdhui");
  const [filter, setFilter] = useState<"tous" | "sam">("tous");
  const [data, setData] = useState<Board | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async (j: string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`/api/proxy/jeu/board?jour=${j}&tz=${encodeURIComponent(tz)}`, { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Service indisponible");
      setData(d);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }, [tz]);

  useEffect(() => { load(jour); }, [jour, load]);

  const groups = (data?.groups ?? []).map((g) => ({ ...g, matches: g.matches.filter((m) => filter === "tous" || m.sam) })).filter((g) => g.matches.length);

  return (
    <>
      <JouerHeader title="Jouer" sub="Paris en jetons SAM, sans argent réel" wallet={data?.wallet} />
      <div className="grid grid-cols-4 gap-1 rounded-xl bg-white p-1" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={jour === k} onClick={() => setJour(k)}
            className={`rounded-lg py-2 text-[13px] font-bold ${jour === k ? (k === "direct" ? "bg-brick text-white" : "bg-night text-white") : "text-steel"}`}>
            {l}
          </button>
        ))}
      </div>
      {jour !== "direct" && (
        <div className="mt-2.5 flex gap-2">
          {([["tous", "Tous les matchs"], ["sam", "Avec pronostic SAM"]] as const).map(([k, l]) => (
            <button key={k} type="button" onClick={() => setFilter(k)} aria-pressed={filter === k}
              className={`rounded-full px-3 py-1.5 text-[13px] font-semibold ${filter === k ? "bg-night text-white" : "border border-line bg-white text-night"}`}>
              {l}
            </button>
          ))}
        </div>
      )}

      {busy && !data && <p className="mt-6 text-center text-sm text-steel">Chargement des matchs…</p>}
      {err && <p className="mt-4 rounded-xl bg-amber-soft px-4 py-3 text-sm">{err}</p>}

      {jour === "direct" ? (
        <div className="mt-3 space-y-2">
          <p className="px-1 text-xs text-steel">Les paris ferment au coup d&apos;envoi : les matchs en cours sont affichés pour suivre vos paris.</p>
          {(data?.live ?? []).length === 0 && !busy && <p className="rounded-xl border border-dashed border-line bg-white/70 p-4 text-center text-sm text-steel">Aucun match en cours.</p>}
          {(data?.live ?? []).map((r) => (
            <Link key={r.match.id} href={`/matchs/${r.match.id}`} className="flex items-center justify-between gap-3 rounded-xl border border-line bg-white px-4 py-3">
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">{r.match.home.name} – {r.match.away.name}</span>
                <span className="block truncate text-xs text-steel">{r.match.competition.name}</span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block font-display text-lg font-bold tabular-nums">{r.live.home ?? "–"} - {r.live.away ?? "–"}</span>
                <span className="block text-[11px] font-bold text-brick">{r.live.minute_estimated ? "≈ " : ""}{r.live.minute ?? "En direct"}</span>
              </span>
            </Link>
          ))}
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {!busy && groups.length === 0 && !err && (
            <p className="rounded-xl border border-dashed border-line bg-white/70 p-4 text-center text-sm text-steel">Aucun match ouvert aux paris pour cette période.</p>
          )}
          {groups.map((g) => (
            <section key={g.code} className="overflow-hidden rounded-xl border border-line bg-white">
              <div className="flex items-center justify-between border-b border-line bg-mist/60 px-3 py-2">
                <span className="truncate text-[13px] font-bold"><span aria-hidden className="mr-1.5">{flag(g.country)}</span>{g.name}</span>
                <span className="shrink-0 text-xs text-steel">{g.country}</span>
              </div>
              {g.matches.map((r) => {
                const label = `${r.match.home.name} – ${r.match.away.name}`;
                return (
                  <div key={r.match.id} className="border-b border-mist px-3 py-2.5 last:border-0">
                    <div className="flex items-start justify-between gap-2">
                      <Link href={`/jouer/match/${r.match.id}`} className="min-w-0">
                        <span className="block truncate text-[15px] font-semibold">{r.match.home.name}</span>
                        <span className="block truncate text-[15px] font-semibold">{r.match.away.name}</span>
                      </Link>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <span className="text-xs text-steel">{kickoffLabel(r.match.kickoff, tz)}</span>
                        {r.sam && <span className="rounded-md bg-pitch-soft px-1.5 py-0.5 text-[11px] font-bold text-pitch-deep">SAM : {r.sam.short} {pct(r.sam.probability)}</span>}
                        {r.avoid && <span className="rounded-md bg-amber-soft px-1.5 py-0.5 text-[11px] font-bold text-amber">Match à éviter</span>}
                      </div>
                    </div>
                    <div className="mt-2 grid grid-cols-[repeat(3,minmax(0,1fr))_48px] gap-1.5">
                      {(["1", "X", "2"] as const).map((k) => (
                        <OddsButton key={k} row={r.odds[k]} matchId={r.match.id} matchLabel={label} label={k} />
                      ))}
                      <Link href={`/jouer/match/${r.match.id}`} aria-label={`Tous les marchés de ${label}`}
                        className="flex items-center justify-center rounded-lg bg-ink text-xs font-bold text-white">+{Math.max(0, r.markets_count - 3)}</Link>
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      )}
      <Legend />
      <div className="h-16" />
      <CouponBar />
    </>
  );
}
