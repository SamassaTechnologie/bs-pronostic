import Link from "next/link";
import type { MatchSummary, PickCard } from "@/lib/types";
import { kickoffLabel, num, pct, time } from "@/lib/format";
import { ProbBar, TierBadge } from "./ui";

export function CompactPick({ pick, tz, thresholds }: { pick: PickCard; tz: string; thresholds?: number[] }) {
  const m = pick.match;
  return (
    <Link href={`/matchs/${m.id}`} className="flex items-center gap-3 px-4 py-3">
      <TierBadge tier={pick.tier} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-night">
          {m.home.name} – {m.away.name}
        </div>
        <div className="truncate text-xs text-steel">
          {pick.label}, {kickoffLabel(m.kickoff, tz)}
        </div>
        <div className="mt-1.5">
          <ProbBar p={pick.probability} thresholds={thresholds} size="sm" />
        </div>
      </div>
      <div className="w-16 shrink-0 text-right">
        <div className="font-display text-lg font-bold text-night">{pct(pick.probability)}</div>
        <div className="text-[11px] text-steel">{pick.odds ? `cote ${num(pick.odds)}` : `conf. ${pick.confidence.score}`}</div>
      </div>
    </Link>
  );
}

export function MatchRow({ match, tz, right }: { match: MatchSummary; tz: string; right?: React.ReactNode }) {
  return (
    <Link href={`/matchs/${match.id}`} className="flex items-center gap-3 px-4 py-3">
      <div className="w-12 shrink-0 text-sm font-bold text-night">{time(match.kickoff, tz)}</div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-night">
          {match.home.name} – {match.away.name}
          {match.score && (
            <span className="ml-2 rounded bg-mist px-1.5 py-0.5 text-xs font-bold">
              {match.score.home}-{match.score.away}
            </span>
          )}
        </div>
        <div className="truncate text-xs text-steel">{match.competition.name}, {match.competition.country}</div>
      </div>
      {right}
    </Link>
  );
}

export function List({ children }: { children: React.ReactNode }) {
  return <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">{children}</div>;
}
