import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import { flag } from "@/lib/flags";
import { time } from "@/lib/format";
import type { MatchSummary } from "@/lib/types";
import { ErrorBox } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Matchs" };

type Row = {
  match: MatchSummary & { status: string; score: { home: number; away: number } | null };
  analysis: { status: string; n_picks: number; avoid: boolean } | null;
};

/** Date locale (AAAA-MM-JJ) dans le fuseau du membre, décalée de n jours. */
function localDay(tz: string, offset: number): string {
  const d = new Date(Date.now() + offset * 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

function dayChip(iso: string, tz: string, today: string): { top: string; bottom: string } {
  const d = new Date(`${iso}T12:00:00Z`);
  const top = iso === today ? "Auj." : new Intl.DateTimeFormat("fr-FR", { weekday: "short", timeZone: "UTC" }).format(d).replace(".", "");
  const bottom = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", timeZone: "UTC" }).format(d).replace(".", "");
  return { top, bottom };
}

export default async function Matchs({ searchParams }: { searchParams: Promise<{ jour?: string }> }) {
  const tz = await userTz();
  const { jour } = await searchParams;
  const today = localDay(tz, 0);
  const days = Array.from({ length: 7 }, (_, i) => localDay(tz, i - 1)); // hier → J+5
  const day = jour && /^\d{4}-\d{2}-\d{2}$/.test(jour) ? jour : today;
  const res = await backend<{ items: Row[] }>(`/api/matches?day=${day}&tz=${encodeURIComponent(tz)}`, { revalidate: 60 });

  const groups: { code: string; name: string; country: string; popular: boolean; rows: Row[] }[] = [];
  if (res.ok) {
    for (const r of res.data.items) {
      const c = r.match.competition as MatchSummary["competition"] & { popular?: boolean };
      let g = groups.find((x) => x.code === c.code);
      if (!g) {
        g = { code: c.code, name: c.name, country: c.country, popular: Boolean(c.popular), rows: [] };
        groups.push(g);
      }
      g.rows.push(r);
    }
  }

  return (
    <>
      <div className="mb-3 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Matchs</h1>
        <p className="text-sm text-steel">Programme et résultats des championnats suivis, grands championnats en tête.</p>
      </div>

      <nav className="-mx-3.5 flex gap-1.5 overflow-x-auto px-3.5 pb-1 [scrollbar-width:none]" aria-label="Jours">
        {days.map((d) => {
          const c = dayChip(d, tz, today);
          const on = d === day;
          return (
            <Link key={d} href={`/matchs?jour=${d}`} aria-current={on ? "date" : undefined} scroll={false}
              className={`flex min-w-[58px] shrink-0 flex-col items-center rounded-xl px-2 py-1.5 text-center ${on ? "bg-night text-white" : "border border-line bg-white text-night"}`}>
              <span className="text-[11px] font-semibold capitalize opacity-80">{c.top}</span>
              <span className="text-[13px] font-bold">{c.bottom}</span>
            </Link>
          );
        })}
      </nav>

      {!res.ok && <div className="mt-3"><ErrorBox message={res.error} /></div>}
      {res.ok && groups.length === 0 && (
        <p className="mt-4 rounded-xl border border-dashed border-line bg-white/70 p-5 text-center text-sm text-steel">Aucun match ce jour dans les championnats suivis.</p>
      )}

      <div className="mt-3 space-y-2.5">
        {groups.map((g) => (
          <details key={g.code} open className="group overflow-hidden rounded-xl border border-line bg-white">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-2.5">
              <span className="flex min-w-0 items-center gap-2">
                <span aria-hidden>{flag(g.country)}</span>
                <span className="truncate text-[14px] font-bold">{g.name}</span>
                {g.popular && <span className="text-amber" aria-label="Grand championnat">★</span>}
              </span>
              <span className="flex shrink-0 items-center gap-2 text-xs text-steel">
                {g.rows.length}
                <svg viewBox="0 0 24 24" className="h-4 w-4 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 9l6 6 6-6" /></svg>
              </span>
            </summary>
            <ul className="divide-y divide-mist border-t border-line">
              {g.rows.map((r) => {
                const m = r.match;
                const fin = m.status === "FINISHED" && m.score;
                const a = r.analysis;
                return (
                  <li key={m.id}>
                    <Link href={`/matchs/${m.id}`} className="grid grid-cols-[52px_minmax(0,1fr)_auto] items-center gap-2 px-4 py-2.5">
                      <span className="text-[13px] font-semibold tabular-nums text-steel">
                        {fin ? "Terminé" : m.status === "POSTPONED" ? "Reporté" : time(m.kickoff, tz)}
                      </span>
                      <span className="min-w-0">
                        <span className="flex justify-between gap-2 text-[14px]"><span className="truncate font-semibold">{m.home.name}</span>{fin && <strong className="tabular-nums">{m.score!.home}</strong>}</span>
                        <span className="flex justify-between gap-2 text-[14px]"><span className="truncate font-semibold">{m.away.name}</span>{fin && <strong className="tabular-nums">{m.score!.away}</strong>}</span>
                      </span>
                      <span className="text-right text-[11px] font-semibold">
                        {a?.status === "ok" && a.n_picks > 0 && !a.avoid ? (
                          <span className="rounded-md bg-pitch-soft px-1.5 py-0.5 text-pitch-deep">{a.n_picks} prono.</span>
                        ) : a?.avoid ? (
                          <span className="text-brick">À éviter</span>
                        ) : a && a.status !== "ok" ? (
                          <span className="text-steel">Données insuff.</span>
                        ) : null}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </details>
        ))}
      </div>
    </>
  );
}
