import Link from "next/link";
import type { MatchAnalysisSummary, MatchSummary } from "@/lib/types";
import { kickoffLabel, pct } from "@/lib/format";

/** Ligne de match compacte avec l'aperçu des pronostics retenus (membres) ou une invitation (visiteurs). */
export function MatchLine({ match, analysis, tz, signedIn, showCompetition = false }: {
  match: MatchSummary; analysis?: MatchAnalysisSummary; tz: string; signedIn: boolean; showCompetition?: boolean;
}) {
  const picks = analysis?.picks ?? [];
  return (
    <Link href={signedIn ? `/matchs/${match.id}` : "/connexion?mode=inscription"} className="block px-4 py-3">
      <div className="flex items-center justify-between gap-2 text-xs text-steel">
        <span className="truncate">{showCompetition ? `${match.competition.name}, ` : ""}{kickoffLabel(match.kickoff, tz)}</span>
        {analysis?.avoid && <span className="shrink-0 font-semibold text-brick">À éviter</span>}
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-3">
        <span className="min-w-0 truncate text-[15px] font-semibold">
          {match.home.name} – {match.away.name}
        </span>
        {match.score && <span className="shrink-0 rounded bg-mist px-1.5 py-0.5 text-xs font-bold">{match.score.home}-{match.score.away}</span>}
      </div>
      {picks.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {signedIn ? (
            picks.map((p) => (
              <span key={p.market_key} className="rounded-md bg-pitch-soft px-2 py-0.5 text-xs font-semibold text-pitch-deep">
                {p.label} {pct(p.probability)}
              </span>
            ))
          ) : (
            <span className="rounded-md bg-mist px-2 py-0.5 text-xs font-semibold text-steel">
              {picks.length} pronostic{picks.length > 1 ? "s" : ""} : inscription gratuite pour voir
            </span>
          )}
        </div>
      )}
      {analysis && analysis.status !== "ok" && <div className="mt-1 text-xs text-steel">Données insuffisantes pour un pronostic</div>}
    </Link>
  );
}

export function Form({ seq }: { seq?: string }) {
  if (!seq) return <span className="text-steel">—</span>;
  const c: Record<string, string> = { V: "bg-pitch text-white", N: "bg-line text-ink", D: "bg-brick text-white" };
  return (
    <span className="inline-flex gap-0.5" aria-label={`Forme récente : ${seq}`}>
      {seq.split("").reverse().map((r, i) => (
        <span key={i} className={`flex h-4 w-4 items-center justify-center rounded-sm text-[9px] font-bold ${c[r]}`}>{r}</span>
      ))}
    </span>
  );
}
