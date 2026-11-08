"use client";
import { useCallback, useEffect, useState } from "react";

type Prefs = { banker: boolean; selection: boolean; combo: boolean; results: boolean; competitions: string[] };
type Comp = { code: string; name: string; country: string; popular: boolean };
type Env = "loading" | "unsupported" | "ios-browser" | "denied" | "ready" | "off-server";

const DEFAULT: Prefs = { banker: true, selection: true, combo: false, results: true, competitions: [] };
const TOGGLES: [keyof Omit<Prefs, "competitions">, string, string][] = [
  ["banker", "Les bankers du jour", "2 à 3 pronostics par jour, les plus solides"],
  ["selection", "Sélection SAM", "Les nouveaux pronostics de la sélection, regroupés"],
  ["combo", "Pronostics combinés", "Deux conditions sur un même match"],
  ["results", "Résultat du banker", "Gagné ou perdu, dès la fin du match"],
];

function b64ToBytes(s: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api/proxy/alertes/${path}`, body === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || "Le serveur n'a pas répondu, réessayez.");
  return j as T;
}

export function AlertsManager({ comps }: { comps: Comp[] }) {
  const [env, setEnv] = useState<Env>("loading");
  const [key, setKey] = useState<string | null>(null);
  const [sub, setSub] = useState<PushSubscription | null>(null);
  const [on, setOn] = useState(false);
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    (async () => {
      const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
      const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
      const standalone = window.matchMedia("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true;
      if (!supported) return setEnv(ios && !standalone ? "ios-browser" : "unsupported");
      try {
        const k = await call<{ enabled: boolean; public_key: string | null }>("cle");
        if (!k.enabled || !k.public_key) return setEnv("off-server");
        setKey(k.public_key);
        const reg = await navigator.serviceWorker.register("/sw.js");
        const s = await reg.pushManager.getSubscription();
        setSub(s);
        if (s) {
          const st = await call<{ subscribed: boolean; prefs: Prefs }>("etat", { endpoint: s.endpoint });
          setOn(st.subscribed);
          setPrefs(st.prefs);
        }
        setEnv(Notification.permission === "denied" ? "denied" : "ready");
      } catch (e) {
        setMsg({ ok: false, text: (e as Error).message });
        setEnv("ready");
      }
    })();
  }, []);

  const enable = useCallback(async () => {
    if (!key) return;
    setBusy(true);
    setMsg(null);
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { setEnv(perm === "denied" ? "denied" : "ready"); throw new Error("Autorisation refusée : les alertes ne peuvent pas s'afficher."); }
      const reg = await navigator.serviceWorker.ready;
      const s = (await reg.pushManager.getSubscription()) || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) }));
      const r = await call<{ prefs: Prefs }>("abonnement", { subscription: s.toJSON(), prefs });
      setSub(s); setOn(true); setPrefs(r.prefs);
      setMsg({ ok: true, text: "Alertes activées sur cet appareil." });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally { setBusy(false); }
  }, [key, prefs]);

  const save = useCallback(async (next: Prefs) => {
    setPrefs(next);
    if (!sub || !on) return;
    try { await call("preferences", { endpoint: sub.endpoint, prefs: next }); setMsg({ ok: true, text: "Préférences enregistrées." }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }, [sub, on]);

  const disable = useCallback(async () => {
    if (!sub) return;
    setBusy(true);
    try {
      await call("desabonnement", { endpoint: sub.endpoint });
      await sub.unsubscribe().catch(() => {});
      setSub(null); setOn(false);
      setMsg({ ok: true, text: "Alertes désactivées sur cet appareil." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  }, [sub]);

  const test = useCallback(async () => {
    if (!sub) return;
    setBusy(true);
    try { await call("test", { endpoint: sub.endpoint }); setMsg({ ok: true, text: "Alerte d'essai envoyée : elle doit apparaître dans quelques secondes." }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  }, [sub]);

  if (env === "loading") return <p className="rounded-xl border border-line bg-white p-4 text-sm text-steel">Vérification de cet appareil…</p>;
  if (env === "ios-browser") return (
    <div className="rounded-xl border border-amber bg-amber-soft p-4 text-[14px] leading-relaxed text-night">
      <strong>Sur iPhone, les alertes demandent d&apos;installer l&apos;application.</strong>
      <ol className="mt-2 list-decimal space-y-1 pl-5">
        <li>Ouvrez sam-prediction.vercel.app dans <strong>Safari</strong>.</li>
        <li>Touchez <strong>Partager</strong> puis « <strong>Sur l&apos;écran d&apos;accueil</strong> ».</li>
        <li>Ouvrez SAM-Prédiction depuis l&apos;icône, puis revenez sur cette page.</li>
      </ol>
      <p className="mt-2 text-[12.5px] text-steel">iOS 16.4 ou plus récent est nécessaire.</p>
    </div>
  );
  if (env === "unsupported") return <p className="rounded-xl border border-line bg-white p-4 text-sm text-steel">Ce navigateur ne permet pas les alertes. Essayez Chrome, Edge ou Firefox, ou installez l&apos;application sur l&apos;écran d&apos;accueil.</p>;
  if (env === "off-server") return <p className="rounded-xl border border-line bg-white p-4 text-sm text-steel">Les alertes ne sont pas encore disponibles. Réessayez plus tard.</p>;

  const popular = comps.filter((c) => c.popular);
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-line bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[15px] font-bold">{on ? "Alertes activées" : "Alertes désactivées"}</div>
            <div className="text-[12.5px] text-steel">Sur cet appareil uniquement · aucune alerte entre 23 h et 7 h</div>
          </div>
          <span className={`h-3 w-3 rounded-full ${on ? "bg-pitch" : "bg-line"}`} aria-hidden />
        </div>
        {env === "denied" ? (
          <p className="mt-3 text-[13px] text-brick">Les notifications sont bloquées pour ce site. Autorisez-les dans les réglages du navigateur (ou de l&apos;iPhone : Réglages › Notifications › SAM-Prédiction), puis rechargez la page.</p>
        ) : on ? (
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button onClick={test} disabled={busy} className="rounded-lg border border-line py-2.5 text-[13.5px] font-bold text-night disabled:opacity-50">Envoyer un essai</button>
            <button onClick={disable} disabled={busy} className="rounded-lg border border-line py-2.5 text-[13.5px] font-bold text-brick disabled:opacity-50">Désactiver</button>
          </div>
        ) : (
          <button onClick={enable} disabled={busy} className="mt-3 w-full rounded-lg bg-pitch py-3 text-[15px] font-bold text-white disabled:opacity-50">
            {busy ? "Activation…" : "🔔 Activer les alertes"}
          </button>
        )}
        {msg && <p className={`mt-2 text-[12.5px] ${msg.ok ? "text-pitch-deep" : "text-brick"}`} role="status">{msg.text}</p>}
      </div>

      <div className="overflow-hidden rounded-xl border border-line bg-white">
        <div className="border-b border-line px-4 py-2.5 text-[13px] font-bold text-steel">Je veux être prévenu pour</div>
        {TOGGLES.map(([k, label, hint]) => (
          <label key={k} className="flex cursor-pointer items-center justify-between gap-3 border-b border-line px-4 py-3 last:border-0">
            <span className="min-w-0"><span className="block text-[14px] font-semibold">{label}</span><span className="block text-[12px] text-steel">{hint}</span></span>
            <input type="checkbox" checked={prefs[k]} onChange={(e) => save({ ...prefs, [k]: e.target.checked })} className="h-5 w-5 shrink-0 accent-[#0b1d3a]" />
          </label>
        ))}
      </div>

      <div className="rounded-xl border border-line bg-white p-4">
        <div className="text-[14px] font-bold">Mes championnats favoris</div>
        <p className="text-[12px] text-steel">Sélection et combinés : uniquement ces championnats. Aucun coché = tous.</p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {popular.map((c) => {
            const sel = prefs.competitions.includes(c.code);
            return (
              <button key={c.code} type="button" aria-pressed={sel}
                onClick={() => save({ ...prefs, competitions: sel ? prefs.competitions.filter((x) => x !== c.code) : [...prefs.competitions, c.code] })}
                className={`rounded-full px-3 py-1.5 text-[12.5px] font-bold ${sel ? "bg-night text-white" : "border border-line bg-white text-night"}`}>
                {c.name}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
