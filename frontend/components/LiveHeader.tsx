"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { MatchSummary } from "@/lib/types";
import { kickoffLabel } from "@/lib/format";

export type LiveState = {
  state: "scheduled" | "live" | "finished" | "postponed";
  label: string;
  home?: number | null;
  away?: number | null;
  ht_home?: number | null;
  ht_away?: number | null;
  minute?: string | null;
  minute_estimated?: boolean;
  covered?: boolean;
  note?: string;
};

type Standing = { position: number; points: number } | null | undefined;

/** En-tête du match avec score et minute en direct (actualisé chaque minute pendant le match). */
export function LiveHeader({ match, initial, tz, homeStanding, awayStanding, children }: {
  match: MatchSummary; initial: LiveState; tz: string; homeStanding?: Standing; awayStanding?: Standing; children?: React.ReactNode;
}) {
  const [live, setLive] = useState<LiveState>(initial);
  const soon = new Date(match.kickoff).getTime() - Date.now() < 20 * 60000;

  useEffect(() => {
    if (live.state === "finished" || live.state === "postponed" || (live.state === "scheduled" && !soon)) return;
    const t = setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const r = await fetch(`/api/proxy/matches/${match.id}/live`, { cache: "no-store" });
        if (r.ok) setLive(await r.json());
      } catch {}
    }, 60000);
    return () => clearInterval(t);
  }, [live.state, match.id, soon]);

  const isLive = live.state === "live";
  const hasScore = live.home !== null && live.home !== undefined;
  return (
    <div className="rounded-2xl bg-night px-5 py-5 text-white">
      <div className="flex items-center justify-between gap-2 text-xs text-white/70">
        <span className="min-w-0 truncate">
          <Link href={`/ligues/${match.competition.code}`} className="underline-offset-2 hover:underline">
            {match.competition.name}, {match.competition.country}
          </Link>
        </span>
        {isLive ? (
          <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-brick px-2.5 py-0.5 font-bold text-white">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" aria-hidden />
            {live.label === "Mi-temps" ? "Mi-temps" : `En direct${live.minute && live.minute !== "Mi-temps" ? ` ${live.minute_estimated ? "≈ " : ""}${live.minute}` : ""}`}
          </span>
        ) : live.state === "finished" ? (
          <span className="shrink-0 rounded-full bg-white/15 px-2.5 py-0.5 font-bold">Terminé</span>
        ) : live.state === "postponed" ? (
          <span className="shrink-0 rounded-full bg-amber px-2.5 py-0.5 font-bold">{live.label}</span>
        ) : (
          <span className="shrink-0">{kickoffLabel(match.kickoff, tz)}</span>
        )}
      </div>
      <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
        <div className="min-w-0">
          <Link href={`/equipes/${match.home.id}`} className="block font-display text-xl font-bold leading-tight underline-offset-2 hover:underline">
            {match.home.name}
          </Link>
          {homeStanding && <div className="text-xs text-white/65">{homeStanding.position}e, {homeStanding.points} pts</div>}
        </div>
        <div className="text-center">
          <div className={`font-display text-3xl font-bold tabular-nums ${isLive ? "text-white" : ""}`} aria-live="polite">
            {hasScore ? `${live.home} – ${live.away}` : "–"}
          </div>
          {live.ht_home !== null && live.ht_home !== undefined && (isLive || live.state === "finished") && (
            <div className="text-[11px] text-white/60">Mi-temps {live.ht_home}-{live.ht_away}</div>
          )}
        </div>
        <div className="min-w-0 text-right">
          <Link href={`/equipes/${match.away.id}`} className="block font-display text-xl font-bold leading-tight underline-offset-2 hover:underline">
            {match.away.name}
          </Link>
          {awayStanding && <div className="text-xs text-white/65">{awayStanding.position}e, {awayStanding.points} pts</div>}
        </div>
      </div>
      {isLive && (live.note || live.minute_estimated) && (
        <p className="mt-2 text-center text-[11px] text-white/55">
          {live.note ?? "Minute estimée d'après l'heure du coup d'envoi. Score actualisé chaque minute."}
        </p>
      )}
      {children}
    </div>
  );
}
