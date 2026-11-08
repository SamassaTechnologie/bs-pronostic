import Link from "next/link";
import type { PickCard as Pick } from "@/lib/types";
import { kickoffLabel, num, pct } from "@/lib/format";
import { flag } from "@/lib/flags";

type Perf = { total: number; n: number; won: number; hit_rate: number | null; avg_probability: number | null };

/** Jour local (AAAA-MM-JJ) d'un coup d'envoi dans le fuseau du membre. */
function dayOf(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
}

/** « Les bankers du jour » : 2 à 3 pronostics par jour, les plus solides, partageables en un geste. */
export function BankerCard({ picks, perf, tz }: { picks: Pick[]; perf?: Perf; tz: string }) {
  if (!picks.length) return null;
  const day = dayOf(picks[0].match.kickoff, tz);
  const list = picks.filter((p) => dayOf(p.match.kickoff, tz) === day).slice(0, 5);
  const today = dayOf(new Date().toISOString(), tz) === day;
  const lines = list.map((p) => `• ${p.match.home.name} – ${p.match.away.name} (${kickoffLabel(p.match.kickoff, tz)}) : ${p.label}, ${pct(p.probability)}`);
  const text = `⭐ Les bankers SAM-Prédiction${today ? " du jour" : ""} :\n${lines.join("\n")}\nNotre bilan vérifié : https://sam-prediction.vercel.app/bilan`;
  return (
    <section className="mt-4 overflow-hidden rounded-2xl border-2 border-amber bg-white" aria-label="Les bankers du jour">
      <div className="flex items-center justify-between gap-2 bg-amber-soft px-4 py-2">
        <span className="flex items-center gap-1.5 text-[13px] font-extrabold uppercase tracking-wide text-amber">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden><path d="M12 2l2.9 6.3 6.9.8-5.1 4.7 1.4 6.8L12 17.3 5.9 20.6l1.4-6.8L2.2 9.1l6.9-.8z" /></svg>
          {today ? (list.length > 1 ? "Les bankers du jour" : "Le banker du jour") : (list.length > 1 ? "Les bankers de demain" : "Le banker de demain")}
        </span>
        <span className="text-[11.5px] font-semibold text-amber">
          {perf?.n ? `${perf.won}/${perf.n} gagnés` : "Nouveau"}
        </span>
      </div>
      <ul className="divide-y divide-line">
        {list.map((p) => {
          const m = p.match;
          return (
            <li key={`${m.id}-${p.market_key}`}>
              <Link href={`/matchs/${m.id}`} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 text-[11.5px] text-steel">
                    <span aria-hidden>{flag(m.competition.country)}</span>
                    <span className="truncate">{m.competition.name} · {kickoffLabel(m.kickoff, tz)}</span>
                  </div>
                  <div className="truncate font-display text-[16px] font-bold leading-tight text-night">{m.home.name} – {m.away.name}</div>
                  <div className="truncate text-[14px] font-bold text-pitch-deep">{p.label}</div>
                  <div className="text-[11.5px] text-steel">
                    Confiance {p.confidence.score}/100{p.odds ? ` · cote ${num(p.odds)}` : p.fair_odds ? ` · cote juste ${num(p.fair_odds)}` : ""}
                  </div>
                </div>
                <div className="shrink-0 font-display text-[26px] font-bold tracking-tight text-night">{pct(p.probability)}</div>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="flex border-t border-line text-[13px] font-bold">
        <a href={`https://wa.me/?text=${encodeURIComponent(text)}`} target="_blank" rel="noopener noreferrer"
          className="flex flex-1 items-center justify-center gap-1.5 py-2.5 text-pitch-deep">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13" /></svg>
          Partager sur WhatsApp
        </a>
        <Link href="/compte/alertes" className="flex flex-1 items-center justify-center border-l border-line py-2.5 text-night">🔔 Chaque jour</Link>
      </div>
    </section>
  );
}
