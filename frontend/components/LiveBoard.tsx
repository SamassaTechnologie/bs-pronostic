"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { MatchSummary } from "@/lib/types";
import { pct, time } from "@/lib/format";

type Item = {
  match: MatchSummary;
  live: { status: string; minute: number | null; home: number | null; away: number | null } | null;
  covered: boolean;
  picks: { market_key: string; market_label: string; probability: number; featured: boolean; state: string }[];
};

const STATE_STYLE: Record<string, string> = {
  "Déjà validé": "bg-pitch text-white",
  "Gagnant si le score ne bouge plus": "bg-pitch-soft text-pitch-deep",
  "Perdant si le score ne bouge plus": "bg-brick-soft text-brick",
  "Perdu": "bg-brick text-white",
};

export function LiveBoard({ tz }: { tz: string }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [refreshed, setRefreshed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/proxy/live", { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Erreur");
      setItems(d.items);
      setRefreshed(d.refreshed_at);
      setError(d.error ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
      setItems((x) => x ?? []);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => document.visibilityState === "visible" && load(), 60000);
    return () => clearInterval(t);
  }, [load]);

  if (items === null) return <p className="px-1 text-sm text-steel">Chargement des matchs en cours…</p>;
  return (
    <div className="space-y-3">
      <p className="px-1 text-xs text-steel">
        Actualisation automatique chaque minute{refreshed ? `, dernière à ${time(refreshed, tz)}` : ""}. Scores fournis par
        football-data.org avec un léger différé.
      </p>
      {error && <p className="rounded-lg bg-amber-soft px-3 py-2 text-sm">Source des scores indisponible pour le moment : {error}</p>}
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line bg-white/60 px-4 py-6 text-center">
          <p className="font-semibold">Aucun match en cours dans les championnats suivis</p>
          <p className="mt-1 text-sm text-steel">Revenez au coup d&apos;envoi des prochains matchs.</p>
        </div>
      ) : (
        items.map((it) => (
          <article key={it.match.id} className="rounded-xl border border-line bg-white">
            <Link href={`/matchs/${it.match.id}`} className="block px-4 py-3">
              <div className="flex items-center justify-between text-xs text-steel">
                <span className="truncate">{it.match.competition.name}, coup d&apos;envoi {time(it.match.kickoff, tz)}</span>
                {it.live ? (
                  <span className="flex items-center gap-1.5 font-semibold text-brick">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-brick" aria-hidden />
                    {it.live.status}{it.live.minute ? ` ${it.live.minute}'` : ""}
                  </span>
                ) : (
                  <span>Score en direct non couvert</span>
                )}
              </div>
              <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                <span className="truncate font-display text-[17px] font-bold">{it.match.home.name}</span>
                <span className="rounded-lg bg-night px-3 py-1 font-display text-xl font-bold text-white">
                  {it.live && it.live.home !== null ? `${it.live.home} – ${it.live.away}` : "– –"}
                </span>
                <span className="truncate text-right font-display text-[17px] font-bold">{it.match.away.name}</span>
              </div>
            </Link>
            {it.picks.length > 0 && (
              <ul className="divide-y divide-line border-t border-line">
                {it.picks.map((p) => (
                  <li key={p.market_key} className="flex items-center justify-between gap-2 px-4 py-2.5 text-sm">
                    <span className="min-w-0">
                      <span className="block truncate font-semibold">{p.market_label}{p.featured ? " · Sélection SAM" : ""}</span>
                      <span className="text-xs text-steel">Annoncé à {pct(p.probability)}</span>
                    </span>
                    <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${STATE_STYLE[p.state] ?? "bg-mist text-steel"}`}>{p.state}</span>
                  </li>
                ))}
              </ul>
            )}
          </article>
        ))
      )}
    </div>
  );
}
