"use client";
import { useCallback, useEffect, useState } from "react";
import { dateTime, num, pct } from "@/lib/format";
import { ConfidenceBadge, ProbBar } from "./ui";

type AiPick = {
  market_key: string; label: string; argument: string; probability: number;
  confidence: { score: number; level: string }; odds: number | null; fair_odds: number; is_pick: boolean;
};
type AiContent = {
  titre: string; resume: string; contexte: string[]; analyse_domicile: string; analyse_exterieur: string;
  confrontations: string; scenario: string; pronostic_principal: AiPick | null; alternatives: AiPick[];
  points_de_vigilance: string[];
};
type AiResponse =
  | { status: "ok"; provider: string; model: string; created_at: string; removed_sentences: number; stale?: boolean; analysis: AiContent }
  | { status: "not_configured" | "insufficient" | "unavailable" | "error" | "pending"; message: string; retryable?: boolean };

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line px-4 py-3.5">
      <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wide text-steel">{title}</h3>
      <div className="text-[15px] leading-relaxed text-ink">{children}</div>
    </section>
  );
}

function PickBox({ p, main, thresholds }: { p: AiPick; main?: boolean; thresholds?: number[] }) {
  return (
    <div className={`rounded-xl border ${main ? "border-pitch/40 bg-pitch-soft/40" : "border-line bg-white"} p-3.5`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-bold uppercase tracking-wide text-steel">{main ? "Pronostic principal" : "Alternative"}</div>
          <div className={`font-display font-bold leading-tight ${main ? "text-lg" : "text-base"}`}>{p.label}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <ConfidenceBadge score={p.confidence.score} level={p.confidence.level} />
            <span className="text-xs text-steel">{p.odds ? `cote ${num(p.odds)}` : `cote juste ${num(p.fair_odds)}`}</span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`font-display font-bold ${main ? "text-3xl" : "text-2xl"}`}>{pct(p.probability)}</div>
          <div className="text-[10px] text-steel">probabilité SAM</div>
        </div>
      </div>
      {main && <div className="mt-2"><ProbBar p={p.probability} thresholds={thresholds} size="sm" /></div>}
      {p.argument && <p className="mt-2 text-sm text-ink">{p.argument}</p>}
    </div>
  );
}

/** Analyse d'avant-match rédigée par IA à partir du seul dossier de données SAM. */
export function AiAnalysis({ matchId, home, away, tz, thresholds }: { matchId: number; home: string; away: string; tz: string; thresholds?: number[] }) {
  const [res, setRes] = useState<AiResponse | null>(null);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await fetch(`/api/proxy/matches/${matchId}/ai`, { cache: "no-store" });
      const d = await r.json();
      setRes(r.ok ? d : { status: "error", message: d.detail || d.error || "Service indisponible", retryable: true });
    } catch {
      setRes({ status: "error", message: "Connexion impossible", retryable: true });
    } finally {
      setBusy(false);
    }
  }, [matchId]);

  useEffect(() => { load(); }, [load]);

  if (busy) {
    return (
      <div className="mt-4 rounded-xl border border-line bg-white p-5" aria-busy="true">
        <div className="flex items-center gap-2 text-sm font-semibold text-night">
          <span className="h-2 w-2 animate-pulse rounded-full bg-pitch" aria-hidden />
          L&apos;IA rédige l&apos;analyse à partir des données SAM…
        </div>
        <p className="mt-1 text-xs text-steel">10 à 20 secondes la première fois, instantané ensuite.</p>
        <div className="mt-4 space-y-2.5">
          {[90, 75, 82, 60].map((w) => <div key={w} className="h-3 animate-pulse rounded bg-mist" style={{ width: `${w}%` }} />)}
        </div>
      </div>
    );
  }
  if (!res || res.status !== "ok") {
    const msg = res?.message ?? "Analyse indisponible";
    return (
      <div className="mt-4 rounded-xl border border-dashed border-line bg-white/70 p-5 text-center">
        <p className="text-sm font-semibold text-night">{msg}</p>
        {res?.status === "not_configured" && <p className="mt-1 text-xs text-steel">Les analyses statistiques des autres onglets restent disponibles.</p>}
        {res?.status === "error" && res.retryable !== false && (
          <button type="button" onClick={load} className="mt-3 rounded-lg bg-night px-4 py-2 text-sm font-bold text-white">Réessayer</button>
        )}
      </div>
    );
  }

  const a = res.analysis;
  return (
    <article className="mt-4 overflow-hidden rounded-xl border border-line bg-white">
      <header className="bg-night px-4 py-4 text-white">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide text-white/70">
          <span className="rounded bg-white/15 px-1.5 py-0.5 text-white">IA</span> Analyse d&apos;avant-match
        </div>
        <h2 className="mt-1.5 font-display text-xl font-bold leading-snug">{a.titre}</h2>
        <p className="mt-2 text-[15px] leading-relaxed text-white/90">{a.resume}</p>
      </header>

      {a.pronostic_principal && (
        <div className="space-y-2.5 px-4 py-4">
          <PickBox p={a.pronostic_principal} main thresholds={thresholds} />
          {a.alternatives.length > 0 && (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {a.alternatives.map((p) => <PickBox key={p.market_key} p={p} />)}
            </div>
          )}
        </div>
      )}

      {a.contexte.length > 0 && (
        <Block title="Contexte">
          <ul className="space-y-1">
            {a.contexte.map((c) => (
              <li key={c} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-sky" aria-hidden />{c}</li>
            ))}
          </ul>
        </Block>
      )}
      <div className="grid sm:grid-cols-2">
        {a.analyse_domicile && <Block title={home}>{a.analyse_domicile}</Block>}
        {a.analyse_exterieur && <Block title={away}>{a.analyse_exterieur}</Block>}
      </div>
      {a.confrontations && <Block title="Confrontations directes">{a.confrontations}</Block>}
      {a.scenario && <Block title="Scénario probable">{a.scenario}</Block>}
      {a.points_de_vigilance.length > 0 && (
        <Block title="Points de vigilance">
          <ul className="space-y-1">
            {a.points_de_vigilance.map((c) => (
              <li key={c} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber" aria-hidden />{c}</li>
            ))}
          </ul>
        </Block>
      )}

      <footer className="border-t border-line bg-mist/60 px-4 py-3 text-[11px] leading-relaxed text-steel">
        Rédigée par {res.provider} ({res.model}) le {dateTime(res.created_at, tz)}, uniquement à partir des données SAM.
        L&apos;IA ne calcule aucune probabilité : les pourcentages et cotes viennent du moteur statistique, et chaque chiffre
        du texte est contrôlé (il doit figurer dans les données SAM, sinon la phrase est retirée).
        {res.stale ? " Analyse précédente affichée : la mise à jour n'a pas pu être rédigée." : ""} Aucune garantie de gain.
      </footer>
    </article>
  );
}
