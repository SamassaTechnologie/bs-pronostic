import Link from "next/link";
import { notFound } from "next/navigation";
import { backend, userTz } from "@/lib/api";
import { dateTime, dayLabel, kickoffLabel, num, pct, RESULT_LABEL } from "@/lib/format";
import type { Analysis, FormBlock, Market, Meta, MatchSummary } from "@/lib/types";
import { Factors } from "@/components/PickCard";
import { Card, ConfidenceBadge, Empty, ErrorBox, OddsInfo, ProbBar, Section, TierBadge } from "@/components/ui";

export const dynamic = "force-dynamic";

type Detail = {
  match: MatchSummary;
  analysis: Analysis | null;
  computed_at: string | null;
  predictions: { id: number; market_label: string; probability: number; tier: string; odds: number | null; result: string; created_at: string }[];
};

const FAMILY_ORDER: [string, string][] = [
  ["result", "Résultat 1X2"], ["double_chance", "Double chance"], ["goals", "Buts"], ["btts", "Les deux équipes marquent"],
  ["halftime", "1re mi-temps"], ["halftime_result", "Résultat à la mi-temps"], ["corners", "Corners"], ["cards", "Cartons"],
];

function Seq({ seq }: { seq?: string }) {
  if (!seq) return <span className="text-steel">—</span>;
  const c: Record<string, string> = { V: "bg-pitch text-white", N: "bg-line text-ink", D: "bg-brick text-white" };
  return (
    <span className="inline-flex gap-1" aria-label={`Forme : ${seq}`}>
      {seq.split("").map((r, i) => (
        <span key={i} className={`flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold ${c[r]}`}>{r}</span>
      ))}
    </span>
  );
}

function FormTable({ name, f }: { name: string; f: Record<string, FormBlock> }) {
  const rows: [string, (b: FormBlock) => string][] = [
    ["Points par match", (b) => num(b.points_per_match ?? null)],
    ["Buts marqués / match", (b) => num(b.goals_for_avg ?? null)],
    ["Buts encaissés / match", (b) => num(b.goals_against_avg ?? null)],
    ["Matchs à +2,5 buts", (b) => pct(b.over25_rate ?? null)],
    ["Les deux marquent", (b) => pct(b.btts_rate ?? null)],
    ["Corners par match (total)", (b) => num(b.corners_total_avg ?? null, 1)],
    ["Cartons par match (total)", (b) => num(b.cards_total_avg ?? null, 1)],
  ];
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">{name}</h3>
        <Seq seq={f.last5?.sequence} />
      </div>
      {f.last10?.played ? (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-xs text-steel">
              <th className="py-1 text-left font-normal" />
              <th className="py-1 text-right font-normal">5 derniers</th>
              <th className="py-1 text-right font-normal">10 derniers</th>
              <th className="py-1 text-right font-normal">10 sur ce terrain</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, fn]) => (
              <tr key={label} className="border-t border-line">
                <td className="py-1.5 text-steel">{label}</td>
                <td className="py-1.5 text-right font-semibold">{f.last5?.played ? fn(f.last5) : "—"}</td>
                <td className="py-1.5 text-right font-semibold">{fn(f.last10)}</td>
                <td className="py-1.5 text-right font-semibold">{f.venue10?.played ? fn(f.venue10) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-2 text-sm text-steel">Données insuffisantes : aucun match récent en base.</p>
      )}
    </Card>
  );
}

function MarketRow({ m, picked, th }: { m: Market; picked: boolean; th?: number[] }) {
  if (!m.available || m.probability === null) {
    return (
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <span className="text-sm text-steel">{m.label}</span>
        <span className="text-right text-xs text-steel">Données insuffisantes</span>
      </div>
    );
  }
  return (
    <details className={`group ${picked ? "bg-pitch-soft/50" : ""}`}>
      <summary className="block px-4 py-3">
        <div className="flex items-center gap-3">
          <TierBadge tier={m.tier!} />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-sm font-semibold">
                {m.label}
                {picked && <span className="ml-2 rounded bg-pitch px-1.5 py-0.5 text-[10px] font-bold text-white">Retenu</span>}
              </span>
              <span className="font-display text-lg font-bold">{pct(m.probability)}</span>
            </div>
            <div className="mt-1">
              <ProbBar p={m.probability} thresholds={th} size="sm" />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
              <OddsInfo odds={m.odds ?? null} edge={m.edge ?? null} bookmaker={m.bookmaker} />
              <span className="text-xs text-steel">Confiance {m.confidence?.score}/100</span>
            </div>
          </div>
        </div>
      </summary>
      <div className="space-y-3 px-4 pb-4 text-sm">
        <p>{m.explanation}</p>
        <div className="flex flex-wrap gap-2 text-xs text-steel">
          <ConfidenceBadge score={m.confidence!.score} level={m.confidence!.level} />
          <span>Cote juste {num(m.fair_odds ?? null)}</span>
          {m.implied_probability != null && <span>Probabilité du marché {pct(m.implied_probability)}</span>}
          {m.raw_probability != null && <span>Avant calibration {pct(m.raw_probability, 1)}</span>}
        </div>
        <Factors fav={m.factors_for ?? []} unf={m.factors_against ?? []} />
        {m.confidence?.components && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {m.confidence.components.map((c) => (
              <div key={c.key} className="flex justify-between gap-2 border-b border-line py-1">
                <span className="text-steel">{c.label}</span>
                <span className="font-semibold">{Math.round(c.value * 100)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}

export default async function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const tz = await userTz();
  const [res, meta] = await Promise.all([backend<Detail>(`/api/matches/${id}`), backend<Meta>("/api/meta", { revalidate: 120 })]);
  if (!res.ok) {
    if (res.error.includes("introuvable")) notFound();
    return <ErrorBox message={res.error} />;
  }
  const { match: m, analysis: a } = res.data;
  const s = meta.data?.settings;
  const th = s ? [s.tier_c, s.tier_b, s.tier_a] : undefined;
  const st = a?.standings;

  return (
    <>
      <Link href="/pronostics" className="mb-3 inline-block px-1 text-sm font-semibold text-sky">Retour aux pronostics</Link>
      <div className="rounded-2xl bg-night px-5 py-5 text-white">
        <div className="text-xs text-white/70">
          {m.competition.name}, {m.competition.country}. {kickoffLabel(m.kickoff, tz)}
        </div>
        <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
          <div>
            <div className="font-display text-xl font-bold leading-tight">{m.home.name}</div>
            {st?.home && <div className="text-xs text-white/65">{st.home.position}e, {st.home.points} pts</div>}
          </div>
          <div className="text-center font-display text-2xl font-bold">
            {m.score ? `${m.score.home} – ${m.score.away}` : "–"}
          </div>
          <div className="text-right">
            <div className="font-display text-xl font-bold leading-tight">{m.away.name}</div>
            {st?.away && <div className="text-xs text-white/65">{st.away.position}e, {st.away.points} pts</div>}
          </div>
        </div>
        {a?.expected_goals && (
          <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/15 pt-3 text-center text-xs text-white/70">
            <div>
              Buts attendus
              <div className="font-display text-base font-bold text-white">
                {num(a.expected_goals.home)} – {num(a.expected_goals.away)}
              </div>
            </div>
            <div>
              Corners attendus
              <div className="font-display text-base font-bold text-white">
                {a.expected_corners ? `${num(a.expected_corners.home, 1)} – ${num(a.expected_corners.away, 1)}` : "—"}
              </div>
            </div>
            <div>
              Cartons attendus
              <div className="font-display text-base font-bold text-white">
                {a.expected_cards ? `${num(a.expected_cards.home, 1)} – ${num(a.expected_cards.away, 1)}` : "—"}
              </div>
            </div>
          </div>
        )}
      </div>

      {!a ? (
        <div className="mt-4">
          <Empty title="Ce match n'a pas encore été analysé">L&apos;analyse couvre les matchs des prochains jours après chaque synchronisation.</Empty>
        </div>
      ) : a.status !== "ok" ? (
        <div className="mt-4 rounded-xl border border-amber/30 bg-amber-soft p-4 text-sm">
          <strong>Données insuffisantes : aucun pronostic n&apos;est proposé.</strong>
          <ul className="mt-1 list-disc pl-5">
            {a.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : (
        <>
          {a.avoid_reasons && a.avoid_reasons.length > 0 && (
            <div className="mt-4 rounded-xl border border-brick/30 bg-brick-soft p-4 text-sm text-brick">
              <strong>Match à éviter.</strong> {a.avoid_reasons.join(". ")}.
            </div>
          )}
          <Section title="Probabilités par marché">
            <p className="-mt-1 mb-3 px-1 text-xs text-steel">
              Touchez un marché pour voir l&apos;explication, les facteurs et le détail de la confiance. Les traits verticaux
              marquent les seuils des niveaux C, B et A.
            </p>
            <div className="space-y-3">
              {FAMILY_ORDER.map(([fam, label]) => {
                const ms = a.markets.filter((x) => x.family === fam);
                if (!ms.length) return null;
                return (
                  <div key={fam}>
                    <h3 className="mb-1.5 px-1 text-sm font-semibold text-steel">{label}</h3>
                    <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                      {ms.map((x) => (
                        <MarketRow key={x.key} m={x} picked={a.picks.includes(x.key)} th={th} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </Section>

          {a.top_scores && (
            <Section title="Scores les plus probables">
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                {a.top_scores.map((t) => (
                  <Card key={t.score} className="px-2 py-2.5 text-center">
                    <div className="font-display text-lg font-bold">{t.score}</div>
                    <div className="text-xs text-steel">{pct(t.probability, 1)}</div>
                  </Card>
                ))}
              </div>
            </Section>
          )}
        </>
      )}

      {a && (
        <>
          <Section title="Forme récente">
            <div className="grid gap-3 md:grid-cols-2">
              <FormTable name={m.home.name} f={a.form.home} />
              <FormTable name={m.away.name} f={a.form.away} />
            </div>
          </Section>

          <Section title="Confrontations directes">
            {a.h2h.n ? (
              <Card className="p-4 text-sm">
                <p>
                  {a.h2h.n} match{a.h2h.n > 1 ? "s" : ""} sur 5 ans : {a.h2h.home_team_wins} victoire(s) de {m.home.name},{" "}
                  {a.h2h.draws} nul(s), {a.h2h.away_team_wins} victoire(s) de {m.away.name}. Moyenne de {num(a.h2h.avg_total_goals ?? null)} buts.
                </p>
                <ul className="mt-2 divide-y divide-line">
                  {a.h2h.matches.map((h) => (
                    <li key={h.date} className="flex justify-between py-1.5">
                      <span className="text-steel">{dayLabel(h.date, tz)} {new Date(h.date).getFullYear()}</span>
                      <span className="font-semibold">
                        {h.home_id === m.home.id ? m.home.name : m.away.name} {h.score} {h.away_id === m.away.id ? m.away.name : m.home.name}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-steel">Poids limité dans le modèle : 8 % d’ajustement au maximum.</p>
              </Card>
            ) : (
              <Empty title="Aucune confrontation récente en base" />
            )}
          </Section>

          <Section title="Absences et suspensions">
            {a.injuries ? (
              <div className="grid gap-3 md:grid-cols-2">
                {(["home", "away"] as const).map((side) => (
                  <Card key={side} className="p-4 text-sm">
                    <h3 className="font-semibold">{side === "home" ? m.home.name : m.away.name}</h3>
                    {a.injuries![side].length ? (
                      <ul className="mt-1 space-y-0.5">
                        {a.injuries![side].map((i) => (
                          <li key={i.player}>
                            {i.player} <span className="text-steel">({i.reason || i.type})</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-steel">Aucune absence signalée par la source.</p>
                    )}
                  </Card>
                ))}
              </div>
            ) : (
              <Empty title="Information non disponible">Les absences nécessitent la clé API-Football (réglage serveur).</Empty>
            )}
          </Section>

          <Section title="Qualité des données et limites">
            <Card className="p-4 text-sm">
              <p>
                Modèle ajusté sur {a.data_quality.league_matches} matchs du championnat, dont {a.data_quality.home_matches} de {m.home.name} et{" "}
                {a.data_quality.away_matches} de {m.away.name}. Analyse du {dateTime(res.data.computed_at, tz)}.
              </p>
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-steel">
                {a.data_quality.limits.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </Card>
          </Section>
        </>
      )}

      {res.data.predictions.length > 0 && (
        <Section title="Pronostics publiés pour ce match">
          <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white text-sm">
            {res.data.predictions.map((p) => (
              <div key={p.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <div className="font-semibold">{p.market_label}</div>
                  <div className="text-xs text-steel">
                    Publié le {dateTime(p.created_at, tz)}, {pct(p.probability)}
                    {p.odds ? `, cote ${num(p.odds)}` : ""}
                  </div>
                </div>
                <span className="text-xs font-semibold">{RESULT_LABEL[p.result] ?? p.result}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
    </>
  );
}
