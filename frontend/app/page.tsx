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
import type { Combo, HistoryRow } from "@/lib/types";
import { ComboView } from "@/components/ComboBuilder";
import { num } from "@/lib/format";
import { kickoffLabel, RESULT_LABEL } from "@/lib/format";

export const dynamic = "force-dynamic";

type LiveItem = { match: MatchSummary; live: { home?: number | null; away?: number | null; minute?: string | number | null } | null; picks?: unknown[] };

type Dashboard = {
  date: string;
  last_sync: string | null;
  last_analysis: string | null;
  stats: {
    matches_analysed: number; matches_today: number; picks: number; competitions: number; insufficient: number;
    history_total: number; history_hit_rate: number | null; history_roi: number | null; history_settled: number;
    selection_settled: number; selection_hit_rate: number | null; selection_roi: number | null;
    value_settled: number; value_hit_rate: number | null; value_roi: number | null; value_avg_probability: number | null;
  };
  selection: Pick[];
  value_picks: Pick[];
  value_settings: { value_min_odds: number; value_max_odds: number; value_min_probability: number; value_min_confidence: number; value_max_per_day: number };
  combo_of_day: Combo[];
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
  const [dash, meta, recent, liveRes] = await Promise.all([
    backend<Dashboard>(`/api/dashboard?tz=${encodeURIComponent(tz)}`),
    backend<Meta>("/api/meta", { revalidate: 120 }),
    backend<{ settled: HistoryRow[]; waiting: HistoryRow[] }>("/api/recent-results?limit=8"),
    backend<{ live: LiveItem[] }>(`/api/live?tz=${encodeURIComponent(tz)}`),
  ]);
  const live = liveRes.ok ? liveRes.data.live : [];
  if (!dash.ok) return <ErrorBox message={dash.error} />;
  const d = dash.data;
  const s = meta.data?.settings;
  const th = s ? [s.tier_c, s.tier_b, s.tier_a] : undefined;
  const longDate = new Intl.DateTimeFormat("fr-FR", { timeZone: tz, weekday: "long", day: "numeric", month: "long" }).format(new Date());
  const hour = Number(new Intl.DateTimeFormat("fr-FR", { timeZone: tz, hour: "numeric", hour12: false }).format(new Date()));
  const hello = hour >= 18 || hour < 5 ? "Bonsoir" : "Bonjour";
  const first = (me.name || "").trim().split(/\s+/)[0];
  const settled = d.stats.history_settled;
  const tiers = meta.data?.calibration?.tiers;

  return (
    <>
      <section className="-mx-3.5 -mt-4 bg-night px-4 pb-5 pt-4 text-white md:mx-0 md:mt-0 md:rounded-2xl md:px-6 md:pt-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-white/60 first-letter:uppercase">{longDate}</p>
        <h1 className="mt-1 font-display text-[26px] font-bold leading-tight tracking-tight">{hello}{first ? `, ${first}` : ""}.</h1>
        <p className="mt-1 text-sm text-white/75">
          {d.stats.matches_analysed} matchs analysés dans {d.stats.competitions} championnats, {d.stats.picks} pronostics retenus.
        </p>
        <div className="mt-4 grid grid-cols-3 gap-2">
          <div className="rounded-xl bg-white/10 px-3 py-2.5">
            <div className="text-[11px] text-white/65">Aujourd&apos;hui</div>
            <div className="font-display text-xl font-bold">{d.stats.matches_today}</div>
            <div className="text-[11px] text-white/65">matchs</div>
          </div>
          <div className="rounded-xl bg-white/10 px-3 py-2.5">
            <div className="text-[11px] text-white/65">Réussite</div>
            <div className="font-display text-xl font-bold">{settled ? pct(d.stats.history_hit_rate) : "—"}</div>
            <div className="text-[11px] text-white/65">{settled ? `${settled} réglés` : "en attente"}</div>
          </div>
          <div className="rounded-xl bg-white/10 px-3 py-2.5">
            <div className="text-[11px] text-white/65">En direct</div>
            <div className="flex items-center gap-1.5 font-display text-xl font-bold">
              {live.length > 0 && <span className="h-2 w-2 animate-pulse rounded-full bg-brick" aria-hidden />}{live.length}
            </div>
            <div className="text-[11px] text-white/65">matchs</div>
          </div>
        </div>
        {tiers?.A && (
          <p className="mt-3 text-[11px] leading-relaxed text-white/60">
            Fiabilité mesurée sur {new Intl.NumberFormat("fr-FR").format(tiers.A.n)} pronostics de niveau A testés : {pct(tiers.A.mean_predicted)} annoncé,{" "}
            {pct(tiers.A.observed_frequency)} observé.
          </p>
        )}
      </section>

      <nav className="mt-4 grid grid-cols-4 gap-2" aria-label="Accès rapides">
        {[
          { href: "/pronostics?best=1", label: "Meilleurs pronos", icon: "M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z", tone: "bg-pitch-soft text-pitch-deep" },
          { href: "/jouer", label: "Jouer", icon: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5l3.8 2.8-1.5 4.4H9.7l-1.5-4.4z", tone: "bg-sky-soft text-sky" },
          { href: "/assistant", label: "Assistant IA", icon: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z", tone: "bg-night text-white" },
          { href: "/combines", label: "Combinés", icon: "M4 7h16M4 12h16M4 17h10", tone: "bg-amber-soft text-amber" },
        ].map((a) => (
          <Link key={a.href} href={a.href} className="flex flex-col items-center gap-1.5 rounded-xl border border-line bg-white px-1 py-3 text-center">
            <span className={`flex h-10 w-10 items-center justify-center rounded-full ${a.tone}`}>
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={a.icon} /></svg>
            </span>
            <span className="text-[12px] font-semibold leading-tight text-night">{a.label}</span>
          </Link>
        ))}
      </nav>

      <div className="mt-3"><Freshness lastSync={d.last_sync} lastAnalysis={d.last_analysis} tz={tz} /></div>

      {live.length > 0 && (
        <Section title="En direct maintenant" action={<MoreLink href="/direct">Tout le direct</MoreLink>}>
          <div className="-mx-3.5 flex gap-2.5 overflow-x-auto px-3.5 pb-1 [scrollbar-width:none] md:mx-0 md:px-0">
            {live.slice(0, 12).map((x) => (
              <Link key={x.match.id} href={`/matchs/${x.match.id}`} className="w-[220px] shrink-0 rounded-xl border border-line bg-white p-3">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="truncate text-steel">{x.match.competition.name}</span>
                  <span className="flex shrink-0 items-center gap-1 font-bold text-brick"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brick" aria-hidden />{x.live?.minute ? `${x.live.minute}'`.replace("''", "'") : "Direct"}</span>
                </div>
                <div className="mt-1.5 grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 text-sm">
                  <span className="truncate font-semibold">{x.match.home.name}</span><strong className="tabular-nums">{x.live?.home ?? "–"}</strong>
                  <span className="truncate font-semibold">{x.match.away.name}</span><strong className="tabular-nums">{x.live?.away ?? "–"}</strong>
                </div>
                {x.picks && x.picks.length > 0 && <div className="mt-1.5 truncate text-[11px] font-semibold text-pitch-deep">{x.picks.length} pronostic{x.picks.length > 1 ? "s" : ""} SAM en jeu</div>}
              </Link>
            ))}
          </div>
        </Section>
      )}

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

      <Section title="Combiné cote 2 du jour" action={<MoreLink href="/combines">Autre cote</MoreLink>}>
        <p className="-mt-1 mb-3 px-1 text-sm text-steel">
          2 ou 3 matchs au lieu de 8 à 10 : la même cote avec moins de risques de surprise. Matchs des 36 prochaines heures.
        </p>
        {d.combo_of_day.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {d.combo_of_day.map((c, i) => (
              <ComboView key={i} c={c} tz={tz} title={i === 0 ? `Combiné principal : ${c.n_legs} matchs` : `Alternative : ${c.n_legs} matchs`} />
            ))}
          </div>
        ) : (
          <Empty title="Pas de combinaison assez solide pour atteindre une cote de 2 en ce moment" />
        )}
      </Section>

      <Section title="Pronostics à cote" action={<MoreLink href="/historique?cote=1">Bilan</MoreLink>}>
        <p className="-mt-1 mb-3 px-1 text-sm text-steel">
          Cote d&apos;environ {num(d.value_settings.value_min_odds)} à {num(d.value_settings.value_max_odds)}, probabilité d&apos;au
          moins {pct(d.value_settings.value_min_probability)}, confiance d&apos;au moins {d.value_settings.value_min_confidence}/100 et
          modèle d&apos;accord avec le marché. Plus rémunérateurs, donc un peu moins sûrs que la Sélection SAM.
          {d.stats.value_settled
            ? ` Bilan réel : ${pct(d.stats.value_hit_rate)} sur ${d.stats.value_settled} pronostics réglés.`
            : ""}
        </p>
        {d.value_picks.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {d.value_picks.map((p) => (
              <PickCard key={`v-${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />
            ))}
          </div>
        ) : (
          <Empty title="Aucun pronostic à cote ne remplit les critères pour le moment" />
        )}
      </Section>


      <Section title="Derniers résultats vérifiés" action={<MoreLink href="/historique">Bilan complet</MoreLink>}>
        {recent.ok && (recent.data.waiting.length || recent.data.settled.length) ? (
          <List>
            {[...recent.data.waiting, ...recent.data.settled].slice(0, 10).map((h) => (
              <Link key={h.id} href={`/matchs/${h.match.id}`} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold">
                    {h.match.home.name} – {h.match.away.name}
                    {h.match.score && <span className="ml-1.5 text-steel">{h.match.score.home}-{h.match.score.away}</span>}
                  </div>
                  <div className="truncate text-xs text-steel">{h.market_label}, {pct(h.probability)}, {kickoffLabel(h.match.kickoff, tz)}</div>
                </div>
                <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${
                  h.result === "won" ? "bg-pitch-soft text-pitch-deep" : h.result === "lost" ? "bg-brick-soft text-brick" : "bg-amber-soft text-amber"}`}>
                  {h.result === "pending" ? "Résultat en attente" : RESULT_LABEL[h.result] ?? h.result}
                </span>
              </Link>
            ))}
          </List>
        ) : (
          <Empty title="Aucun pronostic terminé pour le moment" />
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

      </div>


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

    </>
  );
}
