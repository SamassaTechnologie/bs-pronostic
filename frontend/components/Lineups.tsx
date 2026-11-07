import type { TeamLineup } from "@/components/LiveHeader";

function Col({ t, name }: { t: TeamLineup; name: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-[13px] font-bold text-night">{name}</div>
      <div className="mb-1.5 text-[11.5px] text-steel">{t.formation ?? "Système non communiqué"}</div>
      <ol className="space-y-0.5">
        {t.starting.map((p) => (
          <li key={`${p.number}-${p.name}`} className="flex items-center gap-1.5 text-[13px]">
            <span className="w-5 shrink-0 text-right text-[11px] font-bold tabular-nums text-steel">{p.number ?? ""}</span>
            <span className="truncate">{p.name}</span>
          </li>
        ))}
      </ol>
      {t.coach && <div className="mt-1.5 truncate text-[11.5px] text-steel">Entraîneur : {t.coach}</div>}
    </div>
  );
}

/** Compositions officielles (source AllSportsAPI, publiées environ une heure avant le coup d'envoi). */
export function Lineups({ l, home, away }: { l: { home: TeamLineup; away: TeamLineup }; home: string; away: string }) {
  const bench = l.home.bench.length + l.away.bench.length > 0;
  const missing = l.home.missing.length + l.away.missing.length > 0;
  return (
    <div className="rounded-xl border border-line bg-white p-3.5">
      <div className="grid grid-cols-2 gap-3">
        <Col t={l.home} name={home} />
        <Col t={l.away} name={away} />
      </div>
      {bench && (
        <details className="group mt-3 border-t border-line pt-2">
          <summary className="cursor-pointer list-none text-[12.5px] font-bold text-sky [&::-webkit-details-marker]:hidden">Remplaçants</summary>
          <div className="mt-1.5 grid grid-cols-2 gap-3 text-[12.5px] text-steel">
            {[l.home, l.away].map((t, i) => (
              <ul key={i} className="space-y-0.5">{t.bench.map((p) => <li key={`${p.number}-${p.name}`} className="truncate">{p.number ?? ""} {p.name}</li>)}</ul>
            ))}
          </div>
        </details>
      )}
      {missing && (
        <p className="mt-2 text-[12px] text-brick">Absents : {[...l.home.missing, ...l.away.missing].join(", ")}</p>
      )}
      <p className="mt-2 text-[10.5px] text-steel">Compositions officielles · AllSportsAPI</p>
    </div>
  );
}
