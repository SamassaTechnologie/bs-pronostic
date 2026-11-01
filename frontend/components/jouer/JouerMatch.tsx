"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { MatchSummary } from "@/lib/types";
import { kickoffLabel, num, pct } from "@/lib/format";
import { useCoupon } from "@/lib/coupon";
import { CouponBar, JouerHeader, Legend, type OddsRow, type Wallet } from "./JouerUi";

type Cell = (OddsRow & { label?: string }) | null;
type Block =
  | { title: string; kind: "grid"; columns: string[]; rows: { label: string; cells: Cell[] }[]; labelled_cells?: boolean; extra?: (OddsRow & { label: string })[] }
  | { title: string; kind: "flow"; cells: (OddsRow & { label: string })[]; highlight?: boolean };
type Tab = { id: string; label: string; count?: number; blocks: Block[] };
type Data = {
  match: MatchSummary | null; open: boolean; message: string | null; wallet: Wallet; tabs: Tab[];
  expected_goals: { home: number; away: number } | null; avoid_reasons: string[];
};

/** Cote compacte d'une grille : cote en gras, probabilité SAM dessous ; libellé facultatif à gauche. */
function OddCell({ m, matchId, matchLabel, open, inlineLabel, betLabel }: {
  m: OddsRow; matchId: number; matchLabel: string; open: boolean; inlineLabel?: string; betLabel: string;
}) {
  const { has, toggle } = useCoupon();
  const on = has(matchId, m.key);
  return (
    <button type="button" disabled={!open} aria-pressed={on}
      onClick={() => toggle({ match_id: matchId, market_key: m.key, label: betLabel, match: matchLabel, odds: m.odds })}
      aria-label={`${betLabel}, cote ${num(m.odds)}`}
      className={`flex min-h-[46px] w-full min-w-0 items-center justify-between gap-1.5 rounded-lg border px-2 py-1 text-left disabled:opacity-50 ${
        on ? "border-2 border-pitch bg-pitch-soft" : m.is_pick ? "border-pitch/40 bg-white" : "border-line bg-mist"}`}>
      {inlineLabel && <span className="min-w-0 truncate text-[12px] text-steel">{inlineLabel}</span>}
      <span className={`flex flex-col ${inlineLabel ? "items-end" : "w-full items-center"}`}>
        <strong className="text-[15px] leading-tight tabular-nums text-night">{num(m.odds)}</strong>
        <span className={`text-[10px] font-semibold leading-tight ${m.is_pick ? "text-pitch-deep" : "text-steel"}`}>{pct(m.probability)}</span>
      </span>
    </button>
  );
}

function BlockView({ b, matchId, matchLabel, open, defaultOpen }: { b: Block; matchId: number; matchLabel: string; open: boolean; defaultOpen: boolean }) {
  const [shown, setShown] = useState(defaultOpen);
  const count = b.kind === "flow" ? b.cells.length : b.rows.reduce((t, r) => t + r.cells.filter(Boolean).length, 0);
  return (
    <section className={`overflow-hidden rounded-xl border bg-white ${b.kind === "flow" && b.highlight ? "border-pitch/40" : "border-line"}`}>
      <button type="button" onClick={() => setShown(!shown)} aria-expanded={shown}
        className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left">
        <span className="flex min-w-0 items-center gap-2">
          {b.kind === "flow" && b.highlight && <span className="rounded bg-pitch px-1.5 py-0.5 text-[10px] font-bold text-white">SAM</span>}
          <span className="truncate text-[14px] font-bold text-night">{b.title}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2 text-xs text-steel">
          {count}
          <svg viewBox="0 0 24 24" className={`h-4 w-4 transition-transform ${shown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 9l6 6 6-6" /></svg>
        </span>
      </button>
      {shown && (
        <div className="border-t border-line px-2.5 pb-2.5 pt-2">
          {b.kind === "flow" ? (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {b.cells.map((c) => (
                <OddCell key={c.key} m={c} matchId={matchId} matchLabel={matchLabel} open={open} inlineLabel={c.label} betLabel={c.label} />
              ))}
            </div>
          ) : (
            <>
              <div className="grid gap-1.5" style={{ gridTemplateColumns: `${b.rows.some((r) => r.label) ? "minmax(64px, 0.9fr) " : ""}repeat(${b.columns.length}, minmax(0, 1fr))` }}>
                {b.rows.some((r) => r.label) && <span />}
                {b.columns.map((c) => <span key={c} className="truncate px-0.5 pb-0.5 text-center text-[11px] font-semibold text-steel">{c}</span>)}
                {b.rows.map((r, i) => (
                  <div key={`${r.label}-${i}`} className="contents">
                    {b.rows.some((x) => x.label) && <span className="flex items-center text-[12.5px] font-semibold leading-tight text-ink">{r.label}</span>}
                    {r.cells.map((c, j) => c ? (
                      <OddCell key={c.key} m={c} matchId={matchId} matchLabel={matchLabel} open={open}
                        inlineLabel={b.labelled_cells ? c.label : undefined}
                        betLabel={`${b.title}${r.label ? ` ${r.label}` : ""} : ${b.labelled_cells ? c.label : b.columns[j]}`} />
                    ) : <span key={`e${j}`} />)}
                  </div>
                ))}
              </div>
              {b.extra && b.extra.length > 0 && (
                <div className="mt-1.5 grid gap-1.5">
                  {b.extra.map((c) => <OddCell key={c.key} m={c} matchId={matchId} matchLabel={matchLabel} open={open} inlineLabel={c.label} betLabel={c.label} />)}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

export function JouerMatch({ id, tz }: { id: number; tz: string }) {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState("populaires");

  useEffect(() => {
    fetch(`/api/proxy/jeu/matchs/${id}`, { cache: "no-store" })
      .then(async (r) => { const x = await r.json(); if (!r.ok) throw new Error(x.detail || "Erreur"); setD(x); })
      .catch((e) => setErr(e instanceof Error ? e.message : "Erreur"));
  }, [id]);

  const m = d?.match;
  const label = m ? `${m.home.name} – ${m.away.name}` : "";
  const current = d?.tabs.find((t) => t.id === tab) ?? d?.tabs[0];
  const total = d?.tabs.filter((t) => t.id !== "populaires").reduce((s, t) => s + (t.count ?? 0), 0) ?? 0;

  return (
    <>
      <JouerHeader title={m ? label : "Match"} sub={m ? `${m.competition.name} · ${kickoffLabel(m.kickoff, tz)}` : undefined} wallet={d?.wallet} back="/jouer" />
      {err && <p className="rounded-xl bg-amber-soft px-4 py-3 text-sm">{err}</p>}
      {!d && !err && <p className="mt-6 text-center text-sm text-steel">Chargement des marchés…</p>}
      {d && (
        <>
          {d.expected_goals && (
            <div className="flex items-center justify-between gap-2 rounded-xl bg-ink px-3 py-2.5 text-[13px] text-white">
              <span className="flex items-center gap-2">
                <span className="rounded bg-pitch px-1.5 py-0.5 text-[11px] font-bold">SAM</span>
                Buts attendus {num(d.expected_goals.home)} – {num(d.expected_goals.away)}
              </span>
              <span className="text-xs text-white/70">{total} cotes</span>
            </div>
          )}
          {d.avoid_reasons.length > 0 && <p className="mt-2 rounded-xl bg-amber-soft px-3 py-2 text-xs text-ink"><strong>Match à éviter selon SAM.</strong> {d.avoid_reasons.join(". ")}.</p>}
          {d.message && <p className="mt-2 rounded-xl bg-brick-soft px-3 py-2 text-sm text-brick">{d.message}</p>}

          <div className="sticky top-[calc(env(safe-area-inset-top)+60px)] z-20 -mx-3.5 mt-3 bg-mist/95 px-3.5 py-2 backdrop-blur md:static md:mx-0 md:px-0">
            <div className="flex gap-1.5 overflow-x-auto [scrollbar-width:none]" role="tablist">
              {d.tabs.map((t) => (
                <button key={t.id} type="button" role="tab" aria-selected={current?.id === t.id} onClick={() => setTab(t.id)}
                  className={`shrink-0 rounded-full px-3.5 py-2 text-[13px] font-bold ${current?.id === t.id ? "bg-night text-white" : "border border-line bg-white text-night"}`}>
                  {t.label}{t.count ? <span className={`ml-1 font-semibold ${current?.id === t.id ? "text-white/70" : "text-steel"}`}>{t.count}</span> : null}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-1 space-y-2">
            {current?.blocks.map((b, i) => (
              <BlockView key={`${current.id}-${b.title}`} b={b} matchId={id} matchLabel={label} open={d.open} defaultOpen={i < 4} />
            ))}
          </div>
          <p className="mt-3 px-1 text-[11px] leading-relaxed text-steel">
            Sous chaque cote : probabilité SAM. Les marchés hors 1X2, double chance, buts, mi-temps, corners et cartons sont dérivés du
            modèle de buts et proposés en cote SAM ; la plupart ont été validés sur 5 539 matchs passés.
          </p>
          <Link href={`/matchs/${id}`} className="mt-2 block text-center text-sm font-semibold text-sky">Voir l&apos;analyse complète du match</Link>
        </>
      )}
      <Legend />
      <div className="h-16" />
      <CouponBar />
    </>
  );
}
