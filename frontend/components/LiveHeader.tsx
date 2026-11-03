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
  details?: MatchDetails | null;
};

type MatchEvent = { minute: string; type: "goal" | "penalty" | "own_goal" | "yellow" | "red" | "second_yellow"; side: "home" | "away"; player: string; assist?: string; score?: string };
type MatchStat = { label: string; home: number; away: number; pct: boolean };
export type MatchDetails = { events: MatchEvent[]; stats: MatchStat[]; source?: string };

const EV_LABEL: Record<MatchEvent["type"], string> = {
  goal: "But", penalty: "But sur penalty", own_goal: "But contre son camp", yellow: "Carton jaune",
  red: "Carton rouge", second_yellow: "Second carton jaune",
};

function EvIcon({ t }: { t: MatchEvent["type"] }) {
  if (t === "yellow") return <span className="inline-block h-3.5 w-2.5 rounded-[2px] bg-[#f5c518]" aria-hidden />;
  if (t === "red" || t === "second_yellow") return <span className="inline-block h-3.5 w-2.5 rounded-[2px] bg-brick" aria-hidden />;
  return (
    <svg viewBox="0 0 24 24" className={`h-4 w-4 ${t === "own_goal" ? "text-brick" : "text-white"}`} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <circle cx="12" cy="12" r="9" /><path d="M12 7.5l3.8 2.8-1.5 4.4H9.7l-1.5-4.4z" />
    </svg>
  );
}

/** Chronologie (buts, cartons) et statistiques du match, à partir de la source de données (jamais estimées). */
function MatchTimeline({ d: raw, home, away }: { d: MatchDetails; home?: number | null; away?: number | null }) {
  const isGoal = (e: MatchEvent) => e.type === "goal" || e.type === "penalty" || e.type === "own_goal";
  const goals = raw.events.filter(isGoal).length;
  // Buteurs affichés seulement s'ils correspondent exactement au score (jamais d'information contradictoire)
  const consistent = home === null || home === undefined || away === null || away === undefined || goals === home + away;
  const d = consistent ? raw : { ...raw, events: raw.events.filter((e) => !isGoal(e)) };
  return (
    <div className="mt-4 border-t border-white/15 pt-3">
      {d.events.length > 0 && (
        <ol className="space-y-1.5" aria-label="Chronologie du match">
          {d.events.map((e, i) => (
            <li key={`${e.minute}-${e.player}-${i}`} className={`flex items-center gap-2 text-[13px] ${e.side === "away" ? "flex-row-reverse text-right" : ""}`}>
              <span className="w-9 shrink-0 text-center font-bold tabular-nums text-white/70">{e.minute}&apos;</span>
              <EvIcon t={e.type} />
              <span className="min-w-0 truncate">
                <span className="font-semibold">{e.player}</span>
                <span className="text-white/55"> · {EV_LABEL[e.type]}{e.score && (e.type === "goal" || e.type === "penalty" || e.type === "own_goal") ? ` (${e.score.replace("-", "–")})` : ""}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
      {d.stats.length > 0 && (
        <div className={`space-y-2 ${d.events.length ? "mt-4" : ""}`} aria-label="Statistiques du match">
          {d.stats.map((s) => {
            const tot = s.home + s.away;
            const hp = tot ? (s.home / tot) * 100 : 50;
            return (
              <div key={s.label}>
                <div className="flex justify-between text-[12px] text-white/80">
                  <strong className="tabular-nums text-white">{s.home}{s.pct ? " %" : ""}</strong>
                  <span>{s.label}</span>
                  <strong className="tabular-nums text-white">{s.away}{s.pct ? " %" : ""}</strong>
                </div>
                <div className="mt-1 flex h-1.5 gap-0.5 overflow-hidden rounded-full">
                  <span className={`h-full rounded-l-full ${s.home >= s.away ? "bg-pitch" : "bg-white/35"}`} style={{ width: `${hp}%` }} />
                  <span className={`h-full flex-1 rounded-r-full ${s.away > s.home ? "bg-pitch" : "bg-white/35"}`} />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {!consistent && <p className="mt-2 text-[11px] text-white/60">Buteurs non affichés : la liste de la source ne correspond pas encore au score.</p>}
      <p className="mt-2 text-[10.5px] text-white/45">Chronologie et statistiques : {d.source ?? "source de données"}.</p>
    </div>
  );
}

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
        if (r.ok) setLive(await r.json().catch(() => ({ detail: "Service momentanément indisponible, réessayez dans un instant." })));
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
      {live.details && (live.state === "live" || live.state === "finished") && (live.details.events.length > 0 || live.details.stats.length > 0) && (
        <MatchTimeline d={live.details} home={live.home} away={live.away} />
      )}
      {children}
    </div>
  );
}
