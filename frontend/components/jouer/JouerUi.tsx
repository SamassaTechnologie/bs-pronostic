"use client";
import Link from "next/link";
import { num, pct } from "@/lib/format";
import { useCoupon, type CouponSel } from "@/lib/coupon";

export type OddsRow = { key: string; label: string; short: string; family: string; odds: number; odds_source: "bookmaker" | "sam"; probability: number; confidence: number | null; is_pick: boolean; extended?: boolean };
export type Wallet = { balance: number; name: string; pending: number; daily_bonus: number; settled: number; won: number; hit_rate: number | null; profit: number };

export function fmtJetons(n: number) {
  return new Intl.NumberFormat("fr-FR").format(n);
}

export function JouerHeader({ title, sub, wallet, back }: { title: string; sub?: string; wallet?: Wallet | null; back?: string }) {
  return (
    <div className="-mx-3.5 -mt-4 mb-3 bg-night px-4 pb-3 pt-3.5 text-white md:mx-0 md:mt-0 md:rounded-2xl">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          {back && <Link href={back} className="mb-0.5 block text-sm font-semibold text-white/70">Retour</Link>}
          <h1 className="truncate font-display text-lg font-bold">{title}</h1>
          {sub && <p className="text-xs text-white/70">{sub}</p>}
        </div>
        <Link href="/jouer/mes-paris" className="flex shrink-0 items-center gap-1.5 rounded-xl bg-pitch px-3 py-2 text-sm font-bold text-white">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><circle cx="12" cy="12" r="9" /><path d="M9 12h6M12 9v6" /></svg>
          {wallet ? `${fmtJetons(wallet.balance)} jetons` : "…"}
        </Link>
      </div>
    </div>
  );
}

/** Bouton de cote : ajoute ou retire la sélection du coupon. */
export function OddsButton({ row, matchId, matchLabel, label, showProb = false, open = true }: {
  row: OddsRow; matchId: number; matchLabel: string; label?: string; showProb?: boolean; open?: boolean;
}) {
  const { has, toggle } = useCoupon();
  const on = has(matchId, row.key);
  const sel: CouponSel = { match_id: matchId, market_key: row.key, label: row.label, match: matchLabel, odds: row.odds };
  return (
    <button type="button" disabled={!open} onClick={() => toggle(sel)} aria-pressed={on}
      aria-label={`${row.label}, cote ${num(row.odds)}${row.odds_source === "sam" ? " (cote SAM)" : ""}`}
      className={`flex min-h-[44px] min-w-0 flex-col items-center justify-center rounded-lg border px-1 py-1.5 text-night disabled:opacity-50 ${
        on ? "border-2 border-pitch bg-pitch-soft" : "border-line bg-mist"}`}>
      {showProb ? (
        <>
          {label !== " " && <span className="max-w-full truncate text-[11px] text-steel">{label ?? row.short}</span>}
          <strong className="text-[15px] tabular-nums">{num(row.odds)}{row.odds_source === "sam" ? <sup className="ml-0.5 text-[9px] font-semibold text-steel">S</sup> : null}</strong>
          <span className={`text-[10.5px] font-semibold ${row.is_pick ? "text-pitch-deep" : "text-steel"}`}>SAM {pct(row.probability)}</span>
        </>
      ) : (
        <span className="flex items-center gap-1.5 text-sm">
          <span className="text-steel">{label ?? row.short}</span>
          <strong className="tabular-nums">{num(row.odds)}</strong>
        </span>
      )}
    </button>
  );
}

export function CouponBar() {
  const { items, total } = useCoupon();
  if (!items.length) return null;
  return (
    <Link href="/jouer/coupon"
      className="fixed inset-x-3 bottom-[calc(env(safe-area-inset-bottom)+68px)] z-30 mx-auto flex max-w-md items-center justify-between rounded-2xl bg-night px-4 py-3 text-white shadow-lg md:bottom-6">
      <span className="flex items-center gap-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-pitch text-sm font-bold">{items.length}</span>
        <span className="font-bold">Coupon</span>
      </span>
      <span className="text-sm text-white/80">{items.length > 1 ? `Cote ${num(total)}` : `Cote ${num(items[0].odds)}`}</span>
    </Link>
  );
}

export function Legend() {
  return (
    <p className="mt-4 px-1 text-[11px] leading-relaxed text-steel">
      Jeu en jetons virtuels, sans argent réel : aucun dépôt, aucun retrait, aucun gain monétaire. Cotes : bookmaker quand elle est
      collectée, sinon cote SAM (<sup>S</sup>) = cote juste du moteur moins 6 %. Paris acceptés jusqu&apos;au coup d&apos;envoi,
      réglés automatiquement avec les scores officiels.
    </p>
  );
}
