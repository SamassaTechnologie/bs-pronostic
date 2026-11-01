"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { MatchSummary } from "@/lib/types";
import { kickoffLabel, num } from "@/lib/format";
import { CouponBar, JouerHeader, Legend, OddsButton, type OddsRow, type Wallet } from "./JouerUi";

type Data = {
  match: MatchSummary | null; open: boolean; message: string | null; wallet: Wallet;
  groups: { family: string; label: string; markets: OddsRow[] }[];
  expected_goals: { home: number; away: number } | null; avoid_reasons: string[];
};

export function JouerMatch({ id, tz }: { id: number; tz: string }) {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fam, setFam] = useState("tous");

  useEffect(() => {
    fetch(`/api/proxy/jeu/matchs/${id}`, { cache: "no-store" })
      .then(async (r) => { const x = await r.json(); if (!r.ok) throw new Error(x.detail || "Erreur"); setD(x); })
      .catch((e) => setErr(e instanceof Error ? e.message : "Erreur"));
  }, [id]);

  const m = d?.match;
  const label = m ? `${m.home.name} – ${m.away.name}` : "";
  const groups = (d?.groups ?? []).filter((g) => fam === "tous" || g.family === fam);
  const pick = d?.groups.flatMap((g) => g.markets).filter((x) => x.is_pick).sort((a, b) => b.probability - a.probability)[0];

  return (
    <>
      <JouerHeader title={m ? label : "Match"} sub={m ? `${m.competition.name} · ${kickoffLabel(m.kickoff, tz)}` : undefined} wallet={d?.wallet} back="/jouer" />
      {err && <p className="rounded-xl bg-amber-soft px-4 py-3 text-sm">{err}</p>}
      {!d && !err && <p className="mt-6 text-center text-sm text-steel">Chargement des marchés…</p>}
      {d && (
        <>
          {(pick || d.expected_goals) && (
            <div className="flex items-center gap-2 rounded-xl bg-ink px-3 py-2.5 text-[13px] text-white">
              <span className="rounded bg-pitch px-1.5 py-0.5 text-[11px] font-bold">SAM</span>
              <span className="min-w-0">
                {pick ? `${pick.label} : ${Math.round(pick.probability * 100)} %` : ""}
                {pick && d.expected_goals ? " · " : ""}
                {d.expected_goals ? `buts attendus ${num(d.expected_goals.home)} – ${num(d.expected_goals.away)}` : ""}
              </span>
            </div>
          )}
          {d.avoid_reasons.length > 0 && <p className="mt-2 rounded-xl bg-amber-soft px-3 py-2 text-xs text-ink"><strong>Match à éviter selon SAM.</strong> {d.avoid_reasons.join(". ")}.</p>}
          {d.message && <p className="mt-2 rounded-xl bg-brick-soft px-3 py-2 text-sm text-brick">{d.message}</p>}
          <div className="mt-3 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
            {[{ family: "tous", label: "Tous" }, ...d.groups].map((g) => (
              <button key={g.family} type="button" onClick={() => setFam(g.family)} aria-pressed={fam === g.family}
                className={`shrink-0 rounded-full px-3 py-1.5 text-[13px] font-semibold ${fam === g.family ? "bg-night text-white" : "border border-line bg-white text-night"}`}>
                {g.label}
              </button>
            ))}
          </div>
          <div className="mt-2 space-y-2.5">
            {groups.map((g) => (
              <section key={g.family} className="rounded-xl border border-line bg-white p-3">
                <h2 className="mb-2 text-sm font-bold">{g.label}</h2>
                <div className="grid grid-cols-3 gap-1.5">
                  {g.markets.map((r) => (
                    <OddsButton key={r.key} row={r} matchId={id} matchLabel={label} label={r.short} showProb open={d.open} />
                  ))}
                </div>
              </section>
            ))}
          </div>
          <Link href={`/matchs/${id}`} className="mt-3 block text-center text-sm font-semibold text-sky">Voir l&apos;analyse complète du match</Link>
        </>
      )}
      <Legend />
      <div className="h-16" />
      <CouponBar />
    </>
  );
}
