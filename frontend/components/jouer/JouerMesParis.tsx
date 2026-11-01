"use client";
import { useCallback, useEffect, useState } from "react";
import { kickoffLabel, num, pct } from "@/lib/format";
import { fmtJetons, JouerHeader, Legend, type Wallet } from "./JouerUi";

type LegLive = { state: string; home?: number | null; away?: number | null; ht_home?: number | null; ht_away?: number | null; minute?: string | null; minute_estimated?: boolean; label?: string; covered?: boolean; winning_now?: boolean | null };
type BetLeg = { match_id: number; match: string; competition: string; kickoff: string; status: string; score: string | null; label: string; odds: number; odds_source: string; probability: number | null; result: string; live?: LegLive };
type Bet = { id: number; kind: string; stake: number; total_odds: number; potential: number; status: string; payout: number; sam_probability: number | null; created_at: string; legs: BetLeg[]; progress: { won: number; lost: number; pending: number; total: number } };
type Rank = { position: number; name: string; profit: number; bets: number; me: boolean };
type Data = { wallet: Wallet; bets: Bet[]; ranking: { month: string; top: Rank[]; me: Rank | null; players: number } };

const STATUS: Record<string, [string, string]> = {
  pending: ["En cours", "bg-amber-soft text-amber"], won: ["Gagné", "bg-pitch-soft text-pitch-deep"],
  lost: ["Perdu", "bg-brick-soft text-brick"], void: ["Remboursé", "bg-mist text-steel"],
};
function ResultIcon({ r }: { r: string }) {
  if (r === "won") return <span className="flex h-6 w-6 items-center justify-center rounded-full bg-pitch text-white" aria-label="Gagnée"><svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden><path d="M5 12l5 5 9-10" /></svg></span>;
  if (r === "lost") return <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brick text-white" aria-label="Perdue"><svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg></span>;
  if (r === "void") return <span className="flex h-6 w-6 items-center justify-center rounded-full bg-line text-[10px] font-bold text-steel" aria-label="Remboursée">R</span>;
  return <span className="block h-6 w-6 shrink-0 rounded-full border-2 border-line" aria-label="En attente" />;
}

/** Ligne d'état du match d'une sélection, comme sur un coupon de bookmaker. */
function LegState({ l, tz }: { l: BetLeg; tz: string }) {
  const lv = l.live;
  if (l.result !== "pending" || lv?.state === "finished") {
    const sc = lv?.state === "finished" ? `${lv.home}-${lv.away}` : l.score;
    return <span className="text-xs text-steel">Terminé{sc ? ` · ${sc}` : ""}{lv?.ht_home != null ? ` (mi-temps ${lv.ht_home}-${lv.ht_away})` : ""}</span>;
  }
  if (lv?.state === "live") {
    return (
      <span className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="flex items-center gap-1 rounded bg-brick px-1.5 py-0.5 font-bold text-white">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" aria-hidden />
          {lv.label === "Mi-temps" ? "Mi-temps" : `En direct${lv.minute && lv.minute !== "Mi-temps" ? ` ${lv.minute_estimated ? "≈ " : ""}${lv.minute}` : ""}`}
        </span>
        {lv.home != null ? <strong className="text-sm tabular-nums text-night">{lv.home} - {lv.away}</strong> : <span className="text-steel">score non disponible</span>}
        {lv.winning_now === true && <span className="rounded bg-pitch-soft px-1.5 py-0.5 font-semibold text-pitch-deep">Gagnante pour l&apos;instant</span>}
        {lv.winning_now === false && <span className="rounded bg-brick-soft px-1.5 py-0.5 font-semibold text-brick">Perdante pour l&apos;instant</span>}
      </span>
    );
  }
  if (lv?.state === "postponed") return <span className="text-xs font-semibold text-amber">Match reporté</span>;
  return <span className="text-xs text-steel">À venir · {kickoffLabel(l.kickoff, tz)}</span>;
}

export function JouerMesParis({ tz, justPlaced }: { tz: string; justPlaced: boolean }) {
  const [tab, setTab] = useState<"en-cours" | "termines" | "classement">("en-cours");
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async (t: string) => {
    try {
      const r = await fetch(`/api/proxy/jeu/mes-paris?statut=${t === "termines" ? "termines" : "en-cours"}`, { cache: "no-store" });
      const x = await r.json();
      if (!r.ok) throw new Error(x.detail || "Erreur");
      setD(x);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Erreur");
    }
  }, []);
  useEffect(() => { load(tab); }, [tab, load]);
  const anyLive = Boolean(d?.bets.some((b) => b.legs.some((l) => l.live?.state === "live" || (l.result === "pending" && new Date(l.kickoff).getTime() < Date.now() + 10 * 60000))));
  useEffect(() => {
    if (!anyLive || tab !== "en-cours") return;
    const t = setInterval(() => { if (document.visibilityState === "visible") load(tab); }, 60000);
    return () => clearInterval(t);
  }, [anyLive, tab, load]);

  const w = d?.wallet;
  const rk = d?.ranking;
  return (
    <>
      <JouerHeader title="Mes paris" wallet={w} back="/jouer" />
      {justPlaced && <p className="mb-3 rounded-xl bg-pitch-soft px-3 py-2 text-sm font-semibold text-pitch-deep">Pari enregistré. Il sera réglé automatiquement après le match.</p>}
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-xl bg-white p-3"><div className="text-[11px] text-steel">Solde</div><div className="font-display text-lg font-bold">{w ? fmtJetons(w.balance) : "…"}</div></div>
        <div className="rounded-xl bg-white p-3"><div className="text-[11px] text-steel">Réussite</div><div className="font-display text-lg font-bold">{w?.hit_rate != null ? pct(w.hit_rate) : "—"}</div></div>
        <div className="rounded-xl bg-white p-3"><div className="text-[11px] text-steel">Classement</div><div className="font-display text-lg font-bold">{rk?.me ? `${rk.me.position}e` : "—"}</div></div>
      </div>
      {w && <p className="mt-1.5 px-1 text-[11px] text-steel">Bonus de {w.daily_bonus} jetons crédité à la première visite de chaque jour.</p>}

      <div className="mt-3 grid grid-cols-3 gap-1 rounded-xl border border-line bg-white p-1" role="tablist">
        {([["en-cours", "En cours"], ["termines", "Terminés"], ["classement", "Classement"]] as const).map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-lg py-2 text-[13px] font-bold ${tab === k ? "bg-night text-white" : "text-steel"}`}>{l}</button>
        ))}
      </div>
      {err && <p className="mt-3 rounded-xl bg-amber-soft px-3 py-2 text-sm">{err}</p>}

      {tab === "classement" ? (
        <section className="mt-3 rounded-xl border border-line bg-white p-3">
          <h2 className="text-sm font-bold">Classement du mois</h2>
          <p className="mb-2 text-xs text-steel">Bénéfice net en jetons sur les paris réglés ce mois-ci ({rk?.players ?? 0} joueurs).</p>
          {!rk?.top.length && <p className="text-sm text-steel">Aucun pari réglé ce mois-ci.</p>}
          <ol className="space-y-1.5">
            {rk?.top.map((r) => (
              <li key={r.position} className={`grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-1.5 py-1 text-sm ${r.me ? "bg-pitch-soft" : ""}`}>
                <strong className="text-steel">{r.position}</strong>
                <span className="truncate">{r.me ? `${r.name} (vous)` : r.name}</span>
                <strong className={r.profit >= 0 ? "text-pitch-deep" : "text-brick"}>{r.profit > 0 ? "+" : ""}{fmtJetons(r.profit)}</strong>
              </li>
            ))}
            {rk?.me && !rk.top.some((r) => r.me) && (
              <li className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 rounded-lg bg-pitch-soft px-1.5 py-1 text-sm">
                <strong className="text-steel">{rk.me.position}</strong><span>Vous</span><strong>{fmtJetons(rk.me.profit)}</strong>
              </li>
            )}
          </ol>
        </section>
      ) : (
        <div className="mt-3 space-y-2.5">
          {d && d.bets.length === 0 && <p className="rounded-xl border border-dashed border-line bg-white/70 p-4 text-center text-sm text-steel">{tab === "en-cours" ? "Aucun pari en cours." : "Aucun pari terminé."}</p>}
          {d?.bets.map((b) => {
            const [lab, cls] = STATUS[b.status] ?? [b.status, ""];
            return (
              <article key={b.id} className="rounded-xl border border-line bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-bold">{b.kind === "combine" ? `Combiné · ${b.legs.length} sélections` : "Simple"}</span>
                  <span className="flex items-center gap-2">
                    {b.kind === "combine" && b.status === "pending" && <span className="text-xs font-semibold text-steel">{b.progress.won}/{b.progress.total} validées</span>}
                    <span className={`rounded-md px-2 py-0.5 text-xs font-bold ${cls}`}>{lab}</span>
                  </span>
                </div>
                <ul className="mt-2 divide-y divide-mist">
                  {b.legs.map((l) => (
                    <li key={`${l.match_id}-${l.label}`} className="flex gap-2.5 py-2">
                      <span className="shrink-0 pt-0.5"><ResultIcon r={l.result} /></span>
                      <span className="min-w-0 flex-1">
                        <a href={`/matchs/${l.match_id}`} className="block truncate text-sm font-semibold text-night">{l.match}</a>
                        <span className="block truncate text-[13px]">{l.label}</span>
                        <LegState l={l} tz={tz} />
                      </span>
                      <strong className="shrink-0 text-sm tabular-nums">{num(l.odds)}</strong>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex justify-between border-t border-line pt-2 text-[13px] text-steel">
                  <span>Mise {fmtJetons(b.stake)} · cote {num(b.total_odds)}{b.sam_probability != null ? ` · SAM ${pct(b.sam_probability)}` : ""}</span>
                  <strong className="text-night">{b.status === "pending" ? `Gain possible ${fmtJetons(b.potential)}` : b.status === "won" ? `+${fmtJetons(b.payout)}` : b.status === "void" ? `${fmtJetons(b.payout)} rendus` : "0"}</strong>
                </div>
              </article>
            );
          })}
        </div>
      )}
      <Legend />
    </>
  );
}
