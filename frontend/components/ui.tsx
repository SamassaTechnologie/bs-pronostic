import Link from "next/link";
import type { ReactNode } from "react";
import { num, pct, signedPct } from "@/lib/format";

/** Barre de probabilité avec les seuils des niveaux C / B / A matérialisés. */
export function ProbBar({ p, thresholds = [0.7, 0.78, 0.85], size = "md" }: { p: number; thresholds?: number[]; size?: "sm" | "md" }) {
  const color = p >= thresholds[1] ? "bg-pitch" : p >= thresholds[0] ? "bg-sky" : "bg-steel/50";
  const h = size === "sm" ? "h-1.5" : "h-2.5";
  return (
    <div className={`relative w-full ${h} rounded-full bg-line/70`} role="img" aria-label={`Probabilité ${pct(p)}`}>
      <div className={`absolute inset-y-0 left-0 rounded-full ${color}`} style={{ width: `${Math.max(2, p * 100)}%` }} />
      {thresholds.map((t) => (
        <span key={t} className="absolute -top-0.5 -bottom-0.5 w-px bg-night/35" style={{ left: `${t * 100}%` }} />
      ))}
    </div>
  );
}

const TIER_STYLE: Record<string, string> = {
  A: "bg-pitch-deep text-white",
  B: "bg-pitch text-white",
  C: "bg-sky text-white",
  D: "bg-line text-steel",
};

export function TierBadge({ tier }: { tier: string }) {
  return (
    <span className={`inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1.5 text-xs font-bold ${TIER_STYLE[tier] ?? TIER_STYLE.D}`} title={`Niveau ${tier}`}>
      {tier}
    </span>
  );
}

export function ConfidenceBadge({ score, level }: { score: number; level: string }) {
  const style = level === "Élevée" ? "bg-pitch-soft text-pitch-deep" : level === "Moyenne" ? "bg-amber-soft text-amber" : "bg-brick-soft text-brick";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold ${style}`}>
      Confiance {level.toLowerCase()} <span className="font-normal opacity-80">{score}/100</span>
    </span>
  );
}

export function OddsInfo({ odds, edge, bookmaker }: { odds: number | null; edge: number | null; bookmaker?: string | null }) {
  if (!odds) return <span className="text-xs text-steel">Cote non disponible</span>;
  const edgeStyle = edge === null ? "" : edge > 0.02 ? "text-pitch-deep" : edge < -0.02 ? "text-brick" : "text-steel";
  return (
    <span className="text-xs text-steel">
      Cote <strong className="text-night">{num(odds)}</strong>
      {bookmaker ? ` (${bookmaker})` : ""}
      {edge !== null && <span className={`ml-1.5 font-semibold ${edgeStyle}`}>valeur {signedPct(edge)}</span>}
    </span>
  );
}

export function Section({ title, action, children, id }: { title: string; action?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section id={id} className="mt-7 min-w-0">
      <div className="mb-3 flex items-baseline justify-between gap-3 px-1">
        <h2 className="font-display text-lg font-bold tracking-tight text-night">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-line bg-white ${className}`}>{children}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-white/60 px-4 py-6 text-center">
      <p className="font-semibold text-night">{title}</p>
      {children && <div className="mt-1 text-sm text-steel">{children}</div>}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-brick/30 bg-brick-soft px-4 py-3 text-sm text-brick" role="alert">
      {message}
    </div>
  );
}

export function MoreLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="text-sm font-semibold text-sky hover:underline">
      {children}
    </Link>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-white px-3.5 py-3">
      <div className="text-xs text-steel">{label}</div>
      <div className="mt-0.5 font-display text-2xl font-bold tracking-tight text-night">{value}</div>
      {hint && <div className="text-[11px] text-steel">{hint}</div>}
    </div>
  );
}
