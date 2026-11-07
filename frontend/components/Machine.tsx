"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { kickoffLabel, num, pct } from "@/lib/format";
import { flag } from "@/lib/flags";
import { replaceCoupon } from "@/lib/coupon";
import type { MatchSummary } from "@/lib/types";

type Comp = { code: string; name: string; country: string; popular: boolean };
type Opts = { events: { key: string; label: string }[]; competitions: Comp[] };
type Facts = {
  last10?: { home: number | null; away: number | null; n_home: number; n_away: number };
  venue?: { home: number | null; away: number | null; n_home: number; n_away: number };
  h2h?: { rate: number | null; n: number };
  goals5?: { home_scored: number | null; away_scored: number | null; home_conceded: number | null; away_conceded: number | null };
};
type Sel = { match: MatchSummary; market_key: string; label: string; event: string; probability: number; confidence: number; odds: number; bookmaker_odds: boolean; bookmaker: string | null; is_pick: boolean; facts: Facts };
type Res = { selections: Sel[]; count: number; candidates: number; matches_scanned: number; total_odds: number | null; probability: number | null; all_bookmaker_odds: boolean; rejected: Record<string, number>; target_reached: boolean | null };

type F = {
  events: string[]; days: number; competitions: string[]; popular_only: boolean; n_matches: number;
  min_odds: number; max_odds: number; target_odds: number | null; min_probability: number; min_confidence: number;
  last10_pct: number | null; venue_pct: number | null; h2h_pct: number | null; min_avg_scored: number | null; max_avg_conceded: number | null;
  sort: "probability" | "odds" | "confidence" | "kickoff";
};
const DEFAULT: F = {
  events: ["O1.5", "1X", "X2"], days: 1, competitions: [], popular_only: true, n_matches: 5, min_odds: 1.2, max_odds: 2.5,
  target_odds: null, min_probability: 0.65, min_confidence: 60, last10_pct: null, venue_pct: null, h2h_pct: null,
  min_avg_scored: null, max_avg_conceded: null, sort: "probability",
};
const PRESETS_KEY = "sam-machine-filtres-v1";
const PCTS = [null, 0.5, 0.6, 0.7, 0.8, 0.9];

function loadPresets(): Record<string, F> {
  try { return JSON.parse(localStorage.getItem(PRESETS_KEY) || "{}"); } catch { return {}; }
}
function savePresets(p: Record<string, F>) {
  try { localStorage.setItem(PRESETS_KEY, JSON.stringify(p)); } catch {}
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-[12.5px] font-bold ${on ? "bg-night text-white" : "border border-line bg-white text-night"}`}>{children}</button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="mb-1 block text-[12px] font-semibold text-steel">{label}</span>{children}</label>;
}

const inputCls = "w-full rounded-lg border border-line bg-white px-3 py-2 text-[15px] tabular-nums";

function PctSelect({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} className={inputCls}>
      {PCTS.map((p) => <option key={String(p)} value={p ?? ""}>{p === null ? "Aucun" : `≥ ${Math.round(p * 100)} %`}</option>)}
    </select>
  );
}

function FactLine({ f }: { f: Facts }) {
  const parts: string[] = [];
  if (f.last10) parts.push(`10 derniers : ${pct(f.last10.home)} / ${pct(f.last10.away)}`);
  if (f.venue) parts.push(`dom./ext. : ${pct(f.venue.home)} / ${pct(f.venue.away)}`);
  if (f.h2h) parts.push(`face-à-face : ${pct(f.h2h.rate)} (${f.h2h.n})`);
  if (f.goals5) parts.push(`buts marqués (5 m.) : ${num(f.goals5.home_scored, 1)} / ${num(f.goals5.away_scored, 1)}`);
  return parts.length ? <div className="mt-1 text-[11.5px] leading-snug text-steel">{parts.join(" · ")}</div> : null;
}

export function Machine({ tz }: { tz: string }) {
  const router = useRouter();
  const [opts, setOpts] = useState<Opts | null>(null);
  const [f, setF] = useState<F>(DEFAULT);
  const [res, setRes] = useState<Res | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [presets, setPresets] = useState<Record<string, F>>({});
  const [showComps, setShowComps] = useState(false);
  const set = <K extends keyof F>(k: K, v: F[K]) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    setPresets(loadPresets());
    fetch("/api/proxy/machine/options").then((r) => r.json()).then(setOpts).catch(() => setErr("Options indisponibles, rechargez la page."));
  }, []);

  async function run() {
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/proxy/machine", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
      const j = await r.json();
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Critères invalides : vérifiez les cotes et les pourcentages.");
      setRes(j);
      setTimeout(() => document.getElementById("resultat")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  function savePreset() {
    const name = window.prompt("Nom de ce filtre (ex. « Buts du week-end »)")?.trim();
    if (!name) return;
    const next = { ...presets, [name.slice(0, 40)]: f };
    setPresets(next); savePresets(next);
  }
  function deletePreset(name: string) {
    const next = { ...presets }; delete next[name];
    setPresets(next); savePresets(next);
  }

  function play() {
    if (!res?.selections.length) return;
    replaceCoupon(res.selections.map((s) => ({ match_id: s.match.id, market_key: s.market_key, label: s.label, match: `${s.match.home.name} – ${s.match.away.name}`, odds: s.odds })));
    router.push("/jouer/coupon");
  }

  const comps = opts?.competitions ?? [];
  const shown = showComps ? comps : comps.filter((c) => c.popular);

  return (
    <div className="space-y-3">
      {Object.keys(presets).length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px] font-semibold text-steel">Mes filtres :</span>
          {Object.keys(presets).map((n) => (
            <span key={n} className="inline-flex items-center overflow-hidden rounded-full border border-line bg-white text-[12.5px] font-bold">
              <button type="button" onClick={() => setF({ ...DEFAULT, ...presets[n] })} className="px-3 py-1.5">{n}</button>
              <button type="button" onClick={() => deletePreset(n)} aria-label={`Supprimer le filtre ${n}`} className="border-l border-line px-2 py-1.5 text-steel">×</button>
            </span>
          ))}
        </div>
      )}

      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="text-[14px] font-bold">1. Événements</h2>
        <p className="mb-2 text-[12px] text-steel">Un seul pronostic par match : le plus probable parmi ceux choisis.</p>
        <div className="flex flex-wrap gap-1.5">
          {(opts?.events ?? []).map((e) => (
            <Chip key={e.key} on={f.events.includes(e.key)} onClick={() => set("events", f.events.includes(e.key) ? f.events.filter((x) => x !== e.key) : [...f.events, e.key])}>{e.label}</Chip>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="mb-2 text-[14px] font-bold">2. Matchs</h2>
        <div className="grid grid-cols-3 gap-1 rounded-lg bg-mist p-1" role="group" aria-label="Période">
          {[[1, "Aujourd'hui"], [2, "48 h"], [3, "3 jours"]].map(([d, l]) => (
            <button key={d} type="button" onClick={() => set("days", d as number)} className={`rounded-md py-1.5 text-[13px] font-bold ${f.days === d ? "bg-white text-night shadow-sm" : "text-steel"}`}>{l}</button>
          ))}
        </div>
        <label className="mt-3 flex items-center justify-between gap-3">
          <span className="text-[13.5px] font-semibold">Grands championnats seulement</span>
          <input type="checkbox" checked={f.popular_only} onChange={(e) => set("popular_only", e.target.checked)} className="h-5 w-5 accent-[#0b1d3a]" />
        </label>
        {!f.popular_only && (
          <div className="mt-2">
            <p className="mb-1.5 text-[12px] text-steel">Championnats précis (aucun = tous) :</p>
            <div className="flex flex-wrap gap-1.5">
              {shown.map((c) => (
                <Chip key={c.code} on={f.competitions.includes(c.code)} onClick={() => set("competitions", f.competitions.includes(c.code) ? f.competitions.filter((x) => x !== c.code) : [...f.competitions, c.code])}>
                  {flag(c.country)} {c.name}
                </Chip>
              ))}
            </div>
            {!showComps && <button type="button" onClick={() => setShowComps(true)} className="mt-2 text-[12.5px] font-bold text-sky">Voir tous les championnats</button>}
          </div>
        )}
        <div className="mt-3 grid grid-cols-2 items-end gap-2.5">
          <Field label="Nombre de matchs (1 à 20)">
            <input type="number" min={1} max={20} value={f.n_matches} onChange={(e) => set("n_matches", Math.max(1, Math.min(20, Number(e.target.value) || 1)))} className={inputCls} inputMode="numeric" />
          </Field>
          <Field label="Trier par">
            <select value={f.sort} onChange={(e) => set("sort", e.target.value as F["sort"])} className={inputCls}>
              <option value="probability">Probabilité</option><option value="odds">Cote</option><option value="confidence">Confiance</option><option value="kickoff">Heure</option>
            </select>
          </Field>
        </div>
      </section>

      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="mb-2 text-[14px] font-bold">3. Cotes et fiabilité</h2>
        <div className="grid grid-cols-2 items-end gap-2.5">
          <Field label="Cote min. par match"><input type="number" step={0.05} min={1.01} value={f.min_odds} onChange={(e) => set("min_odds", Number(e.target.value))} className={inputCls} inputMode="decimal" /></Field>
          <Field label="Cote max. par match"><input type="number" step={0.05} min={1.01} value={f.max_odds} onChange={(e) => set("max_odds", Number(e.target.value))} className={inputCls} inputMode="decimal" /></Field>
          <Field label="Cote totale visée (option)"><input type="number" step={0.5} min={1.1} placeholder="ex. 3" value={f.target_odds ?? ""} onChange={(e) => set("target_odds", e.target.value ? Number(e.target.value) : null)} className={inputCls} inputMode="decimal" /></Field>
          <Field label={`Probabilité min. : ${Math.round(f.min_probability * 100)} %`}>
            <input type="range" min={0.5} max={0.9} step={0.05} value={f.min_probability} onChange={(e) => set("min_probability", Number(e.target.value))} className="mt-2 w-full accent-[#0b1d3a]" />
          </Field>
          <Field label={`Confiance min. : ${f.min_confidence}/100`}>
            <input type="range" min={0} max={90} step={5} value={f.min_confidence} onChange={(e) => set("min_confidence", Number(e.target.value))} className="mt-2 w-full accent-[#0b1d3a]" />
          </Field>
        </div>
      </section>

      <details className="group rounded-xl border border-line bg-white">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 [&::-webkit-details-marker]:hidden">
          <span><span className="block text-[14px] font-bold">4. Filtre statistique (option)</span><span className="block text-[12px] text-steel">Sur les vrais matchs joués par les deux équipes</span></span>
          <svg viewBox="0 0 24 24" className="h-4 w-4 text-steel transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 9l6 6 6-6" /></svg>
        </summary>
        <div className="grid grid-cols-2 items-end gap-2.5 border-t border-line px-4 pb-4 pt-3">
          <Field label="Événement, 10 derniers matchs (chaque équipe)"><PctSelect value={f.last10_pct} onChange={(v) => set("last10_pct", v)} /></Field>
          <Field label="Domicile à domicile, extérieur à l'extérieur"><PctSelect value={f.venue_pct} onChange={(v) => set("venue_pct", v)} /></Field>
          <Field label="Confrontations directes (5 dernières)"><PctSelect value={f.h2h_pct} onChange={(v) => set("h2h_pct", v)} /></Field>
          <Field label="Buts marqués (moy. 5 m.) au moins">
            <input type="number" step={0.1} min={0} placeholder="—" value={f.min_avg_scored ?? ""} onChange={(e) => set("min_avg_scored", e.target.value ? Number(e.target.value) : null)} className={inputCls} inputMode="decimal" />
          </Field>
          <Field label="Buts encaissés (moy. 5 m.) au plus">
            <input type="number" step={0.1} min={0} placeholder="—" value={f.max_avg_conceded ?? ""} onChange={(e) => set("max_avg_conceded", e.target.value ? Number(e.target.value) : null)} className={inputCls} inputMode="decimal" />
          </Field>
          <p className="col-span-2 text-[11.5px] text-steel">Une équipe avec moins de 5 matchs connus est écartée (données insuffisantes), jamais estimée.</p>
        </div>
      </details>

      <div className="grid grid-cols-[1fr_auto_auto] gap-2">
        <button type="button" onClick={run} disabled={busy || !f.events.length} className="rounded-xl bg-pitch py-3.5 text-[15px] font-bold text-white disabled:opacity-50">
          {busy ? "Recherche…" : "⚙️ Générer mes pronostics"}
        </button>
        <button type="button" onClick={savePreset} className="rounded-xl border border-line bg-white px-3 text-[13px] font-bold" title="Enregistrer ce filtre sur cet appareil">Enregistrer</button>
        <button type="button" onClick={() => { setF(DEFAULT); setRes(null); }} className="rounded-xl border border-line bg-white px-3 text-[13px] font-bold text-steel">Effacer</button>
      </div>
      {err && <p className="text-[13px] text-brick" role="alert">{err}</p>}

      {res && (
        <section id="resultat" className="scroll-mt-16">
          {res.count ? (
            <>
              <div className="rounded-xl bg-night p-4 text-white">
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <div className="text-[12px] text-white/65">{res.count} match{res.count > 1 ? "s" : ""} · {res.candidates} correspondent sur {res.matches_scanned} analysés</div>
                    <div className="font-display text-3xl font-bold">Cote {num(res.total_odds)}</div>
                    <div className="text-[11.5px] text-white/65">{res.all_bookmaker_odds ? "Cotes bookmaker relevées" : "Cotes bookmaker si relevées, sinon cote juste SAM"}</div>
                  </div>
                  {res.count > 1 && (
                    <div className="text-right">
                      <div className="text-[11.5px] text-white/65">Chances de tout passer</div>
                      <div className="font-display text-2xl font-bold">{pct(res.probability)}</div>
                    </div>
                  )}
                </div>
                {res.count > 1 && <p className="mt-2 text-[11px] text-white/55">Chances calculées en supposant les matchs indépendants : une estimation, pas une garantie.</p>}
              </div>
              <ul className="mt-2 divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                {res.selections.map((s) => (
                  <li key={s.match.id}>
                    <Link href={`/matchs/${s.match.id}`} className="flex items-start gap-3 px-3.5 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12px] text-steel">{flag(s.match.competition.country)} {s.match.competition.name} · {kickoffLabel(s.match.kickoff, tz)}</div>
                        <div className="truncate text-[14px] font-semibold">{s.match.home.name} – {s.match.away.name}</div>
                        <div className="text-[13.5px] font-bold text-pitch-deep">{s.label}{s.is_pick && <span className="ml-1.5 rounded bg-pitch-soft px-1 text-[10.5px]">Pronostic SAM</span>}</div>
                        <FactLine f={s.facts} />
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="font-display text-[18px] font-bold tabular-nums">{pct(s.probability)}</div>
                        <div className="text-[12px] font-semibold tabular-nums">{s.bookmaker_odds ? `cote ${num(s.odds)}` : `cote juste ${num(s.odds)}`}</div>
                        <div className="text-[11px] text-steel">confiance {s.confidence}</div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
              <button type="button" onClick={play} className="mt-2 w-full rounded-xl bg-night py-3 text-[14.5px] font-bold text-white">Jouer ce coupon en jetons</button>
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-line bg-white/70 p-4 text-center text-[13.5px] text-steel">
              <strong className="block text-night">Aucun match ne remplit tous ces critères.</strong>
              {res.target_reached === false ? "La cote totale visée n'est pas atteignable avec ce nombre de matchs. " : ""}
              Écartés : {res.rejected.probabilite} pour la probabilité ou la confiance, {res.rejected.cote} pour la cote, {res.rejected.statistiques} pour les statistiques, {res.rejected.donnees} faute de données. Assouplissez un critère.
            </div>
          )}
        </section>
      )}
    </div>
  );
}
