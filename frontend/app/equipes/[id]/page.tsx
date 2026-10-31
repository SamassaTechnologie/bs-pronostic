import Link from "next/link";
import { notFound } from "next/navigation";
import { backend, userTz } from "@/lib/api";
import { flag } from "@/lib/flags";
import { dayLabel, num, pct, RESULT_LABEL } from "@/lib/format";
import { currentMember } from "@/lib/supabase/server";
import type { FormSummary, HistoryRow, MatchAnalysisSummary, MatchSummary } from "@/lib/types";
import { Form, MatchLine } from "@/components/MatchLine";
import { Card, Empty, ErrorBox, Section } from "@/components/ui";

export const dynamic = "force-dynamic";

type Detail = {
  team: { id: number; name: string; country: string };
  competition: { id: number; code: string; name: string; country: string } | null;
  standing: { position: number; points: number; played: number; goal_difference: number; teams: number } | null;
  form: { last10: FormSummary; last5: FormSummary; home10: FormSummary; away10: FormSummary };
  upcoming: { match: MatchSummary; analysis: MatchAnalysisSummary }[];
  recent: MatchSummary[];
  predictions: HistoryRow[];
};

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = /^\d+$/.test(id) ? await backend<Detail>(`/api/teams/${id}`, { revalidate: 120 }) : null;
  return { title: r?.ok ? r.data.team.name : "Équipe" };
}

function outcome(m: MatchSummary, teamId: number): "V" | "N" | "D" | null {
  if (!m.score) return null;
  const gf = m.home.id === teamId ? m.score.home : m.score.away;
  const ga = m.home.id === teamId ? m.score.away : m.score.home;
  return gf > ga ? "V" : gf === ga ? "N" : "D";
}

export default async function Equipe({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const [res, tz, me] = await Promise.all([backend<Detail>(`/api/teams/${id}`, { revalidate: 120 }), userTz(), currentMember()]);
  if (!res.ok) {
    if (res.error.includes("introuvable")) notFound();
    return <ErrorBox message={res.error} />;
  }
  const d = res.data;
  const f = d.form;
  const rows: [string, (x: FormSummary) => string][] = [
    ["Points par match", (x) => num(x.points_per_match ?? null)],
    ["Buts marqués / match", (x) => num(x.goals_for_avg ?? null)],
    ["Buts encaissés / match", (x) => num(x.goals_against_avg ?? null)],
    ["Matchs à +2,5 buts", (x) => pct(x.over25_rate ?? null)],
    ["Les deux marquent", (x) => pct(x.btts_rate ?? null)],
    ["Corners / match (total)", (x) => num(x.corners_total_avg ?? null, 1)],
    ["Cartons / match (total)", (x) => num(x.cards_total_avg ?? null, 1)],
  ];
  const badge: Record<string, string> = { V: "bg-pitch text-white", N: "bg-line text-ink", D: "bg-brick text-white" };

  return (
    <>
      <div className="rounded-2xl bg-night px-5 py-5 text-white">
        <div className="flex items-center gap-3">
          <span className="text-4xl" aria-hidden>{flag(d.team.country)}</span>
          <div className="min-w-0">
            <h1 className="truncate font-display text-2xl font-bold tracking-tight">{d.team.name}</h1>
            {d.competition && (
              <Link href={`/ligues/${d.competition.code}?vue=classement`} className="text-sm text-white/75 underline-offset-2 hover:underline">
                {d.competition.name}, {d.competition.country}
              </Link>
            )}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/15 pt-3 text-center text-xs text-white/70">
          <div>Classement<div className="font-display text-lg font-bold text-white">{d.standing ? `${d.standing.position}e / ${d.standing.teams}` : "—"}</div></div>
          <div>Points<div className="font-display text-lg font-bold text-white">{d.standing ? d.standing.points : "—"}</div></div>
          <div>Forme<div className="mt-1 flex justify-center"><Form seq={f.last5.sequence} /></div></div>
        </div>
      </div>

      <Section title="Prochains matchs">
        {d.upcoming.length ? (
          <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
            {d.upcoming.map((u) => <MatchLine key={u.match.id} match={u.match} analysis={u.analysis} tz={tz} signedIn={Boolean(me)} showCompetition />)}
          </div>
        ) : (
          <Empty title="Aucun match programmé dans les prochains jours" />
        )}
      </Section>

      <Section title="Statistiques récentes">
        {f.last10.played ? (
          <Card className="p-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-steel">
                  <th className="py-1 text-left font-normal" />
                  <th className="py-1 pl-2 text-right font-normal">10 m.</th>
                  <th className="py-1 pl-2 text-right font-normal">Dom.</th>
                  <th className="py-1 pl-2 text-right font-normal">Ext.</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(([label, fn]) => (
                  <tr key={label} className="border-t border-line">
                    <td className="py-1.5 text-steel">{label}</td>
                    <td className="py-1.5 text-right font-semibold">{fn(f.last10)}</td>
                    <td className="py-1.5 text-right font-semibold">{f.home10.played ? fn(f.home10) : "—"}</td>
                    <td className="py-1.5 text-right font-semibold">{f.away10.played ? fn(f.away10) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-steel">
              10 m. : 10 derniers matchs ; Dom. et Ext. : 10 derniers à domicile et à l&apos;extérieur. Sur 10 matchs : {f.last10.wins} victoires, {f.last10.draws} nuls, {f.last10.losses} défaites, {f.last10.clean_sheets} sans encaisser.
            </p>
          </Card>
        ) : (
          <Empty title="Pas encore de match joué en base" />
        )}
      </Section>

      <Section title="Derniers résultats">
        {d.recent.length ? (
          <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
            {d.recent.map((m) => {
              const o = outcome(m, d.team.id);
              const opp = m.home.id === d.team.id ? m.away : m.home;
              return (
                <div key={m.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                  {o && <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded text-xs font-bold ${badge[o]}`}>{o}</span>}
                  <div className="min-w-0 flex-1">
                    <Link href={`/equipes/${opp.id}`} className="block truncate font-semibold">
                      {m.home.id === d.team.id ? "contre " : "à "}{opp.name}
                    </Link>
                    <span className="text-xs text-steel">{dayLabel(m.kickoff, tz)}, {m.competition.name}</span>
                  </div>
                  <span className="shrink-0 font-bold">{m.score ? `${m.score.home}-${m.score.away}` : "–"}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <Empty title="Aucun résultat" />
        )}
      </Section>

      {me && d.predictions.length > 0 && (
        <Section title="Pronostics SAM sur cette équipe">
          <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
            {d.predictions.map((p) => (
              <Link key={p.id} href={`/matchs/${p.match.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{p.match.home.name} – {p.match.away.name}</span>
                  <span className="text-xs text-steel">{p.market_label}, {pct(p.probability)}</span>
                </span>
                <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${p.result === "won" ? "bg-pitch-soft text-pitch-deep" : "bg-brick-soft text-brick"}`}>
                  {RESULT_LABEL[p.result]}
                </span>
              </Link>
            ))}
          </div>
        </Section>
      )}
    </>
  );
}
