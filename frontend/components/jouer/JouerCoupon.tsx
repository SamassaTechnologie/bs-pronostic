"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { kickoffLabel, num, pct } from "@/lib/format";
import { useCoupon } from "@/lib/coupon";
import { fmtJetons, JouerHeader, Legend, type Wallet } from "./JouerUi";

type Leg = { match_id: number; market_key: string; label: string; odds: number; odds_source: string; probability: number; match: string; kickoff: string; competition: string };
type Quote = { legs: Leg[]; errors: { match_id: number; market_key: string; error: string }[]; total_odds: number | null; sam_probability: number | null; combo_error: string | null; wallet: Wallet; min_stake: number; max_stake: number };

/** Avis calculé à partir des chiffres SAM (règles fixes, pas de texte d'IA). */
function advice(n: number, total: number | null, p: number | null): string | null {
  if (n < 2 || !total || p === null) return null;
  const legsFor = Math.ceil(Math.log(total) / Math.log(1.1));
  const risk = p >= 0.6 ? "risque modéré" : p >= 0.4 ? "risque élevé" : "risque très élevé";
  let s = `Avis SAM : ${n} matchs pour une cote de ${num(total)}, environ ${pct(p)} de chances de passer (${risk}).`;
  if (n <= 3 && legsFor > n + 2) s += ` C'est mieux que ${legsFor} sélections à 1,10 pour la même cote : moins de marge cumulée.`;
  if (n >= 5) s += " Au-delà de 4 matchs, chaque sélection ajoutée réduit fortement les chances : pensez à alléger le coupon.";
  return s;
}

export function JouerCoupon({ tz }: { tz: string }) {
  const router = useRouter();
  const { items, remove, clear } = useCoupon();
  const [mode, setMode] = useState<"combine" | "simple">("combine");
  const [stake, setStake] = useState(100);
  const [q, setQ] = useState<Quote | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (items.length < 2 && mode === "combine" && items.length) setMode("simple");
    if (!items.length) { setQ(null); return; }
    const sel = items.map((s) => ({ match_id: s.match_id, market_key: s.market_key }));
    fetch("/api/proxy/jeu/devis", { method: "POST", body: JSON.stringify({ selections: sel, stake: 100, mode: "combine" }) })
      .then((r) => r.json()).then(setQ).catch(() => setQ(null));
  }, [items, mode]);

  const legs = q?.legs ?? [];
  const nBets = mode === "simple" ? legs.length : 1;
  const cost = stake * nBets;
  const potential = mode === "combine" ? Math.round(stake * (q?.total_odds ?? 0)) : legs.reduce((t, l) => t + Math.round(stake * l.odds), 0);
  const canCombine = legs.length >= 2 && !q?.combo_error;
  const ok = legs.length > 0 && (mode === "simple" || canCombine) && stake >= (q?.min_stake ?? 10) && cost <= (q?.wallet.balance ?? 0) && !q?.errors.length;
  const adv = mode === "combine" ? advice(legs.length, q?.total_odds ?? null, q?.sam_probability ?? null) : null;

  async function submit() {
    setBusy(true);
    setMsg(null);
    try {
      const sel = legs.map((l) => ({ match_id: l.match_id, market_key: l.market_key }));
      const r = await fetch("/api/proxy/jeu/paris", { method: "POST", body: JSON.stringify({ selections: sel, stake, mode }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Pari refusé");
      clear();
      router.push("/jouer/mes-paris?ok=1");
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Erreur" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <JouerHeader title="Coupon" sub={q ? `Solde ${fmtJetons(q.wallet.balance)} jetons` : undefined} wallet={q?.wallet} back="/jouer" />
      {!items.length ? (
        <div className="rounded-xl border border-dashed border-line bg-white/70 p-6 text-center">
          <p className="text-sm font-semibold">Votre coupon est vide</p>
          <p className="mt-1 text-xs text-steel">Touchez une cote pour l&apos;ajouter.</p>
          <Link href="/jouer" className="mt-3 inline-block rounded-lg bg-night px-4 py-2 text-sm font-bold text-white">Voir les matchs</Link>
        </div>
      ) : (
        <div className="space-y-2.5">
          <div className="grid grid-cols-2 gap-1 rounded-xl border border-line bg-white p-1" role="tablist">
            {(["simple", "combine"] as const).map((k) => (
              <button key={k} type="button" role="tab" aria-selected={mode === k} disabled={k === "combine" && legs.length < 2} onClick={() => setMode(k)}
                className={`rounded-lg py-2 text-sm font-bold disabled:opacity-40 ${mode === k ? "bg-night text-white" : "text-steel"}`}>
                {k === "simple" ? `Simples${legs.length > 1 ? ` (${legs.length})` : ""}` : "Combiné"}
              </button>
            ))}
          </div>

          {legs.map((l) => (
            <div key={`${l.match_id}-${l.market_key}`} className="flex justify-between gap-3 rounded-xl border border-line bg-white p-3">
              <div className="min-w-0">
                <div className="truncate text-xs text-steel">{l.competition} · {kickoffLabel(l.kickoff, tz)}</div>
                <div className="truncate text-[15px] font-semibold">{l.match}</div>
                <div className="text-sm">{l.label}</div>
                <div className="text-xs font-semibold text-pitch-deep">Probabilité SAM {pct(l.probability)}</div>
              </div>
              <div className="flex shrink-0 flex-col items-end justify-between">
                <button type="button" onClick={() => remove(l.match_id, l.market_key)} aria-label={`Retirer ${l.label}`} className="-mr-1 -mt-1 flex h-9 w-9 items-center justify-center text-steel">
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
                </button>
                <strong className="text-lg tabular-nums">{num(l.odds)}{l.odds_source === "sam" && <sup className="ml-0.5 text-[9px] text-steel">S</sup>}</strong>
              </div>
            </div>
          ))}
          {q?.errors.map((e) => (
            <div key={`${e.match_id}-${e.market_key}`} className="flex items-center justify-between gap-2 rounded-xl bg-brick-soft px-3 py-2 text-sm text-brick">
              <span>{e.error}</span>
              <button type="button" onClick={() => remove(e.match_id, e.market_key)} className="shrink-0 font-semibold underline">Retirer</button>
            </div>
          ))}

          <section className="space-y-2.5 rounded-xl border border-line bg-white p-3">
            {mode === "combine" && q?.total_odds && (
              <>
                <div className="flex justify-between text-sm"><span className="text-steel">Cote totale</span><strong>{num(q.total_odds)}</strong></div>
                {q.sam_probability !== null && (
                  <>
                    <div className="flex justify-between text-sm"><span className="text-steel">Chance estimée par SAM</span><strong className="text-pitch-deep">{pct(q.sam_probability)}</strong></div>
                    <div className="h-2 overflow-hidden rounded bg-mist"><div className="h-2 bg-pitch" style={{ width: `${Math.round((q.sam_probability ?? 0) * 100)}%` }} /></div>
                  </>
                )}
              </>
            )}
            <label className="block text-[13px] text-steel">
              Mise en jetons{mode === "simple" && legs.length > 1 ? " (par pari)" : ""}
              <input type="number" inputMode="numeric" min={q?.min_stake ?? 10} max={q?.max_stake ?? 5000} value={stake}
                onChange={(e) => setStake(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
                className="mt-1 w-full rounded-lg border border-line px-3 py-2.5 text-[17px] font-bold text-night" />
            </label>
            <div className="grid grid-cols-4 gap-1.5">
              {[50, 100, 250, 500].map((v) => (
                <button key={v} type="button" onClick={() => setStake(v)} className={`rounded-lg border py-2 text-[13px] font-semibold ${stake === v ? "border-night bg-night text-white" : "border-line bg-mist"}`}>{v}</button>
              ))}
            </div>
            <div className="flex justify-between text-[15px]"><span>Gain potentiel</span><strong>{fmtJetons(potential)} jetons</strong></div>
            {cost > (q?.wallet.balance ?? 0) && <p className="text-xs font-semibold text-brick">Solde insuffisant : {fmtJetons(q?.wallet.balance ?? 0)} jetons disponibles.</p>}
            {q?.combo_error && mode === "combine" && <p className="text-xs font-semibold text-brick">{q.combo_error}</p>}
          </section>

          {adv && <p className="rounded-xl bg-amber-soft px-3 py-2.5 text-xs leading-relaxed text-ink">{adv}</p>}
          {msg && <p className={`rounded-xl px-3 py-2 text-sm ${msg.ok ? "bg-pitch-soft" : "bg-brick-soft text-brick"}`}>{msg.text}</p>}

          <button type="button" onClick={submit} disabled={!ok || busy} className="w-full rounded-xl bg-pitch py-3.5 text-base font-bold text-white disabled:opacity-50">
            {busy ? "Validation…" : `Valider ${nBets > 1 ? `${nBets} paris` : "le pari"} (${fmtJetons(cost)} jetons)`}
          </button>
          <button type="button" onClick={clear} className="w-full py-2 text-sm font-semibold text-steel">Vider le coupon</button>
        </div>
      )}
      <Legend />
    </>
  );
}
