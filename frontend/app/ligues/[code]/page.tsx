import Link from "next/link";
import { notFound } from "next/navigation";
import { backend, userTz } from "@/lib/api";
import { flag } from "@/lib/flags";
import { dayLabel, num, pct } from "@/lib/format";
import { currentMember } from "@/lib/supabase/server";
import type { MatchAnalysisSummary, MatchSummary, StandingRow } from "@/lib/types";
import { Form, MatchLine } from "@/components/MatchLine";
import { Empty, ErrorBox, Section, Stat } from "@/components/ui";

export const dynamic = "force-dynamic";

type Detail = {
  competition: { id: number; code: string; name: string; country: string };
  season: string | null;
  standings: StandingRow[];
  stats: {
    matches: number; avg_goals: number; home_win: number; draw: number; away_win: number; over25: number; btts: number;
    avg_corners: number | null; avg_cards: number | null; over15?: number; over35?: number; clean_sheet?: number; goalless?: number;
    ht_matches?: number; ht_goals_avg?: number; ht_draw?: number; second_half_more?: number;
    htft?: { key: string; rate: number }[];
    leaders?: Record<string, { team_id: number; team: string; value: number | null; played: number }[]>;
  } | null;
  upcoming: { match: MatchSummary; analysis: MatchAnalysisSummary }[];
  recent: MatchSummary[];
  performance: { total: number; n: number; won: number; hit_rate: number | null };
};

export async function generateMetadata({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  const r = await backend<Detail>(`/api/competitions/${encodeURIComponent(code)}`, { revalidate: 120 });
  return { title: r.ok ? `${r.data.competition.name} (${r.data.competition.country})` : "Championnat" };
}

export default async function Ligue({ params, searchParams }: { params: Promise<{ code: string }>; searchParams: Promise<{ vue?: string }> }) {
  const { code } = await params;
  const { vue } = await searchParams;
  const [res, tz, me] = await Promise.all([
    backend<Detail>(`/api/competitions/${encodeURIComponent(code)}`, { revalidate: 120 }),
    userTz(),
    currentMember(),
  ]);
  if (!res.ok) {
    if (res.error.includes("introuvable")) notFound();
    return <ErrorBox message={res.error} />;
  }
  const d = res.data;
  const tab = vue === "classement" || vue === "resultats" || vue === "stats" ? vue : "matchs";
  const tabs: [string, string][] = [["matchs", "Matchs"], ["classement", "Classement"], ["stats", "Stats"], ["resultats", "Résultats"]];
  const st = d.stats;
  const HTFT: Record<string, string> = { "1": "Dom.", X: "Nul", "2": "Ext." };
  const LEAD: [string, string, boolean][] = [
    ["over25", "Plus de 2,5 buts", true], ["btts", "Les deux marquent", true], ["clean_sheets", "Sans encaisser", true],
    ["failed_to_score", "Sans marquer", true], ["goals_for", "Buts marqués / match", false],
  ];

  return (
    <>
      <Link href="/ligues" className="mb-3 inline-block px-1 text-sm font-semibold text-sky">Tous les championnats</Link>
      <div className="flex items-center gap-3 px-1">
        <span className="text-4xl" aria-hidden>{flag(d.competition.country)}</span>
        <div>
          <h1 className="font-display text-2xl font-bold leading-tight tracking-tight">{d.competition.name}</h1>
          <p className="text-sm text-steel">{d.competition.country}{d.season ? `, saison ${d.season}` : ""}</p>
        </div>
      </div>

      {d.stats && (
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Stat label="Buts / match" value={num(d.stats.avg_goals, 2)} />
          <Stat label="Plus de 2,5" value={pct(d.stats.over25)} />
          <Stat label="Les deux marquent" value={pct(d.stats.btts)} />
          <Stat label="Victoires domicile" value={pct(d.stats.home_win)} hint={`Nuls ${pct(d.stats.draw)}`} />
          <Stat label="Corners / match" value={d.stats.avg_corners !== null ? num(d.stats.avg_corners, 1) : "—"} />
          <Stat label="Cartons / match" value={d.stats.avg_cards !== null ? num(d.stats.avg_cards, 1) : "—"} />
        </div>
      )}
      {d.performance.n > 0 && (
        <p className="mt-2 px-1 text-xs text-steel">
          Pronostics SAM dans ce championnat : {d.performance.won} gagnés sur {d.performance.n} réglés ({pct(d.performance.hit_rate)}).
        </p>
      )}

      <div className="sticky top-[calc(env(safe-area-inset-top)+60px)] z-20 -mx-3.5 mt-5 bg-mist/95 px-3.5 py-2 backdrop-blur md:static md:mx-0 md:px-0">
        <div className="grid grid-cols-4 gap-1 rounded-lg bg-white p-1" role="tablist">
          {tabs.map(([k, l]) => (
            <Link key={k} href={`/ligues/${d.competition.code}?vue=${k}`} role="tab" aria-selected={tab === k} replace scroll={false}
              className={`rounded-md py-2 text-center text-sm font-bold ${tab === k ? "bg-night text-white" : "text-steel"}`}>{l}</Link>
          ))}
        </div>
      </div>

      {tab === "matchs" && (
        <Section title="Prochains matchs">
          {d.upcoming.length ? (
            <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
              {d.upcoming.map((u) => <MatchLine key={u.match.id} match={u.match} analysis={u.analysis} tz={tz} signedIn={Boolean(me)} />)}
            </div>
          ) : (
            <Empty title="Aucun match programmé pour le moment" />
          )}
        </Section>
      )}

      {tab === "classement" && (
        <Section title="Classement">
          {d.standings.length ? (
            <div className="overflow-hidden rounded-xl border border-line bg-white">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-steel">
                    <th className="w-8 py-2 pl-3 text-left font-normal">#</th>
                    <th className="py-2 text-left font-normal">Équipe</th>
                    <th className="px-1 py-2 text-right font-normal">J</th>
                    <th className="px-1 py-2 text-right font-normal">Diff</th>
                    <th className="px-2 py-2 text-right font-normal">Pts</th>
                    <th className="hidden py-2 pr-3 text-right font-normal sm:table-cell">Forme</th>
                  </tr>
                </thead>
                <tbody>
                  {d.standings.map((r) => (
                    <tr key={r.team_id} className="border-t border-line">
                      <td className="py-2 pl-3 text-steel">{r.position}</td>
                      <td className="max-w-0 py-2">
                        <Link href={`/equipes/${r.team_id}`} className="block truncate font-semibold">{r.team}</Link>
                      </td>
                      <td className="px-1 py-2 text-right">{r.played}</td>
                      <td className="px-1 py-2 text-right">{r.goal_difference > 0 ? `+${r.goal_difference}` : r.goal_difference}</td>
                      <td className="px-2 py-2 text-right font-bold">{r.points}</td>
                      <td className="hidden py-2 pr-3 text-right sm:table-cell"><Form seq={r.form} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="Classement indisponible" />
          )}
          <p className="mt-2 px-1 text-xs text-steel">Calculé à partir des résultats en base (3 points la victoire, 1 le nul).</p>
        </Section>
      )}

      {tab === "stats" && (
        <Section title="Statistiques de la saison">
          {st ? (
            <div className="space-y-4">
              <div className="overflow-hidden rounded-xl border border-line bg-white">
                <table className="w-full text-sm">
                  <tbody>
                    {([
                      ["Matchs joués", String(st.matches)],
                      ["Plus de 1,5 but", st.over15 != null ? pct(st.over15) : "—"],
                      ["Plus de 2,5 buts", pct(st.over25)],
                      ["Plus de 3,5 buts", st.over35 != null ? pct(st.over35) : "—"],
                      ["Les deux équipes marquent", pct(st.btts)],
                      ["Au moins une équipe sans encaisser", st.clean_sheet != null ? pct(st.clean_sheet) : "—"],
                      ["Matchs à 0-0", st.goalless != null ? pct(st.goalless) : "—"],
                      ["Victoire dom. / nul / ext.", `${pct(st.home_win)} / ${pct(st.draw)} / ${pct(st.away_win)}`],
                      ["Buts en 1re mi-temps / match", st.ht_goals_avg != null ? num(st.ht_goals_avg, 2) : "Données insuffisantes"],
                      ["Nul à la mi-temps", st.ht_draw != null ? pct(st.ht_draw) : "Données insuffisantes"],
                      ["Plus de buts en 2de mi-temps", st.second_half_more != null ? pct(st.second_half_more) : "Données insuffisantes"],
                    ] as [string, string][]).map(([l, v]) => (
                      <tr key={l} className="border-t border-line first:border-0">
                        <td className="py-2 pl-4 text-steel">{l}</td>
                        <td className="py-2 pr-4 text-right font-bold">{v}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {st.htft && st.htft.length > 0 && (
                <div className="rounded-xl border border-line bg-white p-4">
                  <div className="mb-2 text-[13px] font-bold">Mi-temps / fin de match les plus fréquents</div>
                  <div className="grid grid-cols-2 gap-2">
                    {st.htft.map((x) => {
                      const [a, b] = x.key.split("/");
                      return (
                        <div key={x.key} className="rounded-lg bg-mist px-3 py-2">
                          <div className="text-[12px] text-steel">{HTFT[a]} puis {HTFT[b]}</div>
                          <div className="font-display text-lg font-bold">{pct(x.rate)}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {st.leaders && (
                <div className="grid gap-3 md:grid-cols-2">
                  {LEAD.filter(([k]) => st.leaders?.[k]?.length).map(([k, label, rate]) => (
                    <div key={k} className="overflow-hidden rounded-xl border border-line bg-white">
                      <div className="border-b border-line px-4 py-2 text-[13px] font-bold">{label} : équipes en tête</div>
                      {st.leaders![k].map((t, i) => (
                        <Link key={t.team_id} href={`/equipes/${t.team_id}`} className="flex items-center gap-3 border-t border-line px-4 py-2 text-sm first:border-0">
                          <span className="w-4 text-steel">{i + 1}</span>
                          <span className="min-w-0 flex-1 truncate font-semibold">{t.team}</span>
                          <span className="text-[11px] text-steel">{t.played} m.</span>
                          <span className="w-12 text-right font-bold">{t.value == null ? "—" : rate ? pct(t.value) : num(t.value, 2)}</span>
                        </Link>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              <p className="px-1 text-xs text-steel">Calculé sur les matchs terminés de la saison en base. Équipes en tête : au moins 5 matchs joués.</p>
            </div>
          ) : (
            <Empty title="Données insuffisantes" />
          )}
        </Section>
      )}

      {tab === "resultats" && (
        <Section title="Derniers résultats">
          {d.recent.length ? (
            <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
              {d.recent.map((m) => (
                <div key={m.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <span className="w-20 shrink-0 text-xs text-steel">{dayLabel(m.kickoff, tz)}</span>
                  <Link href={`/equipes/${m.home.id}`} className="min-w-0 flex-1 truncate text-right font-semibold">{m.home.name}</Link>
                  <span className="shrink-0 rounded bg-night px-2 py-0.5 text-xs font-bold text-white">{m.score ? `${m.score.home}-${m.score.away}` : "–"}</span>
                  <Link href={`/equipes/${m.away.id}`} className="min-w-0 flex-1 truncate font-semibold">{m.away.name}</Link>
                </div>
              ))}
            </div>
          ) : (
            <Empty title="Aucun résultat" />
          )}
        </Section>
      )}
    </>
  );
}
