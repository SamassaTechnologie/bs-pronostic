import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import { pct } from "@/lib/format";
import type { Meta, MatchSummary, PickCard as Pick } from "@/lib/types";
import { Freshness } from "@/components/Freshness";
import { PickCard } from "@/components/PickCard";
import { CompactPick, List, MatchRow } from "@/components/Rows";
import { Empty, ErrorBox, MoreLink } from "@/components/ui";
import { Category, SubCategory } from "@/components/Category";
import { flag } from "@/lib/flags";
import { isPopular, popularRank } from "@/lib/popular";
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
  combo_picks?: Pick[];
  combo_performance?: { total: number; n: number; won: number; hit_rate: number | null; avg_probability: number | null };
  value_settings: { value_min_odds: number; value_max_odds: number; value_min_probability: number; value_min_confidence: number; value_max_per_day: number };
  combo_of_day: Combo[];
  today_matches: { match: MatchSummary; status: string; n_picks: number; match_confidence: number; avoid: boolean }[];
  best_today: Pick[];
  by_probability: Pick[];
  top5: Pick[];
  avoid: { match: MatchSummary; reasons: string[]; match_confidence: number | null }[];
  markets: { key: string; label: string; count: number; avg_probability: number; avg_confidence: number }[];
  latest_analyses: { match: MatchSummary; computed_at: string; status: string; n_picks: number }[];
  popular?: {
    code: string; name: string; country: string; n_matches: number; n_picks: number;
    matches: { match: MatchSummary; status: string; n_picks: number; avoid: boolean; best: { label: string; probability: number; featured: boolean } | null }[];
  }[];
};

const IC = {
  live: "M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4",
  star: "M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z",
  chart: "M4 19h16M6 16V9m6 7V5m6 11v-4",
  combo: "M4 7h16M4 12h16M4 17h10",
  calendar: "M7 3v3M17 3v3M4 8h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  trend: "M4 19V5M4 19h16M8 15l3-4 3 2 4-6",
};

/** Heure compacte pour les listes : « Auj. 19:00 », « Dem. 14:00 » ou « Sam. 14:00 ». */
function shortKick(iso: string, tz: string): [string, string] {
  const day = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const k = new Date(iso);
  const t = new Intl.DateTimeFormat("fr-FR", { timeZone: tz, hour: "2-digit", minute: "2-digit" }).format(k);
  const now = new Date();
  if (day(k) === day(now)) return ["Auj.", t];
  if (day(k) === day(new Date(now.getTime() + 86400000))) return ["Dem.", t];
  const w = new Intl.DateTimeFormat("fr-FR", { timeZone: tz, weekday: "short" }).format(k).replace(".", "");
  return [w.charAt(0).toUpperCase() + w.slice(1) + ".", t];
}

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
  // Matchs du jour regroupés par compétition (l'ordre du serveur place les grands championnats en tête)
  const todayGroups: { code: string; name: string; country: string; popular: boolean; rows: Dashboard["today_matches"] }[] = [];
  for (const t of d.today_matches) {
    const c = t.match.competition;
    let g = todayGroups.find((x) => x.code === c.code);
    if (!g) { g = { code: c.code, name: c.name, country: c.country, popular: isPopular(c.code), rows: [] }; todayGroups.push(g); }
    g.rows.push(t);
  }
  todayGroups.sort((a, b) => popularRank(a.code) - popularRank(b.code));

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
          meta.data?.ai?.assistant !== false
            ? { href: "/assistant", label: "Assistant IA", icon: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z", tone: "bg-night text-white" }
            : { href: "/historique", label: "Bilan", icon: "M4 19V5M4 19h16M8 15l3-4 3 2 4-6", tone: "bg-night text-white" },
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

      {/* Sommaire des catégories */}
      <nav className="-mx-3.5 mt-3 flex gap-1.5 overflow-x-auto px-3.5 pb-1 [scrollbar-width:none] md:mx-0 md:px-0" aria-label="Catégories">
        {[
          ...(live.length ? [["#direct", `Direct ${live.length}`]] : []),
          ["#grands", "★ Grands championnats"], ["#pronostics", "Pronostics SAM"], ["#combines", "Combinés"],
          ["#jour", "Matchs du jour"], ["#bilan", "Bilan"],
        ].map(([h, l]) => (
          <a key={h} href={h} className="shrink-0 rounded-full border border-line bg-white px-3 py-1.5 text-[12.5px] font-bold text-night">{l}</a>
        ))}
      </nav>

      {live.length > 0 && (
        <Category id="direct" title="En direct maintenant" subtitle={`${live.length} match${live.length > 1 ? "s" : ""} en cours`}
          icon={IC.live} tone="bg-brick text-white" badge={<span className="h-2 w-2 animate-pulse rounded-full bg-brick" aria-hidden />}>
          <div className="-mx-3 flex gap-2.5 overflow-x-auto px-3 pb-1 [scrollbar-width:none]">
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
          <div className="mt-2 text-right"><MoreLink href="/direct">Tout le direct</MoreLink></div>
        </Category>
      )}

      <Category id="grands" title="Grands championnats" subtitle="Ligue des champions, Premier League, LaLiga, Serie A, Bundesliga, Ligue 1…"
        icon={IC.star} tone="bg-amber-soft text-amber"
        badge={<span className="shrink-0 rounded-md bg-amber-soft px-1.5 py-0.5 text-[11px] font-bold text-amber">{(d.popular ?? []).reduce((t, g) => t + g.n_matches, 0)} matchs</span>}>
        {(d.popular ?? []).length ? (
          (d.popular ?? []).map((g, i) => (
            <SubCategory key={g.code} open={i < 2}
              title={<><span className="mr-1.5" aria-hidden>{flag(g.country)}</span>{g.name}</>}
              hint={`${g.n_matches} match${g.n_matches > 1 ? "s" : ""} à venir · ${g.n_picks} pronostic${g.n_picks > 1 ? "s" : ""}`}
              count={g.n_matches} action={<MoreLink href={`/ligues/${g.code}`}>Voir le championnat</MoreLink>}>
              <ul className="divide-y divide-mist">
                {g.matches.map((r) => (
                  <li key={r.match.id}>
                    <Link href={`/matchs/${r.match.id}`} className="grid grid-cols-[46px_minmax(0,1fr)] items-center gap-2 py-2">
                      <span className="flex flex-col text-[12px] font-semibold leading-tight text-steel">
                        {shortKick(r.match.kickoff, tz).map((x) => <span key={x}>{x}</span>)}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-[14px] font-semibold">{r.match.home.name} – {r.match.away.name}</span>
                        {r.best ? (
                          <span className="mt-0.5 inline-flex max-w-full items-center gap-1 rounded-md bg-pitch-soft px-1.5 py-0.5 text-[11.5px] font-semibold text-pitch-deep">
                            {r.best.featured && <span className="rounded bg-pitch px-1 text-[9.5px] font-bold text-white">SAM</span>}
                            <span className="truncate">{r.best.label} · {pct(r.best.probability)}</span>
                          </span>
                        ) : r.avoid ? (
                          <span className="text-[11.5px] font-semibold text-brick">À éviter selon SAM</span>
                        ) : r.status !== "ok" ? (
                          <span className="text-[11.5px] text-steel">Données insuffisantes</span>
                        ) : (
                          <span className="text-[11.5px] text-steel">Aucun pronostic assez solide</span>
                        )}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </SubCategory>
          ))
        ) : (
          <Empty title="Pas de match des grands championnats dans les prochains jours" />
        )}
      </Category>

      <Category id="pronostics" title="Pronostics SAM" subtitle="Sélection du jour, pronostics à cote, les plus fiables"
        icon={IC.chart} tone="bg-pitch-soft text-pitch-deep"
        badge={<span className="shrink-0 rounded-md bg-pitch-soft px-1.5 py-0.5 text-[11px] font-bold text-pitch-deep">{d.stats.picks}</span>}>
        <SubCategory open title="Sélection SAM du jour" count={d.selection.length}
          hint={`Probabilité d'au moins ${pct(s?.featured_min_probability ?? 0.72)}, confiance élevée, cote jouable${d.stats.selection_settled ? ` · bilan ${pct(d.stats.selection_hit_rate)} sur ${d.stats.selection_settled}` : ""}`}
          action={<MoreLink href="/historique?selection=1">Bilan de la sélection</MoreLink>}>
          {d.selection.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {d.selection.map((p) => <PickCard key={`s-${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />)}
            </div>
          ) : (
            <Empty title="Aucun pronostic n'atteint les critères de la sélection pour le moment">
              Mieux vaut ne rien proposer qu&apos;un pronostic fragile.
            </Empty>
          )}
        </SubCategory>
        <SubCategory open={d.value_picks.length > 0} title="Pronostics à cote" count={d.value_picks.length}
          hint={`Cote ${num(d.value_settings.value_min_odds)} à ${num(d.value_settings.value_max_odds)}, grands championnats, probabilité ≥ ${pct(d.value_settings.value_min_probability)}${d.stats.value_settled ? ` · bilan ${pct(d.stats.value_hit_rate)} sur ${d.stats.value_settled}` : ""}`}
          action={<MoreLink href="/historique?cote=1">Bilan des pronostics à cote</MoreLink>}>
          {d.value_picks.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {d.value_picks.map((p) => <PickCard key={`v-${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />)}
            </div>
          ) : (
            <Empty title="Aucun pronostic à cote ne remplit les critères pour le moment" />
          )}
        </SubCategory>
        <SubCategory open={(d.combo_picks?.length ?? 0) > 0} title="Pronostics combinés" count={d.combo_picks?.length ?? 0}
          hint={`Même match : résultat ou « les deux marquent » + buts, cote juste 1,60 à 3,20${d.combo_performance?.n ? ` · bilan ${pct(d.combo_performance.hit_rate)} sur ${d.combo_performance.n}` : ""}`}
          action={<MoreLink href="/historique?combine=1">Bilan des pronostics combinés</MoreLink>}>
          {d.combo_picks?.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {d.combo_picks.map((p) => <PickCard key={`c-${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />)}
            </div>
          ) : (
            <Empty title="Aucun pronostic combiné ne remplit les critères pour le moment">
              Chaque combiné est calculé sur le modèle de buts et validé hors échantillon ; rien n&apos;est proposé au hasard.
            </Empty>
          )}
        </SubCategory>
        <SubCategory title="Top 5 des plus fiables" count={d.top5.length} hint="Un pronostic par match, probabilité et confiance combinées"
          action={<MoreLink href="/pronostics?sort=probability">Tous les pronostics</MoreLink>}>
          {d.top5.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {d.top5.map((p, i) => <PickCard key={`${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} rank={i + 1} />)}
            </div>
          ) : (
            <Empty title="Aucune sélection ne passe les critères" />
          )}
        </SubCategory>
        <SubCategory title="Meilleurs pronostics du jour" count={d.best_today.length} hint="Matchs d'aujourd'hui uniquement"
          action={<MoreLink href="/pronostics?best=1">Voir les meilleurs</MoreLink>}>
          {d.best_today.length ? (
            <List>{d.best_today.slice(0, 8).map((p) => <CompactPick key={`${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />)}</List>
          ) : (
            <Empty title="Pas de pronostic retenu aujourd'hui">Consultez les prochains jours dans l&apos;onglet Pronostics.</Empty>
          )}
        </SubCategory>
      </Category>

      <Category id="combines" title="Combinés" subtitle="Cote 2 avec 2 ou 3 matchs seulement" icon={IC.combo} tone="bg-sky-soft text-sky"
        badge={<span className="shrink-0 rounded-md bg-sky-soft px-1.5 py-0.5 text-[11px] font-bold text-sky">{d.combo_of_day.length}</span>}>
        <p className="mb-2 px-1 text-[12.5px] text-steel">La même cote qu&apos;un combiné de 8 à 10 matchs, avec bien moins de risques de surprise. Matchs des 36 prochaines heures.</p>
        {d.combo_of_day.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {d.combo_of_day.map((c, i) => <ComboView key={i} c={c} tz={tz} title={i === 0 ? `Combiné principal : ${c.n_legs} matchs` : `Alternative : ${c.n_legs} matchs`} />)}
          </div>
        ) : (
          <Empty title="Pas de combinaison assez solide pour atteindre une cote de 2 en ce moment" />
        )}
        <div className="mt-2 text-right"><MoreLink href="/combines">Choisir une autre cote</MoreLink></div>
      </Category>

      <Category id="jour" open={false} title="Matchs du jour" subtitle={`${d.today_matches.length} matchs · ${d.avoid.length} à éviter`}
        icon={IC.calendar} tone="bg-mist text-night">
        {todayGroups.length ? (
          todayGroups.map((g, i) => (
            <SubCategory key={g.code} open={i < 3 && g.popular} count={g.rows.length}
              title={<><span className="mr-1.5" aria-hidden>{flag(g.country)}</span>{g.name}{g.popular ? <span className="ml-1 text-amber" aria-hidden>★</span> : null}</>}>
              <List>
                {g.rows.map((t) => (
                  <MatchRow key={t.match.id} match={t.match} tz={tz}
                    right={t.status !== "ok" ? (
                      <span className="shrink-0 rounded-md bg-mist px-2 py-0.5 text-[11px] text-steel">Données insuffisantes</span>
                    ) : t.avoid ? (
                      <span className="shrink-0 text-[11px] font-semibold text-brick">À éviter</span>
                    ) : t.n_picks ? (
                      <span className="shrink-0 rounded-md bg-pitch-soft px-2 py-0.5 text-[11px] font-semibold text-pitch-deep">{t.n_picks} prono.</span>
                    ) : (
                      <span className="shrink-0 text-[11px] text-steel">Aucun retenu</span>
                    )} />
                ))}
              </List>
            </SubCategory>
          ))
        ) : (
          <Empty title="Aucun match aujourd'hui dans les championnats suivis" />
        )}
        {d.avoid.length > 0 && (
          <SubCategory title={<span className="text-brick">Matchs à éviter</span>} count={d.avoid.length} hint="Données fragiles ou trop d'incertitude">
            <List>
              {d.avoid.map((a) => (
                <div key={a.match.id}>
                  <MatchRow match={a.match} tz={tz} />
                  <ul className="-mt-1.5 space-y-0.5 px-4 pb-3 pl-[76px] text-xs text-brick">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                </div>
              ))}
            </List>
          </SubCategory>
        )}
        <div className="mt-2 text-right"><MoreLink href="/matchs">Calendrier complet</MoreLink></div>
      </Category>

      <Category id="bilan" open={false} title="Bilan et résultats" subtitle={settled ? `${pct(d.stats.history_hit_rate)} de réussite sur ${settled} pronostics réglés` : "Aucun pronostic réglé pour le moment"}
        icon={IC.trend} tone="bg-pitch text-white">
        <div className="grid grid-cols-3 gap-2">
          {[
            ["Tous", d.stats.history_hit_rate, d.stats.history_settled],
            ["Sélection SAM", d.stats.selection_hit_rate, d.stats.selection_settled],
            ["À cote", d.stats.value_hit_rate, d.stats.value_settled],
          ].map(([l, r, n]) => (
            <div key={String(l)} className="rounded-xl border border-line bg-white px-2.5 py-2 text-center">
              <div className="text-[11px] text-steel">{String(l)}</div>
              <div className="font-display text-lg font-bold">{n ? pct(r as number | null) : "—"}</div>
              <div className="text-[10.5px] text-steel">{n ? `${n} réglés` : "en attente"}</div>
            </div>
          ))}
        </div>
        <SubCategory open title="Derniers résultats vérifiés" action={<MoreLink href="/historique">Bilan complet</MoreLink>}>
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
        </SubCategory>
      </Category>
    </>
  );
}
