import Link from "next/link";
import type { PickCard } from "@/lib/types";
import { flag } from "@/lib/flags";
import { pct, time, dayLabel } from "@/lib/format";
import { TierBadge } from "./ui";

/** Pronostics regroupés par championnat puis par match. */
export function GroupedPicks({ items, tz }: { items: PickCard[]; tz: string }) {
  const comps = new Map<string, { name: string; country: string; code: string; matches: Map<number, PickCard[]> }>();
  for (const p of items) {
    const c = p.match.competition;
    const g = comps.get(c.code) ?? { name: c.name, country: c.country, code: c.code, matches: new Map() };
    g.matches.set(p.match.id, [...(g.matches.get(p.match.id) ?? []), p]);
    comps.set(c.code, g);
  }
  const groups = [...comps.values()].sort((a, b) => a.country.localeCompare(b.country, "fr") || a.name.localeCompare(b.name, "fr"));
  return (
    <div className="space-y-3">
      {groups.map((g) => {
        const matches = [...g.matches.values()].sort((a, b) => a[0].match.kickoff.localeCompare(b[0].match.kickoff));
        const n = matches.reduce((s, m) => s + m.length, 0);
        return (
          <details key={g.code} open className="group overflow-hidden rounded-xl border border-line bg-white">
            <summary className="flex items-center gap-2.5 bg-night/[0.03] px-4 py-3">
              <span className="text-xl" aria-hidden>{flag(g.country)}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-bold">{g.name}</span>
                <span className="block text-xs text-steel">{g.country}, {matches.length} match{matches.length > 1 ? "s" : ""}, {n} pronostic{n > 1 ? "s" : ""}</span>
              </span>
              <span className="text-steel transition-transform group-open:rotate-180" aria-hidden>▾</span>
            </summary>
            <ul className="divide-y divide-line border-t border-line">
              {matches.map((ps) => {
                const m = ps[0].match;
                return (
                  <li key={m.id}>
                    <Link href={`/matchs/${m.id}`} className="block px-4 py-3">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="min-w-0 truncate text-[15px] font-semibold">{m.home.name} – {m.away.name}</span>
                        <span className="shrink-0 text-xs text-steel">{dayLabel(m.kickoff, tz)}, {time(m.kickoff, tz)}</span>
                      </div>
                      <div className="mt-2 space-y-1.5">
                        {ps.sort((a, b) => b.probability - a.probability).map((p) => (
                          <div key={p.market_key} className="flex items-center gap-2 text-sm">
                            <TierBadge tier={p.tier} />
                            <span className="min-w-0 flex-1 truncate">{p.label}</span>
                            {p.featured && <span className="shrink-0 text-[11px] font-bold text-pitch-deep">Sélection SAM</span>}
                            <span className="w-12 shrink-0 text-right font-bold">{pct(p.probability)}</span>
                          </div>
                        ))}
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
            <Link href={`/ligues/${g.code}`} className="block border-t border-line px-4 py-2.5 text-sm font-semibold text-sky">
              Classement et statistiques : {g.name}
            </Link>
          </details>
        );
      })}
    </div>
  );
}
