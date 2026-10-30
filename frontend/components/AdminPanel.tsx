"use client";
import { useCallback, useEffect, useState } from "react";
import type { Provider } from "@/lib/types";

type Status = {
  providers: Provider[];
  counts: Record<string, number>;
  pipeline: { running: boolean; step: string | null; started_at: string | null; last_result: { status: string; message?: string; finished_at?: string } | null };
  scheduler: { enabled: boolean; interval_minutes: number };
  calibration: { created_at: string | null; n_matches?: number; note?: string };
  database: string;
};
type Comp = { id: number; code: string; name: string; country: string; enabled: boolean; primary_source: string; api_football_id: number | null; fdorg_code: string | null; fdcuk_code: string | null; matches: number };
type Run = { id: number; provider: string; kind: string; status: string; items: number; message: string | null; started_at: string };

const SOURCE_LABEL: Record<string, string> = { football_data_co_uk: "football-data.co.uk", api_football: "API-Football", football_data_org: "football-data.org" };
const NUMERIC_SETTINGS: [string, string, number][] = [
  ["tier_a", "Seuil niveau A", 0.01], ["tier_b", "Seuil niveau B", 0.01], ["tier_c", "Seuil niveau C", 0.01],
  ["min_probability", "Probabilité minimale d'un pronostic", 0.01], ["min_confidence", "Confiance minimale (/100)", 1],
  ["min_fair_odds", "Cote juste minimale", 0.01], ["max_picks_per_match", "Pronostics max. par match", 1],
  ["max_daily_picks", "Pronostics max. par jour", 1], ["days_ahead", "Jours analysés à l'avance", 1],
  ["avoid_confidence_below", "« À éviter » si confiance max. sous", 1], ["market_divergence_alert", "Alerte écart modèle/marché", 0.01],
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/admin/${path}`, { ...init, headers: { "Content-Type": "application/json" } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Erreur ${r.status}`);
  return d as T;
}

const fmt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("fr-FR") : "jamais");

export function AdminPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [settings, setSettings] = useState<Record<string, number | string[]> | null>(null);
  const [comps, setComps] = useState<Comp[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [tests, setTests] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, st, c, r] = await Promise.all([
        api<Status>("status"), api<Record<string, number | string[]>>("settings"), api<Comp[]>("competitions"), api<Run[]>("sync-runs?limit=25"),
      ]);
      setStatus(s); setSettings(st); setComps(c); setRuns(r);
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Erreur" });
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!status?.pipeline.running) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [status?.pipeline.running, load]);

  async function act(path: string, body: unknown, success: string) {
    setNotice(null);
    try {
      const r = await api<{ message?: string; status?: string }>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
      setNotice({ ok: r.status !== "busy", text: r.message || success });
      await load();
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Erreur" });
    }
  }

  async function saveSettings(form: FormData) {
    const changes: Record<string, number> = {};
    for (const [k] of NUMERIC_SETTINGS) changes[k] = Number(form.get(k));
    try {
      const s = await api<Record<string, number | string[]>>("settings", { method: "PUT", body: JSON.stringify(changes) });
      setSettings(s);
      setNotice({ ok: true, text: "Réglages enregistrés. Ils s'appliquent dès la prochaine analyse." });
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Erreur" });
    }
  }

  async function updateComp(c: Comp, change: Partial<Comp>) {
    try {
      const u = await api<Comp>(`competitions/${c.id}`, { method: "PUT", body: JSON.stringify(change) });
      setComps((cs) => cs.map((x) => (x.id === c.id ? { ...x, ...u, matches: x.matches } : x)));
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Erreur" });
    }
  }

  async function test(name: string) {
    setTests((t) => ({ ...t, [name]: { ok: true, message: "Test en cours…" } }));
    try {
      const r = await api<{ ok: boolean; message: string }>(`providers/${name}/test`, { method: "POST" });
      setTests((t) => ({ ...t, [name]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [name]: { ok: false, message: e instanceof Error ? e.message : "Erreur" } }));
    }
  }

  async function toggleProvider(p: Provider) {
    await api(`providers/${p.name}`, { method: "PUT", body: JSON.stringify({ enabled: !p.enabled }) }).catch(() => {});
    load();
  }

  if (!status) {
    return <p className="p-4 text-sm text-steel">{notice?.text ?? "Chargement de l'administration…"}</p>;
  }
  const visible = showAll ? comps : comps.filter((c) => c.enabled);
  const box = "rounded-xl border border-line bg-white";

  return (
    <div className="space-y-7">
      <div className="flex items-center justify-between px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Administration</h1>
        <form method="post" action="/api/admin/logout"><button className="text-sm font-semibold text-sky">Se déconnecter</button></form>
      </div>
      {notice && (
        <p className={`rounded-lg px-3 py-2 text-sm ${notice.ok ? "bg-pitch-soft text-pitch-deep" : "bg-brick-soft text-brick"}`} role="status">{notice.text}</p>
      )}

      <section>
        <h2 className="mb-2 px-1 font-display text-lg font-bold">Synchronisation</h2>
        <div className={`${box} space-y-3 p-4 text-sm`}>
          <p>
            {status.pipeline.running ? (
              <strong>En cours : {status.pipeline.step}…</strong>
            ) : (
              <>Dernier passage : {status.pipeline.last_result ? `${status.pipeline.last_result.status === "ok" ? "réussi" : "en erreur"}, ${fmt(status.pipeline.last_result.finished_at)}` : "aucun depuis le démarrage du serveur"}.</>
            )}{" "}
            Automatique {status.scheduler.enabled ? `toutes les ${status.scheduler.interval_minutes} min` : "désactivée (déclenchement externe)"}.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => act("sync", {}, "Synchronisation lancée")} disabled={status.pipeline.running} className="rounded-lg bg-night px-3 py-2.5 font-bold text-white disabled:opacity-50">Synchroniser et analyser</button>
            <button onClick={() => act("analyze", {}, "Analyse terminée")} className="rounded-lg bg-mist px-3 py-2.5 font-bold">Relancer l&apos;analyse</button>
            <button onClick={() => act("settle", {}, "Résultats réglés")} className="rounded-lg bg-mist px-3 py-2.5 font-bold">Régler les résultats</button>
            <button onClick={() => act("calibrate", {}, "Recalibrage lancé")} className="rounded-lg bg-mist px-3 py-2.5 font-bold">Recalibrer le modèle</button>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-steel sm:grid-cols-4">
            {Object.entries(status.counts).map(([k, v]) => (
              <span key={k}>{{ competitions_enabled: "Championnats actifs", teams: "Équipes", matches: "Matchs", matches_finished: "Matchs terminés", matches_scheduled: "Matchs à venir", analyses: "Analyses", predictions: "Pronostics publiés" }[k] ?? k} : <strong className="text-night">{v}</strong></span>
            ))}
          </div>
          <p className="text-xs text-steel">
            Calibration : {status.calibration.created_at ? `recalculée le ${fmt(status.calibration.created_at)} (${status.calibration.n_matches} matchs)` : status.calibration.note}. Base : {status.database}.
          </p>
        </div>
      </section>

      <section>
        <h2 className="mb-2 px-1 font-display text-lg font-bold">Fournisseurs de données</h2>
        <div className="space-y-2.5">
          {status.providers.map((p) => (
            <div key={p.name} className={`${box} p-4 text-sm`}>
              <div className="flex items-center justify-between gap-2">
                <a href={p.website} target="_blank" rel="noreferrer" className="font-semibold underline-offset-2 hover:underline">{p.label}</a>
                <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${p.configured ? "bg-pitch-soft text-pitch-deep" : "bg-amber-soft text-amber"}`}>
                  {p.configured ? (p.requires_key ? "Clé configurée" : "Sans clé") : "Clé manquante"}
                </span>
              </div>
              <p className="mt-1 text-xs text-steel">{p.setup}</p>
              {p.last_run && (
                <p className={`mt-1 text-xs ${p.last_run.status === "error" ? "text-brick" : "text-steel"}`}>
                  Dernier passage ({p.last_run.kind}, {fmt(p.last_run.started_at)}) : {p.last_run.message}
                </p>
              )}
              {p.requires_key && <p className="mt-1 text-xs text-steel">Requêtes aujourd&apos;hui : {p.requests_today}</p>}
              {tests[p.name] && <p className={`mt-1 text-xs font-semibold ${tests[p.name].ok ? "text-pitch-deep" : "text-brick"}`}>{tests[p.name].message}</p>}
              <div className="mt-2 flex gap-2">
                <button onClick={() => test(p.name)} className="rounded-lg bg-mist px-3 py-1.5 text-xs font-bold">Tester la connexion</button>
                <button onClick={() => toggleProvider(p)} className="rounded-lg bg-mist px-3 py-1.5 text-xs font-bold">{p.enabled ? "Désactiver" : "Activer"}</button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {settings && (
        <section>
          <h2 className="mb-2 px-1 font-display text-lg font-bold">Seuils et sélection</h2>
          <form action={saveSettings} className={`${box} grid grid-cols-2 gap-3 p-4`}>
            {NUMERIC_SETTINGS.map(([k, label, step]) => (
              <label key={k} className="text-xs text-steel">
                {label}
                <input name={k} type="number" step={step} defaultValue={String(settings[k])} className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm text-night" />
              </label>
            ))}
            <button className="col-span-2 rounded-lg bg-night py-2.5 text-sm font-bold text-white">Enregistrer les réglages</button>
          </form>
        </section>
      )}

      <section>
        <div className="mb-2 flex items-baseline justify-between px-1">
          <h2 className="font-display text-lg font-bold">Championnats</h2>
          <button onClick={() => setShowAll((s) => !s)} className="text-sm font-semibold text-sky">{showAll ? "Afficher les actifs" : "Afficher tous"}</button>
        </div>
        <div className={`${box} divide-y divide-line`}>
          {visible.map((c) => (
            <div key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <input type="checkbox" checked={c.enabled} onChange={() => updateComp(c, { enabled: !c.enabled })} className="h-4 w-4" aria-label={`Activer ${c.name}`} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold">{c.name} <span className="font-normal text-steel">({c.country})</span></div>
                <div className="text-xs text-steel">{SOURCE_LABEL[c.primary_source]}, {c.matches} matchs en base{c.api_football_id ? `, API-Football n° ${c.api_football_id}` : ""}</div>
              </div>
              <select value={c.primary_source} onChange={(e) => updateComp(c, { primary_source: e.target.value })} className="max-w-36 rounded-lg border border-line px-2 py-1 text-xs" aria-label="Source principale">
                {Object.entries(SOURCE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          ))}
        </div>
        <p className="mt-2 px-1 text-xs text-steel">
          Une compétition africaine (ex. championnat du Mali) s&apos;ajoute avec son identifiant API-Football via l&apos;API
          <code className="mx-1">POST /api/admin/competitions</code> (voir le guide d&apos;installation).
        </p>
      </section>

      <section>
        <h2 className="mb-2 px-1 font-display text-lg font-bold">Journal</h2>
        <div className={`${box} divide-y divide-line text-xs`}>
          {runs.length ? runs.map((r) => (
            <div key={r.id} className="px-4 py-2">
              <div className="flex justify-between gap-2">
                <span className="font-semibold">{r.provider}, {r.kind}</span>
                <span className={r.status === "error" ? "font-semibold text-brick" : r.status === "ok" ? "text-pitch-deep" : "text-steel"}>{r.status}</span>
              </div>
              <div className="text-steel">{fmt(r.started_at)} : {r.message}</div>
            </div>
          )) : <p className="px-4 py-3 text-steel">Aucune synchronisation pour l&apos;instant.</p>}
        </div>
      </section>
    </div>
  );
}
