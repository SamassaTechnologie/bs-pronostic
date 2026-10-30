"use client";
import { useEffect, useMemo, useState } from "react";
import type { Combo, PickCard } from "@/lib/types";
import { kickoffLabel, num, pct, signedPct } from "@/lib/format";
import { ProbBar } from "./ui";

const RISK_STYLE: Record<string, string> = {
  Modéré: "bg-pitch-soft text-pitch-deep",
  Élevé: "bg-amber-soft text-amber",
  "Très élevé": "bg-brick-soft text-brick",
  Extrême: "bg-brick text-white",
};

function ComboView({ c, tz, title }: { c: Combo; tz: string; title: string }) {
  if (!c.valid) {
    return (
      <div className="rounded-xl border border-brick/30 bg-brick-soft p-4 text-sm text-brick">
        <strong>Combinaison refusée.</strong>
        <ul className="mt-1 list-disc pl-5">{c.errors.map((e) => <li key={e}>{e}</li>)}</ul>
      </div>
    );
  }
  return (
    <article className="rounded-xl border border-line bg-white">
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div>
          <h3 className="font-display text-base font-bold">{title}</h3>
          <span className={`mt-1 inline-block rounded-md px-2 py-0.5 text-xs font-semibold ${RISK_STYLE[c.risk ?? ""] ?? ""}`}>
            Risque {c.risk?.toLowerCase()}
          </span>
        </div>
        <div className="text-right">
          <div className="font-display text-3xl font-bold">{pct(c.probability)}</div>
          <div className="text-xs text-steel">chance estimée de passer</div>
        </div>
      </div>
      <div className="px-4 pt-2">
        <ProbBar p={c.probability ?? 0} thresholds={[0.25, 0.4, 0.6]} />
      </div>
      <ul className="mt-3 divide-y divide-line border-t border-line">
        {c.legs.map((l) => (
          <li key={`${l.match_id}-${l.market_key}`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
            <div className="min-w-0">
              <div className="truncate font-semibold">{l.match_label}</div>
              <div className="truncate text-xs text-steel">{l.label}, {kickoffLabel(l.kickoff, tz)}</div>
            </div>
            <div className="shrink-0 text-right">
              <div className="font-semibold">{pct(l.probability)}</div>
              <div className="text-xs text-steel">{l.odds ? `cote ${num(l.odds)}` : "sans cote"}</div>
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-line px-4 py-3 text-sm">
        <span>Cote totale <strong>{c.total_odds ? num(c.total_odds) : "indisponible"}</strong></span>
        <span>Cote juste <strong>{num(c.fair_odds ?? null)}</strong></span>
        {c.expected_value != null && <span>Valeur <strong className={c.expected_value > 0 ? "text-pitch-deep" : "text-brick"}>{signedPct(c.expected_value)}</strong></span>}
      </div>
      {c.warnings.length > 0 && (
        <ul className="space-y-1 border-t border-line px-4 py-3 text-xs text-amber">
          {c.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
    </article>
  );
}

export function ComboBuilder({ tz }: { tz: string }) {
  const [legs, setLegs] = useState(3);
  const [mode, setMode] = useState<"prudent" | "valeur">("prudent");
  const [minConf, setMinConf] = useState(60);
  const [combos, setCombos] = useState<Combo[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [pool, setPool] = useState<PickCard[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [custom, setCustom] = useState<Combo | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetch("/api/proxy/predictions?all_markets=true&min_prob=0.6&min_conf=45&limit=250&sort=kickoff")
      .then((r) => r.json())
      .then((d) => setPool(d.items ?? []))
      .catch(() => setPool([]));
  }, []);

  async function generate() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch("/api/proxy/combos/generate", {
        method: "POST",
        body: JSON.stringify({ legs, mode, min_confidence: minConf }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Erreur");
      setCombos(d.combos);
      setMsg(d.message);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (chosen.length < 2) {
      setCustom(null);
      return;
    }
    const selections = chosen.map((k) => {
      const [match_id, market_key] = k.split("|");
      return { match_id: Number(match_id), market_key };
    });
    fetch("/api/proxy/combos/evaluate", { method: "POST", body: JSON.stringify({ selections }) })
      .then((r) => r.json())
      .then((d) => setCustom(d.valid !== undefined ? d : { valid: false, legs: [], warnings: [], errors: [d.detail ?? "Erreur"] }))
      .catch(() => setCustom(null));
  }, [chosen]);

  const grouped = useMemo(() => {
    const g = new Map<number, PickCard[]>();
    const q = query.trim().toLowerCase();
    for (const p of pool) {
      const name = `${p.match.home.name} ${p.match.away.name} ${p.match.competition.name}`.toLowerCase();
      if (q && !name.includes(q)) continue;
      g.set(p.match.id, [...(g.get(p.match.id) ?? []), p]);
    }
    return [...g.values()];
  }, [pool, query]);

  const toggle = (k: string) => setChosen((c) => (c.includes(k) ? c.filter((x) => x !== k) : c.length >= 10 ? c : [...c, k]));

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 px-1 font-display text-lg font-bold">Génération automatique</h2>
        <div className="space-y-4 rounded-xl border border-line bg-white p-4">
          <div>
            <div className="mb-1.5 text-xs text-steel">Nombre de matchs</div>
            <div className="grid grid-cols-4 gap-1.5" role="radiogroup">
              {[2, 3, 4, 5].map((n) => (
                <button key={n} type="button" role="radio" aria-checked={legs === n} onClick={() => setLegs(n)}
                  className={`rounded-lg py-2 text-sm font-bold ${legs === n ? "bg-night text-white" : "bg-mist text-night"}`}>
                  {n}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1.5 text-xs text-steel">Approche</div>
            <div className="grid grid-cols-2 gap-1.5" role="radiogroup">
              {([["prudent", "Prudente", "Probabilité maximale"], ["valeur", "Valeur", "Cote supérieure à la cote juste"]] as const).map(([v, l, h]) => (
                <button key={v} type="button" role="radio" aria-checked={mode === v} onClick={() => setMode(v)}
                  className={`rounded-lg px-3 py-2 text-left ${mode === v ? "bg-night text-white" : "bg-mist text-night"}`}>
                  <span className="block text-sm font-bold">{l}</span>
                  <span className="block text-[11px] opacity-75">{h}</span>
                </button>
              ))}
            </div>
          </div>
          <label className="block text-xs text-steel">
            Confiance minimale de chaque sélection : <strong className="text-night">{minConf}/100</strong>
            <input type="range" min={40} max={85} step={5} value={minConf} onChange={(e) => setMinConf(Number(e.target.value))} className="mt-1 w-full accent-[#0b1d3a]" />
          </label>
          <button type="button" onClick={generate} disabled={busy} className="w-full rounded-lg bg-pitch py-3 text-sm font-bold text-white disabled:opacity-60">
            {busy ? "Calcul en cours…" : `Générer un combiné de ${legs} matchs`}
          </button>
          <p className="text-xs text-steel">
            Une seule sélection par match : les matchs différents sont traités comme indépendants. Aucune probabilité n&apos;est
            multipliée pour des événements d&apos;un même match.
          </p>
        </div>
        {msg && <p className="mt-3 rounded-lg bg-amber-soft px-3 py-2 text-sm text-ink">{msg}</p>}
        {combos && combos.length > 0 && (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {combos.map((c, i) => <ComboView key={i} c={c} tz={tz} title={`Proposition ${i + 1}`} />)}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-1 px-1 font-display text-lg font-bold">Sélection personnalisée</h2>
        <p className="mb-3 px-1 text-sm text-steel">
          Choisissez vos sélections : deux marchés d&apos;un même match sont calculés ensemble sur la matrice des scores, ou refusés si
          leur corrélation n&apos;est pas modélisée.
        </p>
        {custom && <div className="mb-4"><ComboView c={custom} tz={tz} title={`Votre combiné (${chosen.length} sélections)`} /></div>}
        {chosen.length > 0 && (
          <button type="button" onClick={() => setChosen([])} className="mb-3 text-sm font-semibold text-sky">Vider la sélection</button>
        )}
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher une équipe ou un championnat"
          className="mb-3 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm" />
        {grouped.length === 0 ? (
          <p className="rounded-xl border border-dashed border-line bg-white/60 p-4 text-center text-sm text-steel">
            Aucune sélection disponible (probabilité d&apos;au moins 60 %).
          </p>
        ) : (
          <div className="space-y-2">
            {grouped.slice(0, 40).map((ms) => {
              const m = ms[0].match;
              return (
                <details key={m.id} className="rounded-xl border border-line bg-white">
                  <summary className="flex items-center justify-between gap-2 px-4 py-3">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold">{m.home.name} – {m.away.name}</span>
                      <span className="block truncate text-xs text-steel">{m.competition.name}, {kickoffLabel(m.kickoff, tz)}</span>
                    </span>
                    <span className="shrink-0 text-xs text-steel">{ms.filter((p) => chosen.includes(`${m.id}|${p.market_key}`)).length || ""}</span>
                  </summary>
                  <ul className="divide-y divide-line border-t border-line">
                    {ms.map((p) => {
                      const k = `${m.id}|${p.market_key}`;
                      return (
                        <li key={k}>
                          <label className="flex items-center gap-3 px-4 py-2.5 text-sm">
                            <input type="checkbox" checked={chosen.includes(k)} onChange={() => toggle(k)} className="h-4 w-4" />
                            <span className="flex-1">{p.label}</span>
                            <span className="font-semibold">{pct(p.probability)}</span>
                            <span className="w-14 text-right text-xs text-steel">{p.odds ? num(p.odds) : "—"}</span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                </details>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
