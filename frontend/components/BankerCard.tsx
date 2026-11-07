import Link from "next/link";
import type { PickCard as Pick } from "@/lib/types";
import { kickoffLabel, num, pct } from "@/lib/format";
import { flag } from "@/lib/flags";

type Perf = { total: number; n: number; won: number; hit_rate: number | null; avg_probability: number | null };

/** « Le banker du jour » : un seul pronostic par jour, le plus solide, partageable en un geste. */
export function BankerCard({ pick, perf, tz }: { pick: Pick; perf?: Perf; tz: string }) {
  const m = pick.match;
  const when = kickoffLabel(m.kickoff, tz);
  const text = `Le banker du jour SAM-Prédiction : ${m.home.name} – ${m.away.name} (${when}) → ${pick.label}, probabilité ${pct(pick.probability)}${pick.fair_odds ? `, cote juste ${num(pick.fair_odds)}` : ""}. https://sam-prediction.vercel.app/bilan`;
  return (
    <section className="mt-4 overflow-hidden rounded-2xl border-2 border-amber bg-white" aria-label="Le banker du jour">
      <div className="flex items-center justify-between gap-2 bg-amber-soft px-4 py-2">
        <span className="flex items-center gap-1.5 text-[13px] font-extrabold uppercase tracking-wide text-amber">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden><path d="M12 2l2.9 6.3 6.9.8-5.1 4.7 1.4 6.8L12 17.3 5.9 20.6l1.4-6.8L2.2 9.1l6.9-.8z" /></svg>
          Le banker du jour
        </span>
        <span className="text-[11.5px] font-semibold text-amber">
          {perf?.n ? `${perf.won}/${perf.n} gagnés` : "Nouveau"}
        </span>
      </div>
      <Link href={`/matchs/${m.id}`} className="block px-4 pb-3 pt-3">
        <div className="flex items-center gap-1.5 text-[12px] text-steel">
          <span aria-hidden>{flag(m.competition.country)}</span>
          <span className="truncate">{m.competition.name} · {when}</span>
        </div>
        <div className="mt-1 font-display text-[18px] font-bold leading-tight text-night">{m.home.name} – {m.away.name}</div>
        <div className="mt-2 flex items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[15px] font-bold text-pitch-deep">{pick.label}</div>
            <div className="text-[12px] text-steel">
              Confiance {pick.confidence.score}/100{pick.fair_odds ? ` · cote juste ${num(pick.fair_odds)}` : ""}{pick.odds ? ` · cote ${num(pick.odds)}` : ""}
            </div>
          </div>
          <div className="shrink-0 font-display text-3xl font-bold tracking-tight text-night">{pct(pick.probability)}</div>
        </div>
      </Link>
      <div className="flex border-t border-line text-[13px] font-bold">
        <a href={`https://wa.me/?text=${encodeURIComponent(text)}`} target="_blank" rel="noopener noreferrer"
          className="flex flex-1 items-center justify-center gap-1.5 py-2.5 text-pitch-deep">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13" /></svg>
          Partager sur WhatsApp
        </a>
        <Link href="/bilan" className="flex flex-1 items-center justify-center border-l border-line py-2.5 text-sky">Notre bilan</Link>
      </div>
    </section>
  );
}
