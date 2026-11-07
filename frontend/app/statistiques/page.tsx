import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import { flag } from "@/lib/flags";
import { kickoffLabel, num, pct } from "@/lib/format";
import type { MatchSummary } from "@/lib/types";
import { ErrorBox } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Statistiques",
  description: "Les deux équipes marquent, plus de 2,5 buts, corners, cartons : fréquences réelles par équipe et matchs à venir.",
};

type Comp = { id: number; code: string; name: string; country: string; popular: boolean };
type TeamRow = { team_id: number; team: string; competition: Comp; n: number; yes: number; rate: number; home_rate: number | null; away_rate: number | null; home_n: number; away_n: number; last: boolean[] };
type Up = { match: MatchSummary; probability: number; confidence: number; fair_odds: number | null; odds: number | null; is_pick: boolean; avoid: boolean; home_rate: number | null; away_rate: number | null };
type Stats = { market: { key: string; label: string; model: string | null }; scope: Comp | null; league_rate: number | null; league_n: number; teams: TeamRow[]; teams_total: number; upcoming: Up[] };

const SEUILS = [0.5, 0.6, 0.7, 0.8];

function href(p: { marche: string; ligue?: string; seuil?: number }) {
  const q = new URLSearchParams({ marche: p.marche });
  if (p.ligue) q.set("ligue", p.ligue);
  if (p.seuil && p.seuil !== 0.6) q.set("seuil", String(p.seuil));
  return `/statistiques?${q}`;
}

function Chip({ to, on, children }: { to: string; on: boolean; children: React.ReactNode }) {
  return (
    <Link href={to} scroll={false} aria-current={on ? "page" : undefined}
      className={`shrink-0 rounded-full px-3 py-1.5 text-[12.5px] font-bold ${on ? "bg-night text-white" : "border border-line bg-white text-night"}`}>
      {children}
    </Link>
  );
}

export default async function Statistiques({ searchParams }: { searchParams: Promise<{ marche?: string; ligue?: string; seuil?: string }> }) {
  const tz = await userTz();
  const sp = await searchParams;
  const [mk, comps] = await Promise.all([
    backend<{ items: { key: string; label: string; has_model: boolean }[] }>("/api/stats", { revalidate: 3600 }),
    backend<{ items: Comp[] }>("/api/competitions", { revalidate: 600 }),
  ]);
  if (!mk.ok) return <ErrorBox message={mk.error} />;
  const marche = mk.data.items.some((m) => m.key === sp.marche) ? sp.marche! : "btts";
  const list = comps.ok ? comps.data.items : [];
  const ligue = list.some((c) => c.code === sp.ligue) ? sp.ligue : undefined;
  const seuil = SEUILS.includes(Number(sp.seuil)) ? Number(sp.seuil) : 0.6;
  const q = new URLSearchParams({ min_probability: String(seuil), days: "3" });
  if (ligue) q.set("competition", ligue);
  const res = await backend<Stats>(`/api/stats/${marche}?${q}`, { revalidate: 300 });
  const popular = list.filter((c) => c.popular);
  const others = list.filter((c) => !c.popular);

  return (
    <>
      <div className="mb-3 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Statistiques</h1>
        <p className="text-sm text-steel">Fréquences réelles de la saison en cours et matchs à venir les plus probables.</p>
      </div>

      <nav className="-mx-3.5 flex gap-1.5 overflow-x-auto px-3.5 pb-1 [scrollbar-width:none]" aria-label="Marchés">
        {mk.data.items.map((m) => <Chip key={m.key} to={href({ marche: m.key, ligue, seuil })} on={m.key === marche}>{m.label}</Chip>)}
      </nav>

      <div className="mt-2 flex gap-2">
        <details className="group relative min-w-0 flex-1">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl border border-line bg-white px-3 py-2 text-[13px] font-semibold [&::-webkit-details-marker]:hidden">
            <span className="truncate">{ligue ? `${flag(list.find((c) => c.code === ligue)!.country)} ${list.find((c) => c.code === ligue)!.name}` : "★ Grands championnats"}</span>
            <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0 text-steel transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 9l6 6 6-6" /></svg>
          </summary>
          <div className="absolute left-0 right-0 z-20 mt-1 max-h-80 overflow-y-auto rounded-xl border border-line bg-white py-1 shadow-lg">
            <Link href={href({ marche, seuil })} className="block px-3 py-2 text-[13px] font-bold">★ Tous les grands championnats</Link>
            {[...popular, ...others].map((c) => (
              <Link key={c.code} href={href({ marche, ligue: c.code, seuil })} className={`block truncate px-3 py-2 text-[13px] ${c.code === ligue ? "bg-mist font-bold" : ""}`}>
                {flag(c.country)} {c.name}{c.popular ? " ★" : ""}
              </Link>
            ))}
          </div>
        </details>
      </div>

      {!res.ok ? <div className="mt-3"><ErrorBox message={res.error} /></div> : (() => {
        const s = res.data;
        return (
          <>
            {s.league_rate !== null && (
              <p className="mt-3 rounded-xl bg-night px-4 py-3 text-[13px] text-white/85">
                <strong className="font-display text-lg text-white">{pct(s.league_rate)}</strong> des {s.league_n} matchs joués cette saison
                {ligue ? "" : " dans les grands championnats"} : « {s.market.label} ».
              </p>
            )}

            {s.market.model && (
              <section className="mt-5">
                <div className="mb-2 px-1">
                  <h2 className="font-display text-lg font-bold">Matchs à venir</h2>
                  <div className="mt-1.5 flex gap-1" role="group" aria-label="Probabilité minimale">
                    {SEUILS.map((v) => (
                      <Link key={v} href={href({ marche, ligue, seuil: v })} scroll={false}
                        className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[12px] font-bold ${v === seuil ? "bg-pitch text-white" : "bg-white text-steel"}`}>≥ {pct(v)}</Link>
                    ))}
                  </div>
                </div>
                {s.upcoming.length ? (
                  <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                    {s.upcoming.map((u) => (
                      <li key={u.match.id}>
                        <Link href={`/matchs/${u.match.id}`} className="flex items-center gap-3 px-3.5 py-2.5">
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[14px] font-semibold">{u.match.home.name} – {u.match.away.name}</div>
                            <div className="truncate text-[11.5px] text-steel">
                              {flag(u.match.competition.country)} {kickoffLabel(u.match.kickoff, tz)}
                              {u.home_rate !== null && u.away_rate !== null && ` · saison ${pct(u.home_rate)} dom. / ${pct(u.away_rate)} ext.`}
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            <div className="font-display text-[17px] font-bold tabular-nums">{pct(u.probability)}</div>
                            <div className="text-[11px] tabular-nums text-steel">
                              {u.avoid ? <span className="font-semibold text-brick">À éviter</span> : u.is_pick ? <span className="font-semibold text-pitch-deep">Pronostic SAM</span> : u.fair_odds ? `cote juste ${num(u.fair_odds)}` : null}
                            </div>
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="rounded-xl border border-dashed border-line bg-white/70 p-4 text-center text-sm text-steel">
                    Aucun match analysé dans les 3 prochains jours n&apos;atteint {pct(seuil)}.
                  </p>
                )}
              </section>
            )}

            <section className="mt-5">
              <h2 className="mb-1 px-1 font-display text-lg font-bold">Classement des équipes</h2>
              <p className="mb-2 px-1 text-[12px] text-steel">Saison en cours, au moins 5 matchs joués. Pastilles : 5 derniers matchs (vert = oui).</p>
              {s.teams.length ? (
                <div className="overflow-hidden rounded-xl border border-line bg-white">
                  <table className="w-full table-fixed text-[13px]">
                    <thead className="bg-mist text-[11px] text-steel">
                      <tr>
                        <th className="w-8 py-2 pl-3 text-left font-semibold">#</th>
                        <th className="py-2 text-left font-semibold">Équipe</th>
                        <th className="w-[52px] py-2 text-right font-semibold">Total</th>
                        <th className="w-[50px] py-2 text-right font-semibold">Dom.</th>
                        <th className="w-[58px] py-2 pr-3 text-right font-semibold">Ext.</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line tabular-nums">
                      {s.teams.map((t, i) => (
                        <tr key={t.team_id}>
                          <td className="py-2 pl-3 text-steel">{i + 1}</td>
                          <td className="py-2 pl-1 pr-1">
                            <Link href={`/equipes/${t.team_id}`} className="block truncate font-semibold">{t.team}</Link>
                            <span className="mt-0.5 flex items-center gap-1">
                              {t.last.map((v, j) => <span key={j} className={`h-1.5 w-1.5 rounded-full ${v ? "bg-pitch" : "bg-line"}`} />)}
                              {!ligue && <span className="ml-1 truncate text-[10.5px] text-steel">{t.competition.name}</span>}
                            </span>
                          </td>
                          <td className="py-2 text-right"><strong>{pct(t.rate)}</strong><div className="text-[10.5px] text-steel">{t.yes}/{t.n}</div></td>
                          <td className="py-2 text-right">{pct(t.home_rate)}</td>
                          <td className="py-2 pr-3 text-right">{pct(t.away_rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="rounded-xl border border-dashed border-line bg-white/70 p-4 text-center text-sm text-steel">
                  Données insuffisantes : aucune équipe n&apos;a encore joué 5 matchs avec cette statistique disponible.
                </p>
              )}
              {s.teams_total > s.teams.length && <p className="mt-1.5 px-1 text-[11.5px] text-steel">{s.teams.length} premières équipes sur {s.teams_total}.</p>}
            </section>
          </>
        );
      })()}
    </>
  );
}
