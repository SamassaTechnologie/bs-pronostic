import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import { dateTime, pct, signedPct } from "@/lib/format";
import type { Meta, MatchSummary, PickCard as Pick } from "@/lib/types";
import { Freshness } from "@/components/Freshness";
import { PickCard } from "@/components/PickCard";
import { CompactPick, List, MatchRow } from "@/components/Rows";
import { Empty, ErrorBox, MoreLink, ProbBar, Section, Stat } from "@/components/ui";
import { Landing } from "@/components/Landing";
import { currentMember } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

type Dashboard = {
  date: string;
  last_sync: string | null;
  last_analysis: string | null;
  stats: {
    matches_analysed: number; matches_today: number; picks: number; competitions: number; insufficient: number;
    history_total: number; history_hit_rate: number | null; history_roi: number | null; history_settled: number;
    selection_settled: number; selection_hit_rate: number | null; selection_roi: number | null;
  };
  selection: Pick[];
  today_matches: { match: MatchSummary; status: string; n_picks: number; match_confidence: number; avoid: boolean }[];
  best_today: Pick[];
  by_probability: Pick[];
  top5: Pick[];
  avoid: { match: MatchSummary; reasons: string[]; match_confidence: number | null }[];
  markets: { key: string; label: string; count: number; avg_probability: number; avg_confidence: number }[];
  latest_analyses: { match: MatchSummary; computed_at: string; status: string; n_picks: number }[];
};

export default async function Home() {
  const tz = await userTz();
  const me = await currentMember();
  if (!me) {
    const summary = await backend<Parameters<typeof Landing>[0]["s"]>("/api/public-summary");
    return <Landing s={summary.ok ? summary.data : null} />;
  }
  const [dash, meta] = await Promise.all([
    backend<Dashboard>(`/api/dashboard?tz=${encodeURIComponent(tz)}`),
    backend<Meta>("/api/meta"),
  ]);
  if (!dash.ok) return <ErrorBox message={dash.error} />;
  const d = dash.data;
  const s = meta.data?.settings;
  const th = s ? [s.tier_c, s.tier_b, s.tier_a] : undefined;
  const longDate = new Intl.DateTimeFormat("fr-FR", { timeZone: tz, weekday: "long", day: "numeric", month: "long" }).format(new Date());

  return (
    <>
      <div className="mb-3 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight first-letter:uppercase">{longDate}</h1>
        <p className="text-sm text-steel">
          {d.stats.matches_analysed} matchs analysés sur {s?.days_ahead ?? 3} jours, {d.stats.picks} pronostics retenus.
        </p>
      </div>
      <Freshness lastSync={d.last_sync} lastAnalysis={d.last_analysis} tz={tz} />

      <div className="mt-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat label="Matchs du jour" value={d.stats.matches_today} hint={`${d.stats.competitions} championnats suivis`} />
        <Stat label="Pronostics retenus" value={d.stats.picks} hint={`${d.stats.insufficient} matchs écartés faute de données`} />
        <Stat
          label="Taux de réussite"
          value={d.stats.history_settled ? pct(d.stats.history_hit_rate) : "—"}
          hint={d.stats.history_settled ? `${d.stats.history_settled} pronostics réglés` : "Aucun pronostic encore réglé"}
        />
        <Stat label="ROI théorique" value={d.stats.history_roi !== null ? signedPct(d.stats.history_roi) : "—"} hint="Mise fixe, pronostics avec cote" />
      </div>

      <Section
        title="Sélection SAM du jour"
        action={<MoreLink href="/historique?selection=1">Bilan</MoreLink>}
      >
        <p className="-mt-1 mb-3 px-1 text-sm text-steel">
          5 pronostics au maximum, probabilité d&apos;au moins 75 % et confiance élevée, figés avant le match.
          {d.stats.selection_settled
            ? ` Bilan réel : ${pct(d.stats.selection_hit_rate)} sur ${d.stats.selection_settled} pronostics réglés.`
            : ""}
        </p>
        {d.selection.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {d.selection.map((p) => (
              <PickCard key={`s-${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />
            ))}
          </div>
        ) : (
          <Empty title="Aucun pronostic n'atteint les critères de la sélection pour le moment">
            Mieux vaut ne rien proposer qu&apos;un pronostic fragile. Les autres sélections restent consultables ci-dessous.
          </Empty>
        )}
      </Section>

      <Section title="Top 5 des sélections les plus fiables" action={<MoreLink href="/pronostics?sort=probability">Tout voir</MoreLink>}>
        {d.top5.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {d.top5.map((p, i) => (
              <PickCard key={`${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} rank={i + 1} />
            ))}
          </div>
        ) : (
          <Empty title="Aucune sélection ne passe les critères">
            Le moteur préfère ne rien proposer plutôt qu&apos;un pronostic fragile. Revenez après la prochaine synchronisation.
          </Empty>
        )}
      </Section>

      <div className="grid gap-x-6 md:grid-cols-2">
        <Section title="Meilleurs pronostics du jour">
          {d.best_today.length ? (
            <List>
              {d.best_today.slice(0, 6).map((p) => (
                <CompactPick key={`${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />
              ))}
            </List>
          ) : (
            <Empty title="Pas de pronostic retenu aujourd'hui">Consultez les prochains jours dans l&apos;onglet Pronostics.</Empty>
          )}
        </Section>

        <Section title="Classés par probabilité" action={<MoreLink href="/pronostics?sort=probability">Filtrer</MoreLink>}>
          {d.by_probability.length ? (
            <List>
              {d.by_probability.slice(0, 6).map((p) => (
                <CompactPick key={`${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />
              ))}
            </List>
          ) : (
            <Empty title="Aucun pronostic disponible" />
          )}
        </Section>
      </div>

      <Section title="Marchés les plus intéressants">
        {d.markets.length ? (
          <List>
            {d.markets.map((m) => (
              <Link key={m.key} href={`/pronostics?market=${encodeURIComponent(m.key)}&all=1`} className="block px-4 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-semibold text-night">{m.label}</span>
                  <span className="text-xs text-steel">
                    {m.count} sélection{m.count > 1 ? "s" : ""}, moyenne {pct(m.avg_probability)}
                  </span>
                </div>
                <div className="mt-1.5">
                  <ProbBar p={m.avg_probability} thresholds={th} size="sm" />
                </div>
              </Link>
            ))}
          </List>
        ) : (
          <Empty title="Rien à signaler pour le moment" />
        )}
      </Section>

      <div className="grid gap-x-6 md:grid-cols-2">
        <Section title="Matchs du jour">
          {d.today_matches.length ? (
            <List>
              {d.today_matches.map((t) => (
                <MatchRow
                  key={t.match.id}
                  match={t.match}
                  tz={tz}
                  right={
                    t.status !== "ok" ? (
                      <span className="shrink-0 rounded-md bg-mist px-2 py-0.5 text-[11px] text-steel">Données insuffisantes</span>
                    ) : t.n_picks ? (
                      <span className="shrink-0 rounded-md bg-pitch-soft px-2 py-0.5 text-[11px] font-semibold text-pitch-deep">
                        {t.n_picks} pronostic{t.n_picks > 1 ? "s" : ""}
                      </span>
                    ) : (
                      <span className="shrink-0 text-[11px] text-steel">Aucun retenu</span>
                    )
                  }
                />
              ))}
            </List>
          ) : (
            <Empty title="Aucun match aujourd'hui dans les championnats suivis" />
          )}
        </Section>

        <Section title="Matchs à éviter">
          {d.avoid.length ? (
            <List>
              {d.avoid.map((a) => (
                <div key={a.match.id}>
                  <MatchRow match={a.match} tz={tz} />
                  <ul className="-mt-1.5 space-y-0.5 px-4 pb-3 pl-[76px] text-xs text-brick">
                    {a.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </List>
          ) : (
            <Empty title="Aucun match signalé" />
          )}
        </Section>
      </div>

      <Section title="Dernières analyses">
        {d.latest_analyses.length ? (
          <List>
            {d.latest_analyses.map((a) => (
              <MatchRow
                key={a.match.id}
                match={a.match}
                tz={tz}
                right={<span className="shrink-0 text-[11px] text-steel">{dateTime(a.computed_at, tz)}</span>}
              />
            ))}
          </List>
        ) : (
          <Empty title="Aucune analyse effectuée" />
        )}
      </Section>
    </>
  );
}
