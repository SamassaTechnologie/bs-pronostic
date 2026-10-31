import Link from "next/link";
import { notFound } from "next/navigation";
import { backend, userTz } from "@/lib/api";
import { dateTime, dayLabel, kickoffLabel, num, pct, RESULT_LABEL } from "@/lib/format";
import type { Analysis, FormBlock, Market, Meta, MatchSummary } from "@/lib/types";
import { Factors } from "@/components/PickCard";
import { LiveHeader, type LiveState } from "@/components/LiveHeader";
import { flag } from "@/lib/flags";
import { Card, ConfidenceBadge, Empty, ErrorBox, OddsInfo, ProbBar, Section, TierBadge } from "@/components/ui";

export const dynamic = "force-dynamic";

type Trend = { text: string; side: "home" | "away" | "h2h"; strength: number; market: string | null; market_label: string | null; probability: number | null; kind: string };
type FormRow = { match_id: number; date: string; competition: string; venue: "home" | "away"; opponent: { id: number; name: string }; score: string; result: "V" | "N" | "D"; ht: string | null; corners: number | null; cards: number | null };
type Insights = {
  live: LiveState;
  trends: Trend[];
  form: { home: FormRow[]; away: FormRow[] };
  h2h: { n: number; home_wins: number; draws: number; away_wins: number; avg_goals: number | null; over25: number | null; btts: number | null;
    matches: { match_id: number; date: string; competition: string; home: string; away: string; score: string; ht: string | null }[] };
  standings: { team_id: number; team: string; position: number; played: number; wins: number; draws: number; losses: number; goal_difference: number; points: number }[];
  odds: { market_key: string; label: string; short: string; family: string; bookmakers: number; average: number; best: number; best_bookmaker: string; probability: number | null; fair_odds: number | null; value: number | null }[];
};

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

const TABS: [string, string, string][] = [["apercu", "Aperçu", "Aperçu"], ["pronostics", "Pronostics", "Pronos"], ["tendances", "Tendances", "Tendances"], ["stats", "Stats", "Stats"], ["cotes", "Cotes", "Cotes"]];
const RES_STYLE: Record<string, string> = { V: "bg-pitch text-white", N: "bg-line text-ink", D: "bg-brick text-white" };

function TrendItem({ t }: { t: Trend }) {
  return (
    <li className="flex gap-3 px-4 py-3">
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${t.side === "h2h" ? "bg-sky" : t.side === "home" ? "bg-pitch" : "bg-amber"}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-[15px] leading-snug">{t.text}</p>
        {t.market_label && (
          <p className="mt-0.5 text-xs text-steel">
            {t.market_label}{t.probability != null ? <> : <strong className="text-night">{pct(t.probability)}</strong> selon notre modèle</> : ""}
          </p>
        )}
      </div>
    </li>
  );
}

function FormList({ name, rows, tz }: { name: string; rows: FormRow[]; tz: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-white">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h3 className="font-semibold">{name}</h3>
        <span className="inline-flex gap-0.5">
          {rows.slice(0, 5).reverse().map((r) => (
            <span key={r.match_id} className={`flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold ${RES_STYLE[r.result]}`}>{r.result}</span>
          ))}
        </span>
      </div>
      {rows.length ? (
        <ul className="divide-y divide-line">
          {rows.map((r) => (
            <li key={r.match_id} className="flex items-center gap-2.5 px-4 py-2 text-sm">
              <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-bold ${RES_STYLE[r.result]}`}>{r.result}</span>
              <div className="min-w-0 flex-1">
                <Link href={`/equipes/${r.opponent.id}`} className="block truncate font-semibold">
                  {r.venue === "home" ? "contre " : "à "}{r.opponent.name}
                </Link>
                <span className="block truncate text-xs text-steel">
                  {dayLabel(r.date, tz)}, {r.competition}{r.corners != null ? `, ${r.corners} corners` : ""}{r.cards != null ? `, ${r.cards} cartons` : ""}
                </span>
              </div>
              <span className="shrink-0 text-right">
                <span className="block font-bold">{r.score}</span>
                {r.ht && <span className="block text-[11px] text-steel">MT {r.ht}</span>}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-3 text-sm text-steel">Aucun match en base.</p>
      )}
    </div>
  );
}

function mainPick(a: Analysis, featured: Set<string>): Market | null {
  const avail = a.markets.filter((x) => x.available && x.probability !== null);
  const feat = avail.find((x) => featured.has(x.key));
  if (feat) return feat;
  const pick = a.picks.map((k) => avail.find((x) => x.key === k)).find(Boolean);
  return pick ?? null;
}

export default async function MatchPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ onglet?: string }> }) {
  const { id } = await params;
  const { onglet } = await searchParams;
  if (!/^\d+$/.test(id)) notFound();
  const tz = await userTz();
  const [res, meta, ins] = await Promise.all([
    backend<Detail>(`/api/matches/${id}`),
    backend<Meta>("/api/meta", { revalidate: 120 }),
    backend<Insights>(`/api/matches/${id}/insights`),
  ]);
  if (!res.ok) {
    if (res.error.includes("introuvable")) notFound();
    return <ErrorBox message={res.error} />;
  }
  const { match: m, analysis: a } = res.data;
  const s = meta.data?.settings;
  const th = s ? [s.tier_c, s.tier_b, s.tier_a] : undefined;
  const st = a?.standings;
  const x = ins.ok ? ins.data : null;
  const tab = TABS.some(([k]) => k === onglet) ? onglet! : "apercu";
  const featured = new Set(res.data.predictions.filter((p) => (p as { featured?: boolean }).featured).map((p) => (p as { market_key?: string }).market_key ?? ""));
  const main = a && a.status === "ok" ? mainPick(a, featured) : null;
  const others = a && a.status === "ok" ? a.picks.filter((k) => k !== main?.key).map((k) => a.markets.find((mk) => mk.key === k)).filter(Boolean) as Market[] : [];
  const initialLive: LiveState = x?.live ?? (m.score ? { state: "finished", label: "Terminé", home: m.score.home, away: m.score.away } : { state: "scheduled", label: "À venir" });
  const homeTrends = x?.trends.filter((t) => t.side === "home") ?? [];
  const awayTrends = x?.trends.filter((t) => t.side === "away") ?? [];
  const h2hTrends = x?.trends.filter((t) => t.side === "h2h") ?? [];

  return (
    <>
      <Link href="/pronostics" className="mb-3 inline-block px-1 text-sm font-semibold text-sky">Retour aux pronostics</Link>
      <LiveHeader match={m} initial={initialLive} tz={tz} homeStanding={st?.home} awayStanding={st?.away}>
        {a?.expected_goals && (
          <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/15 pt-3 text-center text-xs text-white/70">
            <div>Buts attendus<div className="font-display text-base font-bold text-white">{num(a.expected_goals.home)} – {num(a.expected_goals.away)}</div></div>
            <div>Corners attendus<div className="font-display text-base font-bold text-white">{a.expected_corners ? `${num(a.expected_corners.home, 1)} – ${num(a.expected_corners.away, 1)}` : "—"}</div></div>
            <div>Cartons attendus<div className="font-display text-base font-bold text-white">{a.expected_cards ? `${num(a.expected_cards.home, 1)} – ${num(a.expected_cards.away, 1)}` : "—"}</div></div>
          </div>
        )}
      </LiveHeader>

      <div className="sticky top-[calc(env(safe-area-inset-top)+60px)] z-20 -mx-3.5 mt-4 bg-mist/95 px-3.5 py-2 backdrop-blur md:static md:mx-0 md:px-0">
        <div className="grid grid-cols-5 gap-0.5 rounded-lg bg-white p-1" role="tablist">
          {TABS.map(([k, l, short]) => (
            <Link key={k} href={`/matchs/${m.id}?onglet=${k}`} role="tab" aria-selected={tab === k} replace scroll={false}
              className={`whitespace-nowrap rounded-md px-0.5 py-2 text-center text-[13px] font-bold sm:text-sm ${tab === k ? "bg-night text-white" : "text-steel"}`}>
              <span className="sm:hidden">{short}</span><span className="hidden sm:inline">{l}</span>
            </Link>
          ))}
        </div>
      </div>

      {tab === "apercu" && (
        <>
          {!a ? (
            <div className="mt-4"><Empty title="Ce match n'a pas encore été analysé">L&apos;analyse couvre les matchs des prochains jours après chaque synchronisation.</Empty></div>
          ) : a.status !== "ok" ? (
            <div className="mt-4 rounded-xl border border-amber/30 bg-amber-soft p-4 text-sm">
              <strong>Données insuffisantes : aucun pronostic n&apos;est proposé.</strong>
              <ul className="mt-1 list-disc pl-5">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          ) : (
            <>
              {a.avoid_reasons && a.avoid_reasons.length > 0 && (
                <div className="mt-4 rounded-xl border border-brick/30 bg-brick-soft p-4 text-sm text-brick">
                  <strong>Match à éviter.</strong> {a.avoid_reasons.join(". ")}.
                </div>
              )}
              <Section title="Notre pronostic">
                {main ? (
                  <Card className="overflow-hidden">
                    <div className="px-4 pt-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-steel">{featured.has(main.key) ? "Sélection SAM du jour" : "Pronostic retenu"}</div>
                          <div className="mt-0.5 font-display text-xl font-bold leading-tight">{main.label}</div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            <TierBadge tier={main.tier!} />
                            <ConfidenceBadge score={main.confidence!.score} level={main.confidence!.level} />
                          </div>
                        </div>
                        <div className="shrink-0 text-right font-display text-4xl font-bold">{pct(main.probability)}</div>
                      </div>
                      <div className="mt-3"><ProbBar p={main.probability!} thresholds={th} /></div>
                      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                        <OddsInfo odds={main.odds ?? null} edge={main.edge ?? null} bookmaker={main.bookmaker} />
                        <span className="text-xs text-steel">Cote juste {num(main.fair_odds ?? null)}</span>
                      </div>
                    </div>
                    <div className="mt-3 space-y-3 border-t border-line px-4 py-3 text-sm">
                      <p>{main.explanation}</p>
                      <Factors fav={main.factors_for ?? []} unf={main.factors_against ?? []} />
                    </div>
                  </Card>
                ) : (
                  <Empty title="Aucun pronostic ne passe nos critères sur ce match">
                    Les probabilités de tous les marchés restent consultables dans l&apos;onglet Pronostics.
                  </Empty>
                )}
                {others.length > 0 && (
                  <div className="mt-3">
                    <h3 className="mb-1.5 px-1 text-sm font-semibold text-steel">Autres pronostics retenus</h3>
                    <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                      {others.map((o) => (
                        <div key={o.key} className="flex items-center gap-3 px-4 py-3">
                          <TierBadge tier={o.tier!} />
                          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{o.label}</span>
                          <span className="text-xs text-steel">conf. {o.confidence?.score}</span>
                          <span className="w-12 text-right font-bold">{pct(o.probability)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </Section>
            </>
          )}

          {x && x.trends.length > 0 && (
            <Section title="Faits clés" action={<Link href={`/matchs/${m.id}?onglet=tendances`} replace scroll={false} className="text-sm font-semibold text-sky">Toutes les tendances</Link>}>
              <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                {x.trends.slice(0, 5).map((t) => <TrendItem key={t.text} t={t} />)}
              </ul>
            </Section>
          )}

          {a?.top_scores && a.status === "ok" && (
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

          {a && (
            <Section title="Absences et suspensions">
              {a.injuries ? (
                <div className="grid gap-3 md:grid-cols-2">
                  {(["home", "away"] as const).map((side) => (
                    <Card key={side} className="p-4 text-sm">
                      <h3 className="font-semibold">{side === "home" ? m.home.name : m.away.name}</h3>
                      {a.injuries![side].length ? (
                        <ul className="mt-1 space-y-0.5">
                          {a.injuries![side].map((i) => <li key={i.player}>{i.player} <span className="text-steel">({i.reason || i.type})</span></li>)}
                        </ul>
                      ) : <p className="text-steel">Aucune absence signalée par la source.</p>}
                    </Card>
                  ))}
                </div>
              ) : (
                <Empty title="Information non disponible pour ce match">Les absences sont récupérées pour les matchs des prochaines 48 heures.</Empty>
              )}
            </Section>
          )}

          <Section title="Informations">
            <Card className="divide-y divide-line text-sm">
              <div className="flex justify-between gap-3 px-4 py-2.5"><span className="text-steel">Compétition</span><Link href={`/ligues/${m.competition.code}`} className="font-semibold">{flag(m.competition.country)} {m.competition.name}</Link></div>
              <div className="flex justify-between gap-3 px-4 py-2.5"><span className="text-steel">Coup d&apos;envoi</span><span className="font-semibold">{dateTime(m.kickoff, tz)}</span></div>
              {m.season && <div className="flex justify-between gap-3 px-4 py-2.5"><span className="text-steel">Saison</span><span className="font-semibold">{m.season}</span></div>}
              {res.data.computed_at && <div className="flex justify-between gap-3 px-4 py-2.5"><span className="text-steel">Analyse du</span><span className="font-semibold">{dateTime(res.data.computed_at, tz)}</span></div>}
            </Card>
          </Section>
        </>
      )}

      {tab === "pronostics" && (
        <>
          {!a || a.status !== "ok" ? (
            <div className="mt-4"><Empty title="Pas de probabilités disponibles pour ce match">{a?.reasons?.join(". ")}</Empty></div>
          ) : (
            <>
              <Section title="Probabilités par marché">
                <p className="-mt-1 mb-3 px-1 text-xs text-steel">
                  Touchez un marché pour voir l&apos;explication, les facteurs et le détail de la confiance. Les traits verticaux
                  marquent les seuils des niveaux C, B et A.
                </p>
                <div className="space-y-3">
                  {FAMILY_ORDER.map(([fam, label]) => {
                    const ms = a.markets.filter((mk) => mk.family === fam);
                    if (!ms.length) return null;
                    return (
                      <div key={fam}>
                        <h3 className="mb-1.5 px-1 text-sm font-semibold text-steel">{label}</h3>
                        <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                          {ms.map((mk) => <MarketRow key={mk.key} m={mk} picked={a.picks.includes(mk.key)} th={th} />)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Section>
              <Section title="Qualité des données et limites">
                <Card className="p-4 text-sm">
                  <p>
                    Modèle ajusté sur {a.data_quality.league_matches} matchs du championnat, dont {a.data_quality.home_matches} de {m.home.name} et{" "}
                    {a.data_quality.away_matches} de {m.away.name}. Analyse du {dateTime(res.data.computed_at, tz)}.
                  </p>
                  <ul className="mt-2 list-disc space-y-0.5 pl-5 text-steel">{a.data_quality.limits.map((l) => <li key={l}>{l}</li>)}</ul>
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
                      <div className="text-xs text-steel">Publié le {dateTime(p.created_at, tz)}, {pct(p.probability)}{p.odds ? `, cote ${num(p.odds)}` : ""}</div>
                    </div>
                    <span className="text-xs font-semibold">{RESULT_LABEL[p.result] ?? p.result}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </>
      )}

      {tab === "tendances" && (
        <>
          {!x || !x.trends.length ? (
            <div className="mt-4"><Empty title="Aucune tendance marquante">Pas de série ni de fréquence assez nette sur les derniers matchs.</Empty></div>
          ) : (
            ([[m.home.name, homeTrends], [m.away.name, awayTrends], ["Confrontations directes", h2hTrends]] as [string, Trend[]][]).map(([title, list]) =>
              list.length ? (
                <Section key={title} title={title}>
                  <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                    {list.map((t) => <TrendItem key={t.text} t={t} />)}
                  </ul>
                </Section>
              ) : null)
          )}
          <p className="mt-3 px-1 text-xs text-steel">
            Calculées sur les matchs réels en base (toutes compétitions suivies). Une tendance passée ne garantit pas la suite :
            comparez-la à la probabilité du modèle affichée sous chaque fait.
          </p>
        </>
      )}

      {tab === "stats" && (
        <>
          <Section title="Confrontations directes">
            {x && x.h2h.n ? (
              <Card className="p-4 text-sm">
                <div className="flex h-3 overflow-hidden rounded-full" role="img"
                  aria-label={`${x.h2h.home_wins} victoires de ${m.home.name}, ${x.h2h.draws} nuls, ${x.h2h.away_wins} victoires de ${m.away.name}`}>
                  <div className="bg-pitch" style={{ width: `${(x.h2h.home_wins / x.h2h.n) * 100}%` }} />
                  <div className="bg-line" style={{ width: `${(x.h2h.draws / x.h2h.n) * 100}%` }} />
                  <div className="bg-amber" style={{ width: `${(x.h2h.away_wins / x.h2h.n) * 100}%` }} />
                </div>
                <div className="mt-2 grid grid-cols-3 text-center text-xs">
                  <div><div className="font-display text-xl font-bold text-pitch-deep">{x.h2h.home_wins}</div>{m.home.name}</div>
                  <div><div className="font-display text-xl font-bold">{x.h2h.draws}</div>Nuls</div>
                  <div><div className="font-display text-xl font-bold text-amber">{x.h2h.away_wins}</div>{m.away.name}</div>
                </div>
                <div className="mt-3 flex flex-wrap justify-center gap-x-5 gap-y-1 text-xs text-steel">
                  <span>Moyenne {num(x.h2h.avg_goals)} buts</span><span>Plus de 2,5 : {pct(x.h2h.over25)}</span><span>Les deux marquent : {pct(x.h2h.btts)}</span>
                </div>
                <ul className="mt-3 divide-y divide-line border-t border-line">
                  {x.h2h.matches.map((h) => (
                    <li key={h.match_id} className="flex items-center gap-2 py-2">
                      <span className="w-16 shrink-0 text-xs text-steel">{new Date(h.date).toLocaleDateString("fr-FR", { timeZone: tz, day: "2-digit", month: "2-digit", year: "2-digit" })}</span>
                      <span className="min-w-0 flex-1 truncate text-right font-semibold">{h.home}</span>
                      <span className="shrink-0 rounded bg-night px-2 py-0.5 text-xs font-bold text-white">{h.score}</span>
                      <span className="min-w-0 flex-1 truncate font-semibold">{h.away}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-steel">Poids limité dans le modèle : 8 % d&apos;ajustement au maximum.</p>
              </Card>
            ) : <Empty title="Aucune confrontation en base entre ces deux équipes" />}
          </Section>

          <Section title="Derniers matchs">
            <div className="grid gap-3 md:grid-cols-2">
              <FormList name={m.home.name} rows={x?.form.home ?? []} tz={tz} />
              <FormList name={m.away.name} rows={x?.form.away ?? []} tz={tz} />
            </div>
          </Section>

          {a && (
            <Section title="Forme comparée">
              <div className="grid gap-3 md:grid-cols-2">
                <FormTable name={m.home.name} f={a.form.home} />
                <FormTable name={m.away.name} f={a.form.away} />
              </div>
            </Section>
          )}

          {x && x.standings.length > 0 && (
            <Section title="Classement" action={<Link href={`/ligues/${m.competition.code}?vue=classement`} className="text-sm font-semibold text-sky">Complet</Link>}>
              <div className="overflow-hidden rounded-xl border border-line bg-white">
                <table className="w-full text-sm">
                  <thead><tr className="text-xs text-steel">
                    <th className="w-8 py-2 pl-3 text-left font-normal">#</th><th className="py-2 text-left font-normal">Équipe</th>
                    <th className="px-1 py-2 text-right font-normal">J</th><th className="px-1 py-2 text-right font-normal">Diff</th><th className="px-3 py-2 text-right font-normal">Pts</th>
                  </tr></thead>
                  <tbody>
                    {x.standings.map((r) => {
                      const mine = r.team_id === m.home.id || r.team_id === m.away.id;
                      return (
                        <tr key={r.team_id} className={`border-t border-line ${mine ? "bg-pitch-soft font-bold" : ""}`}>
                          <td className="py-1.5 pl-3 text-steel">{r.position}</td>
                          <td className="max-w-0 py-1.5"><Link href={`/equipes/${r.team_id}`} className="block truncate">{r.team}</Link></td>
                          <td className="px-1 py-1.5 text-right">{r.played}</td>
                          <td className="px-1 py-1.5 text-right">{r.goal_difference > 0 ? `+${r.goal_difference}` : r.goal_difference}</td>
                          <td className="px-3 py-1.5 text-right font-bold">{r.points}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Section>
          )}
        </>
      )}

      {tab === "cotes" && (
        <Section title="Cotes et valeur">
          {x && x.odds.length ? (
            <>
              <div className="overflow-hidden rounded-xl border border-line bg-white">
                <table className="w-full text-sm">
                  <thead><tr className="text-xs text-steel">
                    <th className="py-2 pl-4 text-left font-normal">Marché</th><th className="px-1 py-2 text-right font-normal">SAM</th>
                    <th className="px-1 py-2 text-right font-normal">Moy.</th><th className="px-1 py-2 text-right font-normal">Max</th><th className="py-2 pr-4 text-right font-normal">Valeur</th>
                  </tr></thead>
                  <tbody>
                    {x.odds.map((o) => (
                      <tr key={o.market_key} className="border-t border-line">
                        <td className="py-2 pl-4"><span className="block font-semibold">{o.short}</span><span className="block text-[11px] leading-tight text-steel">{o.bookmakers} offre{o.bookmakers > 1 ? "s" : ""}, max. {o.best_bookmaker}</span></td>
                        <td className="px-1 py-2 text-right">{o.probability != null ? pct(o.probability) : "—"}</td>
                        <td className="px-1 py-2 text-right">{num(o.average)}</td>
                        <td className="px-1 py-2 text-right font-bold">{num(o.best)}</td>
                        <td className={`py-2 pr-4 text-right font-semibold ${o.value == null ? "text-steel" : o.value > 0.02 ? "text-pitch-deep" : o.value < -0.02 ? "text-brick" : "text-steel"}`}>
                          {o.value == null ? "—" : `${o.value > 0 ? "+" : ""}${Math.round(o.value * 100)} %`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 px-1 text-xs text-steel">
                1 / X / 2 : victoire domicile / nul / victoire extérieur ; +2,5 : plus de 2,5 buts ; BTTS : les deux équipes marquent ; MT : 1re mi-temps.
                Valeur = probabilité SAM × meilleure cote − 1. Une valeur positive signifie que la cote dépasse la cote juste du modèle ;
                ce n&apos;est pas une garantie de gain. Cotes relevées lors de la dernière synchronisation : vérifiez-les chez votre bookmaker.
              </p>
            </>
          ) : (
            <Empty title="Aucune cote disponible pour ce match">Les cotes arrivent quelques jours avant le match selon les sources.</Empty>
          )}
        </Section>
      )}
    </>
  );
}
