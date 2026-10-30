import Link from "next/link";
import { dateTime, hoursSince } from "@/lib/format";

export function Freshness({ lastSync, lastAnalysis, tz }: { lastSync: string | null; lastAnalysis: string | null; tz: string }) {
  const age = hoursSince(lastSync);
  if (!lastSync) {
    return (
      <div className="rounded-xl border border-amber/30 bg-amber-soft px-4 py-3 text-sm text-ink">
        <strong>Aucune donnée synchronisée pour l&apos;instant.</strong> Lancez une première synchronisation depuis{" "}
        <Link href="/admin" className="font-semibold text-sky underline">l&apos;administration</Link> (elle démarre aussi
        automatiquement au lancement du serveur).
      </div>
    );
  }
  const stale = age !== null && age > 24;
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl px-4 py-2.5 text-xs ${stale ? "border border-amber/30 bg-amber-soft text-ink" : "bg-white text-steel"}`}>
      <span className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${stale ? "bg-amber" : "bg-pitch"}`} aria-hidden />
        Données actualisées le {dateTime(lastSync, tz)}
      </span>
      {lastAnalysis && <span>Analyse du {dateTime(lastAnalysis, tz)}</span>}
      {stale && <span className="font-semibold">Une source est peut-être indisponible : les chiffres datent de plus de 24 h.</span>}
    </div>
  );
}
