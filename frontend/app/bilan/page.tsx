import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import { dayLabel, pct, RESULT_LABEL } from "@/lib/format";
import type { HistoryRow } from "@/lib/types";
import { ErrorBox } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Notre bilan",
  description: "Le bilan réel de SAM-Prédiction : chaque pronostic figé avant le match et réglé sur le score officiel.",
};

type P = { total: number; n: number; won: number; lost: number; hit_rate: number | null; avg_probability: number | null; gap: number | null; pending: number; staked: number; roi: number | null };
type Row = { label: string; n: number; won: number; hit_rate: number | null; avg_probability: number | null };
type Track = {
  generated_at: string; since: string | null;
  categories: { key: string; label: string; hint: string; periods: Record<"d7" | "d30" | "all", P> }[];
  calibration: { low: number; high: number; n: number; mean_predicted: number | null; observed_frequency: number | null }[];
  brier: number | null;
  by_competition: Row[]; by_family: Row[];
  banker_form: string[];
  recent: HistoryRow[];
};

const PERIODS: [keyof Track["categories"][number]["periods"], string][] = [["d7", "7 jours"], ["d30", "30 jours"], ["all", "Depuis le début"]];

function Rate({ p, big = false }: { p: P; big?: boolean }) {
  if (!p.n) return <span className={`${big ? "text-2xl" : "text-base"} font-display font-bold text-steel`}>—</span>;
  return <span className={`${big ? "text-[28px]" : "text-base"} font-display font-bold tabular-nums text-night`}>{pct(p.hit_rate)}</span>;
}

function Bars({ rows }: { rows: Row[] }) {
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
      {rows.map((r) => (
        <li key={r.label} className="px-3.5 py-2.5">
          <div className="flex items-baseline justify-between gap-3 text-[13.5px]">
            <span className="min-w-0 truncate font-semibold">{r.label}</span>
            <span className="shrink-0 tabular-nums"><strong>{pct(r.hit_rate)}</strong> <span className="text-steel">· {r.won}/{r.n}</span></span>
          </div>
          <div className="relative mt-1.5 h-1.5 rounded-full bg-mist">
            <div className="absolute inset-y-0 left-0 rounded-full bg-pitch" style={{ width: `${(r.hit_rate ?? 0) * 100}%` }} />
            {r.avg_probability !== null && (
              <div className="absolute -top-0.5 h-2.5 w-0.5 bg-night" style={{ left: `${r.avg_probability * 100}%` }} title="Probabilité annoncée" />
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export default async function Bilan({ searchParams }: { searchParams: Promise<{ periode?: string }> }) {
  const tz = await userTz();
  const { periode } = await searchParams;
  const per = PERIODS.find(([k]) => k === periode)?.[0] ?? "all";
  const res = await backend<Track>("/api/track-record", { revalidate: 300 });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const t = res.data;
  const cal = t.calibration.filter((c) => c.n > 0);
  const since = t.since ? new Intl.DateTimeFormat("fr-FR", { timeZone: tz, day: "numeric", month: "long", year: "numeric" }).format(new Date(t.since)) : null;

  return (
    <>
      <section className="-mx-3.5 -mt-4 bg-night px-4 pb-5 pt-5 text-white md:mx-0 md:mt-0 md:rounded-2xl md:px-6">
        <h1 className="font-display text-[26px] font-bold leading-tight tracking-tight">Notre bilan</h1>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-white/75">
          Chiffres réels uniquement. Chaque pronostic est figé avant le coup d&apos;envoi puis réglé automatiquement sur le score
          officiel ; aucun n&apos;est effacé ni modifié après coup{since ? `. Suivi depuis le ${since}` : ""}.
        </p>
        <nav className="mt-3 grid grid-cols-3 gap-1 rounded-lg bg-white/10 p-1" aria-label="Période">
          {PERIODS.map(([k, l]) => (
            <Link key={k} href={k === "all" ? "/bilan" : `/bilan?periode=${k}`} scroll={false} aria-current={k === per ? "page" : undefined}
              className={`rounded-md py-1.5 text-center text-[13px] font-bold ${k === per ? "bg-white text-night" : "text-white/75"}`}>{l}</Link>
          ))}
        </nav>
      </section>

      <div className="mt-4 grid gap-2.5 md:grid-cols-2">
        {t.categories.map((c) => {
          const p = c.periods[per];
          return (
            <div key={c.key} className={`rounded-2xl border bg-white p-4 ${c.key === "banker" ? "border-2 border-amber" : "border-line"}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-[15px] font-bold text-night">{c.label}</h2>
                  <p className="text-[12px] text-steel">{c.hint}</p>
                </div>
                <div className="shrink-0 text-right"><Rate p={p} big /></div>
              </div>
              {p.n ? (
                <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-[11.5px] text-steel">
                  <div className="rounded-lg bg-mist px-1 py-1.5"><div className="text-[15px] font-bold text-pitch-deep">{p.won}</div>gagnés</div>
                  <div className="rounded-lg bg-mist px-1 py-1.5"><div className="text-[15px] font-bold text-brick">{p.lost}</div>perdus</div>
                  <div className="rounded-lg bg-mist px-1 py-1.5"><div className="text-[15px] font-bold text-night">{pct(p.avg_probability)}</div>annoncé</div>
                </div>
              ) : (
                <p className="mt-2 text-[12.5px] text-steel">Données insuffisantes : aucun pronostic réglé sur cette période.</p>
              )}
              {c.key === "banker" && t.banker_form.length > 0 && (
                <div className="mt-2.5 flex items-center gap-1" aria-label="Forme des derniers bankers">
                  <span className="mr-1 text-[11.5px] text-steel">Derniers :</span>
                  {t.banker_form.map((r, i) => (
                    <span key={i} className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold text-white ${r === "won" ? "bg-pitch" : "bg-brick"}`}>
                      {r === "won" ? "G" : "P"}
                    </span>
                  ))}
                </div>
              )}
              {p.pending > 0 && <p className="mt-2 text-[11.5px] text-steel">{p.pending} en attente de résultat</p>}
            </div>
          );
        })}
      </div>

      {cal.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-1 px-1 font-display text-lg font-bold">Annoncé ou réel ?</h2>
          <p className="mb-2 px-1 text-[12.5px] text-steel">Pour chaque tranche de probabilité, la fréquence réellement observée. Un modèle honnête reste proche de ce qu&apos;il annonce.</p>
          <div className="overflow-hidden rounded-xl border border-line bg-white">
            <table className="w-full text-[13px]">
              <thead className="bg-mist text-[11.5px] text-steel">
                <tr><th className="px-3 py-2 text-left font-semibold">Probabilité</th><th className="px-3 py-2 text-right font-semibold">Annoncé</th><th className="px-3 py-2 text-right font-semibold">Réel</th><th className="px-3 py-2 text-right font-semibold">Pronos</th></tr>
              </thead>
              <tbody className="divide-y divide-line tabular-nums">
                {cal.map((c) => (
                  <tr key={c.low}>
                    <td className="px-3 py-2">{pct(c.low)} – {pct(c.high)}</td>
                    <td className="px-3 py-2 text-right">{pct(c.mean_predicted)}</td>
                    <td className={`px-3 py-2 text-right font-bold ${c.observed_frequency !== null && c.mean_predicted !== null && c.observed_frequency >= c.mean_predicted - 0.03 ? "text-pitch-deep" : "text-brick"}`}>{pct(c.observed_frequency)}</td>
                    <td className="px-3 py-2 text-right text-steel">{c.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {t.by_family.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-1 px-1 font-display text-lg font-bold">Par type de pari</h2>
          <p className="mb-2 px-1 text-[12.5px] text-steel">Barre verte : réussite réelle. Trait noir : probabilité annoncée. Au moins 10 pronostics réglés.</p>
          <Bars rows={t.by_family} />
        </section>
      )}

      {t.by_competition.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 px-1 font-display text-lg font-bold">Par championnat</h2>
          <Bars rows={t.by_competition} />
        </section>
      )}

      {t.recent.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 px-1 font-display text-lg font-bold">Derniers résultats mis en avant</h2>
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
            {t.recent.map((h) => (
              <li key={h.id} className="flex items-center gap-3 px-3.5 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px] font-semibold">
                    {h.match.home.name} – {h.match.away.name}
                    {h.match.score && <span className="ml-1.5 text-steel">{h.match.score.home}-{h.match.score.away}</span>}
                  </div>
                  <div className="truncate text-[12px] text-steel">
                    {h.banker ? "Banker · " : h.featured ? "Sélection · " : h.combo_pick ? "Combiné · " : ""}{h.market_label}, {pct(h.probability)} · {dayLabel(h.match.kickoff, tz)}
                  </div>
                </div>
                <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${h.result === "won" ? "bg-pitch-soft text-pitch-deep" : "bg-brick-soft text-brick"}`}>
                  {RESULT_LABEL[h.result] ?? h.result}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-6 grid gap-2.5 sm:grid-cols-2">
        <Link href="/historique" className="rounded-xl border border-line bg-white px-4 py-3.5 text-center font-semibold">Historique détaillé, pronostic par pronostic</Link>
        <Link href="/methodologie" className="rounded-xl border border-line bg-white px-4 py-3.5 text-center font-semibold">Comment sont calculées les probabilités</Link>
      </div>
      <p className="mt-4 px-1 text-[11.5px] text-steel">
        Un taux de réussite passé ne garantit pas les résultats futurs. Les paris comportent des risques : ne misez que ce que vous pouvez vous permettre de perdre.
      </p>
    </>
  );
}
