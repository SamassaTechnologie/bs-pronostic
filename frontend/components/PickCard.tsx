import Link from "next/link";
import type { PickCard as Pick } from "@/lib/types";
import { kickoffLabel, pct } from "@/lib/format";
import { ConfidenceBadge, OddsInfo, ProbBar, TierBadge } from "./ui";

export function PickCard({ pick, tz, thresholds, rank }: { pick: Pick; tz: string; thresholds?: number[]; rank?: number }) {
  const m = pick.match;
  return (
    <article className="rounded-xl border border-line bg-white">
      <Link href={`/matchs/${m.id}`} className="block px-4 pt-3.5 pb-3">
        <div className="flex items-center justify-between gap-2 text-xs text-steel">
          <span className="truncate">
            {m.competition.name}, {m.competition.country}
          </span>
          <span className="shrink-0">{kickoffLabel(m.kickoff, tz)}</span>
        </div>
        <h3 className="mt-1 font-display text-[17px] font-bold leading-snug tracking-tight text-night">
          {rank !== undefined && <span className="mr-1.5 text-steel">{rank}.</span>}
          {m.home.name} – {m.away.name}
        </h3>
        <div className="mt-2.5 flex items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-ink">{pick.label}</div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <TierBadge tier={pick.tier} />
              <ConfidenceBadge score={pick.confidence.score} level={pick.confidence.level} />
            </div>
          </div>
          <div className="shrink-0 text-right font-display text-3xl font-bold tracking-tight text-night">{pct(pick.probability)}</div>
        </div>
        <div className="mt-2.5">
          <ProbBar p={pick.probability} thresholds={thresholds} />
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <OddsInfo odds={pick.odds} edge={pick.edge} bookmaker={pick.bookmaker} />
          {pick.implied_probability !== null && (
            <span className="text-xs text-steel">Marché {pct(pick.implied_probability)}</span>
          )}
        </div>
      </Link>
      <details className="group border-t border-line">
        <summary className="flex items-center justify-between px-4 py-2.5 text-sm font-semibold text-sky">
          <span>Pourquoi ce pronostic ?</span>
          <span className="text-steel transition-transform group-open:rotate-180" aria-hidden>
            ▾
          </span>
        </summary>
        <div className="space-y-3 px-4 pb-4 text-sm">
          <p className="text-ink">{pick.explanation}</p>
          <Factors fav={pick.factors_for} unf={pick.factors_against} />
        </div>
      </details>
    </article>
  );
}

export function Factors({ fav, unf }: { fav: string[]; unf: string[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div>
        <div className="mb-1 text-xs font-semibold text-pitch-deep">Facteurs favorables</div>
        {fav.length ? (
          <ul className="space-y-1">
            {fav.map((f) => (
              <li key={f} className="flex gap-2 text-ink">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-pitch" />
                {f}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-steel">Aucun facteur marquant.</p>
        )}
      </div>
      <div>
        <div className="mb-1 text-xs font-semibold text-brick">Facteurs défavorables</div>
        {unf.length ? (
          <ul className="space-y-1">
            {unf.map((f) => (
              <li key={f} className="flex gap-2 text-ink">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brick" />
                {f}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-steel">Aucun signal contraire relevé.</p>
        )}
      </div>
    </div>
  );
}
