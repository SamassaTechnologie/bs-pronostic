import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import type { Meta, PickCard as Pick } from "@/lib/types";
import { PickCard } from "@/components/PickCard";
import { GroupedPicks } from "@/components/GroupedPicks";
import { Empty, ErrorBox } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Pronostics" };

type SP = Record<string, string | string[] | undefined>;

function one(sp: SP, k: string): string {
  const v = sp[k];
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

const field = "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-night";

export default async function Pronostics({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const tz = await userTz();
  const best = one(sp, "best") === "1";
  const list = one(sp, "vue") === "liste" || best;
  const day = one(sp, "jour");
  const isoDay = (offset: number) => new Intl.DateTimeFormat("fr-CA", { timeZone: tz }).format(new Date(Date.now() + offset * 86400000));
  const dayTabs: [string, string, string][] = [["", "Tous", ""], ["0", "Aujourd'hui", isoDay(0)], ["1", "Demain", isoDay(1)], ["2", "Après-demain", isoDay(2)]];
  const q = new URLSearchParams({ tz, limit: list ? "80" : "250", sort: list ? "score" : "kickoff" });
  const chosen = dayTabs.find((t) => t[0] === day && day !== "");
  if (chosen) {
    q.set("date_from", chosen[2]);
    q.set("date_to", chosen[2]);
  }
  const keep = (extra: Record<string, string>) => {
    const u = new URLSearchParams();
    for (const [k, v] of Object.entries(sp)) if (typeof v === "string" && v) u.set(k, v);
    for (const [k, v] of Object.entries(extra)) (v ? u.set(k, v) : u.delete(k));
    const s = u.toString();
    return s ? `/pronostics?${s}` : "/pronostics";
  };
  const map: Record<string, string> = {
    date_from: "from", date_to: "to", competition: "competition", country: "country", team: "team", market: "market",
    tier: "tier", min_odds: "min_odds", max_odds: "max_odds", sort: "sort",
  };
  for (const [api, ui] of Object.entries(map)) if (one(sp, ui)) q.set(api, one(sp, ui));
  if (one(sp, "min_prob")) q.set("min_prob", String(Number(one(sp, "min_prob")) / 100));
  if (one(sp, "min_conf")) q.set("min_conf", one(sp, "min_conf"));
  if (one(sp, "all") === "1") q.set("all_markets", "true");
  if (best) q.set("best", "true");
  const cote = one(sp, "cote") === "1";
  if (cote) q.set("value_only", "true");

  const [res, meta] = await Promise.all([
    backend<{ count: number; items: Pick[] }>(`/api/predictions?${q}`),
    backend<Meta>("/api/meta", { revalidate: 120 }),
  ]);
  const m = meta.data;
  const th = m ? [m.settings.tier_c, m.settings.tier_b, m.settings.tier_a] : undefined;
  const countries = m ? [...new Set(m.competitions.map((c) => c.country))].sort() : [];
  const families = m ? [...new Map(m.markets.map((x) => [x.family, x.family_label])).entries()] : [];
  const activeFilters = Object.keys(sp).filter((k) => one(sp, k) && !["sort", "jour", "vue", "best", "cote"].includes(k)).length;

  return (
    <>
      <div className="mb-3 flex items-end justify-between gap-3 px-1">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">{best ? "Meilleures opportunités" : "Pronostics"}</h1>
          <p className="text-sm text-steel">
            {best
              ? "Une sélection par match : probabilité, confiance et valeur combinées."
              : cote
                ? "Pronostics dont la cote du bookmaker dépasse la cote juste calculée par le moteur."
                : "Sélections retenues par le moteur. Touchez un match pour l'analyse complète."}
          </p>
        </div>
      </div>

      <nav className="mb-4 grid grid-cols-4 gap-1.5" aria-label="Raccourcis">
        {([
          ["/pronostics?best=1", "Meilleures", "opportunités", best, "M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z"],
          [cote ? "/pronostics" : "/pronostics?cote=1", "Pronostics", "à cote", cote, "M4 18l5-6 4 3 7-9M15 6h5v5"],
          ["/combines", "Combinés", "2 à 5 matchs", false, "M5 6h14M5 12h14M5 18h9"],
          ["/machine", "Machine", "SAM", false, "M12 4v3M5 10h14v9H5zM9 14h.01M15 14h.01M9 17h6"],
        ] as [string, string, string, boolean, string][]).map(([href, l1, l2, on, d]) => (
          <Link key={href + l1} href={href} aria-current={on ? "page" : undefined}
            className={`flex flex-col items-center gap-1 rounded-xl px-1 py-2.5 text-center ${on ? "bg-pitch text-white" : "border border-line bg-white text-night"}`}>
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>
            <span className="text-[11.5px] font-bold leading-tight">{l1}<br /><span className={`font-semibold ${on ? "text-white/85" : "text-steel"}`}>{l2}</span></span>
          </Link>
        ))}
      </nav>

      <div className="mb-3 space-y-2">
        <div className="scroll-x -mx-3.5 flex gap-1.5 px-3.5" role="tablist" aria-label="Jour">
          {dayTabs.map(([k, label, iso]) => (
            <Link key={k || "all"} href={keep({ jour: k })} role="tab" aria-selected={day === k} scroll={false}
              className={`shrink-0 rounded-full px-4 py-2 text-sm font-semibold ${day === k ? "bg-night text-white" : "border border-line bg-white text-night"}`}>
              {label}{iso ? <span className={`ml-1 text-[11px] font-normal ${day === k ? "text-white/75" : "text-steel"}`}>{iso.slice(8, 10)}/{iso.slice(5, 7)}</span> : null}
            </Link>
          ))}
        </div>
        {best ? (
          <div className="scroll-x -mx-3.5 flex items-center gap-1.5 px-3.5" aria-label="Classement">
            <span className="shrink-0 text-xs text-steel">Classer par</span>
            {([["", "Pertinence"], ["probability", "Probabilité"], ["confidence", "Confiance"], ["value", "Valeur"]] as const).map(([v, l]) => {
              const on = (one(sp, "sort") || "") === v || (v === "" && one(sp, "sort") === "score");
              return (
                <Link key={v || "score"} href={keep({ sort: v })} scroll={false} aria-current={on ? "true" : undefined}
                  className={`shrink-0 rounded-full px-3 py-1.5 text-[12.5px] font-bold ${on ? "bg-pitch text-white" : "border border-line bg-white text-night"}`}>
                  {l}
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-1 rounded-lg border border-line bg-white p-1" role="tablist" aria-label="Présentation">
            <Link href={keep({ vue: "" })} role="tab" aria-selected={!list} scroll={false}
              className={`rounded-md py-2 text-center text-sm font-bold ${!list ? "bg-night text-white" : "text-steel"}`}>Par championnat</Link>
            <Link href={keep({ vue: "liste" })} role="tab" aria-selected={list} scroll={false}
              className={`rounded-md py-2 text-center text-sm font-bold ${list ? "bg-night text-white" : "text-steel"}`}>Détail par pronostic</Link>
          </div>
        )}
      </div>

      <details className="mb-4 rounded-xl border border-line bg-white" open={activeFilters > 0 && !best && !cote && !one(sp, "jour") && !one(sp, "vue")}>
        <summary className="flex items-center justify-between gap-2 px-4 py-3 text-sm font-semibold">
          <span className="flex items-center gap-2">
            Filtres avancés
            {activeFilters > 0 && <span className="rounded-full bg-pitch px-2 py-0.5 text-[11px] font-bold text-white">{activeFilters}</span>}
          </span>
          <span className="flex items-center gap-3">
            {(best || cote || activeFilters > 0) && <Link href="/pronostics" className="text-[12.5px] font-bold text-brick">Tout effacer</Link>}
            <span className="text-steel" aria-hidden>▾</span>
          </span>
        </summary>
        <form method="get" className="grid grid-cols-2 gap-3 border-t border-line p-4 md:grid-cols-4">
          {day && <input type="hidden" name="jour" value={day} />}
          {one(sp, "vue") && <input type="hidden" name="vue" value={one(sp, "vue")} />}
          {best && <input type="hidden" name="best" value="1" />}
          {cote && <input type="hidden" name="cote" value="1" />}
          <label className="text-xs text-steel">
            Du
            <input type="date" name="from" defaultValue={one(sp, "from")} className={field} />
          </label>
          <label className="text-xs text-steel">
            Au
            <input type="date" name="to" defaultValue={one(sp, "to")} className={field} />
          </label>
          <label className="text-xs text-steel">
            Pays
            <select name="country" defaultValue={one(sp, "country")} className={field}>
              <option value="">Tous</option>
              {countries.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-steel">
            Championnat
            <select name="competition" defaultValue={one(sp, "competition")} className={field}>
              <option value="">Tous</option>
              {m?.competitions.map((c) => (
                <option key={c.id} value={c.code}>
                  {c.name} ({c.country})
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-2 text-xs text-steel">
            Équipe
            <input type="search" name="team" placeholder="ex. Arsenal" defaultValue={one(sp, "team")} className={field} />
          </label>
          <label className="col-span-2 text-xs text-steel">
            Marché
            <select name="market" defaultValue={one(sp, "market")} className={field}>
              <option value="">Tous</option>
              {families.map(([fam, label]) => (
                <optgroup key={fam} label={label}>
                  {m?.markets.filter((x) => x.family === fam).map((x) => (
                    <option key={x.key} value={x.key}>
                      {x.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="text-xs text-steel">
            Probabilité min. (%)
            <input type="number" name="min_prob" min={0} max={99} inputMode="numeric" defaultValue={one(sp, "min_prob")} className={field} />
          </label>
          <label className="text-xs text-steel">
            Confiance min. (/100)
            <input type="number" name="min_conf" min={0} max={100} inputMode="numeric" defaultValue={one(sp, "min_conf")} className={field} />
          </label>
          <label className="text-xs text-steel">
            Cote min.
            <input type="number" name="min_odds" step="0.01" min={1} inputMode="decimal" defaultValue={one(sp, "min_odds")} className={field} />
          </label>
          <label className="text-xs text-steel">
            Cote max.
            <input type="number" name="max_odds" step="0.01" min={1} inputMode="decimal" defaultValue={one(sp, "max_odds")} className={field} />
          </label>
          <label className="text-xs text-steel">
            Niveau
            <select name="tier" defaultValue={one(sp, "tier")} className={field}>
              <option value="">Tous</option>
              <option value="A">A (85 % et plus)</option>
              <option value="A,B">A et B (78 % et plus)</option>
              <option value="A,B,C">A, B et C (70 % et plus)</option>
            </select>
          </label>
          <label className="text-xs text-steel">
            Trier par
            <select name="sort" defaultValue={one(sp, "sort") || "score"} className={field}>
              <option value="score">Pertinence</option>
              <option value="probability">Probabilité</option>
              <option value="confidence">Confiance</option>
              <option value="value">Valeur</option>
            </select>
          </label>
          <label className="col-span-2 flex items-center gap-2 text-sm text-night">
            <input type="checkbox" name="all" value="1" defaultChecked={one(sp, "all") === "1"} className="h-4 w-4" />
            Tous les marchés (pas seulement les pronostics retenus)
          </label>
          <button type="submit" className="col-span-2 rounded-lg bg-night px-4 py-2.5 text-sm font-bold text-white md:col-span-4">
            Appliquer les filtres
          </button>
        </form>
      </details>

      {!res.ok ? (
        <ErrorBox message={res.error} />
      ) : res.data.items.length ? (
        <>
          <p className="mb-2 flex items-center justify-between gap-2 px-1 text-xs text-steel">
            <span><strong className="text-night">{res.data.count}</strong> {best ? "opportunité" : "pronostic"}{res.data.count > 1 ? "s" : ""}{chosen ? ` · ${chosen[1].toLowerCase()}` : ""}</span>
            <span>{new Set(res.data.items.map((p) => p.match.id)).size} match{new Set(res.data.items.map((p) => p.match.id)).size > 1 ? "s" : ""}</span>
          </p>
          {list ? (
            <div className="grid gap-3 md:grid-cols-2">
              {res.data.items.map((p) => (
                <PickCard key={`${p.match.id}-${p.market_key}`} pick={p} tz={tz} thresholds={th} />
              ))}
            </div>
          ) : (
            <GroupedPicks items={res.data.items} tz={tz} />
          )}
        </>
      ) : (
        <Empty title="Aucun pronostic ne correspond">
          {chosen ? "Aucun pronostic retenu pour ce jour : essayez « Tous » ou un autre jour. " : "Élargissez les filtres ou cochez « Tous les marchés ». "}
          Les matchs sans données suffisantes ne sont jamais proposés.
        </Empty>
      )}
    </>
  );
}
