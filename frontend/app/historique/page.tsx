import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import { dayLabel, num, pct, RESULT_LABEL, signedPct } from "@/lib/format";
import type { GroupStat, HistoryRow, Performance } from "@/lib/types";
import { LineChart } from "@/components/LineChart";
import { Card, Empty, ErrorBox, Section, Stat, TierBadge } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Historique" };

const RESULT_STYLE: Record<string, string> = {
  won: "bg-pitch-soft text-pitch-deep",
  lost: "bg-brick-soft text-brick",
  pending: "bg-mist text-steel",
  void: "bg-mist text-steel",
  unverifiable: "bg-amber-soft text-amber",
};

function Breakdown({ rows }: { rows: GroupStat[] }) {
  const settled = rows.filter((r) => r.n > 0);
  if (!settled.length) return <p className="px-4 py-3 text-sm text-steel">Aucun pronostic réglé.</p>;
  return (
    <div className="scroll-x">
      <table className="w-full min-w-[480px] text-sm">
        <thead>
          <tr className="text-xs text-steel">
            <th className="px-4 py-2 text-left font-normal" />
            <th className="px-2 py-2 text-right font-normal">Réglés</th>
            <th className="px-2 py-2 text-right font-normal">Réussite</th>
            <th className="px-2 py-2 text-right font-normal">Annoncé</th>
            <th className="px-2 py-2 text-right font-normal">Écart</th>
            <th className="px-4 py-2 text-right font-normal">ROI</th>
          </tr>
        </thead>
        <tbody>
          {settled.map((r) => (
            <tr key={String(r.key)} className="border-t border-line">
              <td className="px-4 py-2 font-semibold">{r.label}</td>
              <td className="px-2 py-2 text-right">{r.n}</td>
              <td className="px-2 py-2 text-right font-semibold">{pct(r.hit_rate)}</td>
              <td className="px-2 py-2 text-right text-steel">{pct(r.avg_probability)}</td>
              <td className={`px-2 py-2 text-right ${r.gap !== null && r.gap > 0.03 ? "text-brick" : "text-steel"}`}>
                {r.gap === null ? "—" : `${r.gap > 0 ? "+" : ""}${Math.round(r.gap * 100)} pts`}
              </td>
              <td className="px-4 py-2 text-right">{r.roi === null ? "—" : signedPct(r.roi)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function Historique({ searchParams }: { searchParams: Promise<{ page?: string; resultat?: string }> }) {
  const sp = await searchParams;
  const tz = await userTz();
  const page = Math.max(0, Number(sp.page || 0));
  const filter = sp.resultat && RESULT_LABEL[sp.resultat] ? sp.resultat : "";
  const [perf, hist] = await Promise.all([
    backend<Performance>("/api/performance"),
    backend<{ total: number; items: HistoryRow[] }>(`/api/history?limit=30&offset=${page * 30}${filter ? `&result=${filter}` : ""}`),
  ]);
  if (!perf.ok) return <ErrorBox message={perf.error} />;
  const p = perf.data;
  const o = p.overall;

  return (
    <>
      <div className="mb-3 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Historique et performances</h1>
        <p className="text-sm text-steel">
          Chaque pronostic est figé au moment de sa publication. Les résultats sont réglés automatiquement à partir des scores
          officiels ; rien n&apos;est modifié après coup.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat label="Pronostics publiés" value={o.total} hint={`${o.pending} en attente`} />
        <Stat label="Gagnés / perdus" value={`${o.won} / ${o.lost}`} hint={o.void || o.unverifiable ? `${o.void} annulés, ${o.unverifiable} non vérifiables` : undefined} />
        <Stat label="Taux de réussite" value={pct(o.hit_rate, 1)} hint={o.avg_probability !== null ? `Probabilité annoncée ${pct(o.avg_probability, 1)}` : undefined} />
        <Stat label="Bénéfice théorique" value={o.staked ? `${o.profit > 0 ? "+" : ""}${num(o.profit, 1)} u` : "—"} hint={o.roi !== null ? `ROI ${signedPct(o.roi)} sur ${o.staked} mises` : "Aucune mise avec cote"} />
      </div>

      <Section title="Évolution">
        <div className="grid gap-3 md:grid-cols-2">
          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold">Bénéfice cumulé (unités)</h3>
            {o.staked === 0 ? (
              <p className="text-sm text-steel">Aucun pronostic réglé ne disposait d&apos;une cote : le bénéfice ne peut pas être calculé sans inventer de cotes.</p>
            ) : <LineChart label="Bénéfice cumulé" zero points={p.timeline.map((t) => ({ x: t.date.slice(5).split("-").reverse().join("/"), y: t.profit }))} format={(v) => num(v, 1)} />}
          </Card>
          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold">Taux de réussite cumulé</h3>
            <LineChart label="Taux de réussite cumulé" points={p.timeline.map((t) => ({ x: t.date.slice(5).split("-").reverse().join("/"), y: t.hit_rate }))} format={(v) => pct(v)} />
          </Card>
        </div>
        <p className="mt-2 px-1 text-xs text-steel">{p.stake_rule}</p>
      </Section>

      <Section title="Calibration des probabilités">
        <Card className="p-4 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            <span>Brier score <strong>{p.calibration.brier === null ? "—" : num(p.calibration.brier, 4)}</strong></span>
            <span>Log Loss <strong>{p.calibration.log_loss === null ? "—" : num(p.calibration.log_loss, 4)}</strong></span>
          </div>
          <p className="mt-1 text-xs text-steel">Plus ces valeurs sont basses, plus les probabilités annoncées sont justes.</p>
          {p.calibration.table.some((r) => r.n > 0) && (
            <div className="mt-3 space-y-2">
              {p.calibration.table.filter((r) => r.n > 0).map((r) => (
                <div key={r.low}>
                  <div className="flex justify-between text-xs">
                    <span>Annoncé {Math.round(r.low * 100)}–{Math.round(r.high * 100)} % ({r.n})</span>
                    <span>
                      prévu <strong>{pct(r.mean_predicted)}</strong>, observé <strong>{pct(r.observed_frequency)}</strong>
                    </span>
                  </div>
                  <div className="relative mt-1 h-2 rounded-full bg-line/70">
                    <div className="absolute inset-y-0 left-0 rounded-full bg-pitch" style={{ width: `${(r.observed_frequency ?? 0) * 100}%` }} />
                    <span className="absolute -top-1 -bottom-1 w-0.5 bg-night" style={{ left: `${(r.mean_predicted ?? 0) * 100}%` }} />
                  </div>
                </div>
              ))}
              <p className="text-xs text-steel">Trait foncé : probabilité moyenne annoncée. Barre verte : fréquence réellement observée.</p>
            </div>
          )}
        </Card>
      </Section>

      {(["by_tier", "by_confidence", "by_market", "by_competition"] as const).map((k) => (
        <Section key={k} title={{ by_tier: "Par niveau", by_confidence: "Par niveau de confiance", by_market: "Par marché", by_competition: "Par championnat" }[k]}>
          <Card>
            <Breakdown rows={p[k]} />
          </Card>
        </Section>
      ))}

      <Section title="Tous les pronostics">
        <div className="scroll-x mb-3 flex gap-1.5">
          {[["", "Tous"], ["won", "Gagnés"], ["lost", "Perdus"], ["pending", "En attente"]].map(([v, l]) => (
            <Link key={v} href={v ? `/historique?resultat=${v}` : "/historique"} className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-semibold ${filter === v ? "bg-night text-white" : "bg-white text-night"}`}>
              {l}
            </Link>
          ))}
        </div>
        {!hist.ok ? (
          <ErrorBox message={hist.error} />
        ) : hist.data.items.length ? (
          <>
            <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
              {hist.data.items.map((h) => (
                <Link key={h.id} href={`/matchs/${h.match.id}`} className="flex items-center gap-3 px-4 py-3">
                  <TierBadge tier={h.tier} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">
                      {h.match.home.name} – {h.match.away.name}
                      {h.match.score && <span className="ml-1.5 text-steel">{h.match.score.home}-{h.match.score.away}</span>}
                    </div>
                    <div className="truncate text-xs text-steel">
                      {h.market_label}, {pct(h.probability)}{h.odds ? `, cote ${num(h.odds)}` : ""}, {dayLabel(h.match.kickoff, tz)}
                    </div>
                  </div>
                  <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${RESULT_STYLE[h.result]}`}>{RESULT_LABEL[h.result] ?? h.result}</span>
                </Link>
              ))}
            </div>
            <div className="mt-3 flex justify-between text-sm font-semibold">
              {page > 0 ? <Link href={`/historique?page=${page - 1}${filter ? `&resultat=${filter}` : ""}`} className="text-sky">Plus récents</Link> : <span />}
              {(page + 1) * 30 < hist.data.total && <Link href={`/historique?page=${page + 1}${filter ? `&resultat=${filter}` : ""}`} className="text-sky">Plus anciens</Link>}
            </div>
          </>
        ) : (
          <Empty title="Aucun pronostic publié pour l'instant">L&apos;historique se remplit dès la première analyse avec des sélections retenues.</Empty>
        )}
      </Section>
    </>
  );
}
