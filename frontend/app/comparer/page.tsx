import Link from "next/link";
import { Suspense } from "react";
import { backend, userTz } from "@/lib/api";
import { dayLabel, kickoffLabel, num, pct } from "@/lib/format";
import type { FormSummary, MatchSummary } from "@/lib/types";
import { Form } from "@/components/MatchLine";
import { TeamPicker } from "@/components/TeamPicker";
import { Empty, ErrorBox, Section } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Comparateur d'équipes" };

type Block = {
  team: { id: number; name: string; country: string };
  competition: { code: string; name: string } | null;
  standing: { position: number; points: number; played: number; teams: number; goal_difference: number } | null;
  last10: FormSummary; last20: FormSummary; home10: FormSummary; away10: FormSummary;
  common_scores: { score: string; count: number }[];
};
type Cmp = {
  a: Block; b: Block;
  h2h: { matches: MatchSummary[]; wins_a: number; draws: number; wins_b: number };
  next: MatchSummary | null;
};

type Row = [string, (x: FormSummary) => number | null | undefined, "pct" | "num" | "num1", boolean];
// [libellé, valeur, format, plus grand = mieux]
const ROWS: Row[] = [
  ["Points par match", (x) => x.points_per_match, "num", true],
  ["Buts marqués / match", (x) => x.goals_for_avg, "num", true],
  ["Buts encaissés / match", (x) => x.goals_against_avg, "num", false],
  ["Matchs à +2,5 buts", (x) => x.over25_rate, "pct", true],
  ["Les deux marquent", (x) => x.btts_rate, "pct", true],
  ["Sans encaisser", (x) => x.clean_sheet_rate, "pct", true],
  ["Sans marquer", (x) => x.failed_to_score_rate, "pct", false],
  ["Mène à la mi-temps", (x) => x.ht_lead_rate, "pct", true],
  ["Buts en 1re mi-temps / match", (x) => x.ht_goals_avg, "num", true],
  ["Corners / match (total)", (x) => x.corners_total_avg, "num1", true],
  ["Cartons / match (total)", (x) => x.cards_total_avg, "num1", true],
];

function fmt(v: number | null | undefined, f: Row[2]) {
  if (v === null || v === undefined) return "—";
  return f === "pct" ? pct(v) : num(v, f === "num1" ? 1 : 2);
}

function Compare({ title, a, b, rows, note }: { title: string; a: FormSummary; b: FormSummary; rows: Row[]; note?: string }) {
  return (
    <Section title={title}>
      <div className="overflow-hidden rounded-xl border border-line bg-white">
        <table className="w-full text-sm">
          <tbody>
            {rows.map(([label, fn, f, higher]) => {
              const va = a.played ? fn(a) : null, vb = b.played ? fn(b) : null;
              const both = va != null && vb != null && va !== vb;
              const aBest = both && (higher ? va! > vb! : va! < vb!);
              const bBest = both && !aBest;
              return (
                <tr key={label} className="border-t border-line first:border-0">
                  <td className={`w-[22%] py-2 pl-3 text-left font-bold ${aBest ? "text-pitch-deep" : ""}`}>{fmt(va, f)}</td>
                  <td className="py-2 text-center text-[12.5px] text-steel">{label}</td>
                  <td className={`w-[22%] py-2 pr-3 text-right font-bold ${bBest ? "text-pitch-deep" : ""}`}>{fmt(vb, f)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {note && <p className="mt-1.5 px-1 text-xs text-steel">{note}</p>}
    </Section>
  );
}

type SP = Record<string, string | string[] | undefined>;

export default async function Comparer({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const a = Number(sp.a), b = Number(sp.b);
  const tz = await userTz();
  const ready = a > 0 && b > 0 && a !== b;
  const res = ready ? await backend<Cmp>(`/api/compare?a=${a}&b=${b}`, { revalidate: 120 }) : null;
  const one = async (id: number) => (id > 0 ? (await backend<{ team: Block["team"] }>(`/api/teams/${id}`, { revalidate: 300 })) : null);
  const [ra, rb] = res?.ok ? [null, null] : await Promise.all([one(a), one(b)]);
  const ta = res?.ok ? res.data.a.team : ra?.ok ? ra.data.team : null;
  const tb = res?.ok ? res.data.b.team : rb?.ok ? rb.data.team : null;

  return (
    <>
      <div className="mb-3 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Comparateur d&apos;équipes</h1>
        <p className="text-sm text-steel">Deux équipes au choix, côte à côte : forme, buts, mi-temps, corners, cartons, confrontations.</p>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <Suspense><TeamPicker slot="a" current={ta} /></Suspense>
        <span className="text-xs font-bold text-steel">contre</span>
        <Suspense><TeamPicker slot="b" current={tb} /></Suspense>
      </div>

      {!ready ? (
        <div className="mt-5"><Empty title="Choisissez deux équipes">Tapez au moins deux lettres du nom, puis touchez l&apos;équipe.</Empty></div>
      ) : !res?.ok ? (
        <div className="mt-5"><ErrorBox message={res?.error || "Comparaison indisponible"} /></div>
      ) : (() => {
        const d = res.data;
        const h = d.h2h;
        return (
          <>
            {d.next && (
              <Link href={`/matchs/${d.next.id}`} className="mt-4 block rounded-xl border-2 border-pitch bg-white px-4 py-3 text-sm">
                <span className="font-bold text-pitch-deep">Prochaine confrontation</span> · {d.next.home.name} – {d.next.away.name}, {kickoffLabel(d.next.kickoff, tz)}
                <span className="block text-[12px] text-steel">Voir l&apos;analyse et les pronostics SAM du match</span>
              </Link>
            )}

            <Section title="Classement et forme">
              <div className="grid grid-cols-2 gap-2">
                {[d.a, d.b].map((x) => (
                  <Link key={x.team.id} href={`/equipes/${x.team.id}`} className="rounded-xl border border-line bg-white p-3">
                    <div className="truncate font-display text-[15px] font-bold">{x.team.name}</div>
                    <div className="truncate text-[12px] text-steel">{x.competition?.name ?? x.team.country}</div>
                    <div className="mt-1.5 text-sm">
                      {x.standing ? <><strong>{x.standing.position}<sup>e</sup></strong> sur {x.standing.teams} · {x.standing.points} pts</> : <span className="text-steel">Classement indisponible</span>}
                    </div>
                    <div className="mt-1.5"><Form seq={x.last10.sequence?.slice(0, 5)} /></div>
                  </Link>
                ))}
              </div>
            </Section>

            <Compare title="10 derniers matchs" a={d.a.last10} b={d.b.last10} rows={ROWS}
              note="En vert : la meilleure valeur des deux. Matchs toutes compétitions confondues, en base." />
            <Compare title={`${d.a.team.name} à domicile, ${d.b.team.name} à l'extérieur`} a={d.a.home10} b={d.b.away10} rows={ROWS.slice(0, 8)}
              note="10 derniers matchs de chaque équipe dans ce rôle." />

            <Section title="Scores les plus fréquents (20 derniers matchs)">
              <div className="grid grid-cols-2 gap-2">
                {[d.a, d.b].map((x) => (
                  <div key={x.team.id} className="rounded-xl border border-line bg-white p-3">
                    <div className="mb-1.5 truncate text-[13px] font-bold">{x.team.name}</div>
                    {x.common_scores.length ? x.common_scores.map((s) => (
                      <div key={s.score} className="flex justify-between text-sm"><span className="font-semibold">{s.score}</span><span className="text-steel">{s.count} fois</span></div>
                    )) : <span className="text-sm text-steel">Données insuffisantes</span>}
                  </div>
                ))}
              </div>
              <p className="mt-1.5 px-1 text-xs text-steel">Score vu du côté de l&apos;équipe : buts marqués – buts encaissés.</p>
            </Section>

            <Section title="Confrontations directes">
              {h.matches.length ? (
                <>
                  <div className="mb-2 grid grid-cols-3 gap-2 text-center">
                    <div className="rounded-xl bg-white p-2"><div className="font-display text-xl font-bold">{h.wins_a}</div><div className="truncate text-[11.5px] text-steel">{d.a.team.name}</div></div>
                    <div className="rounded-xl bg-white p-2"><div className="font-display text-xl font-bold">{h.draws}</div><div className="text-[11.5px] text-steel">Nuls</div></div>
                    <div className="rounded-xl bg-white p-2"><div className="font-display text-xl font-bold">{h.wins_b}</div><div className="truncate text-[11.5px] text-steel">{d.b.team.name}</div></div>
                  </div>
                  <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                    {h.matches.map((m) => (
                      <div key={m.id} className="flex items-center gap-2 px-3 py-2.5 text-sm">
                        <span className="w-16 shrink-0 text-xs text-steel">{dayLabel(m.kickoff, tz)}</span>
                        <span className="min-w-0 flex-1 truncate text-right font-semibold">{m.home.name}</span>
                        <span className="shrink-0 rounded bg-night px-2 py-0.5 text-xs font-bold text-white">{m.score ? `${m.score.home}-${m.score.away}` : "–"}</span>
                        <span className="min-w-0 flex-1 truncate font-semibold">{m.away.name}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <Empty title="Aucune confrontation en base" />
              )}
            </Section>
          </>
        );
      })()}
    </>
  );
}
