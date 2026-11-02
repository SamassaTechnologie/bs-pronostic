import Link from "next/link";
import { backend } from "@/lib/api";
import { flag } from "@/lib/flags";
import { ErrorBox } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Championnats" };

type Comp = { id: number; code: string; name: string; country: string; upcoming: number; picks: number; popular?: boolean };

function Row({ c, showCountry }: { c: Comp; showCountry?: boolean }) {
  return (
    <Link href={`/ligues/${c.code}`} className="flex items-center justify-between gap-3 px-4 py-3.5">
      <span className="min-w-0">
        <span className="block truncate font-semibold">{showCountry && <span className="mr-1.5" aria-hidden>{flag(c.country)}</span>}{c.name}</span>
        {showCountry && <span className="block text-xs text-steel">{c.country}</span>}
      </span>
      <span className="shrink-0 text-xs text-steel">
        {c.upcoming ? `${c.upcoming} match${c.upcoming > 1 ? "s" : ""} à venir` : "Pas de match ces 3 jours"}
        {c.picks ? <span className="ml-2 rounded-md bg-pitch-soft px-1.5 py-0.5 font-semibold text-pitch-deep">{c.picks} prono.</span> : null}
      </span>
    </Link>
  );
}

export default async function Ligues() {
  const res = await backend<{ items: Comp[] }>("/api/competitions", { revalidate: 300 });
  if (!res.ok) return <ErrorBox message={res.error} />;
  const popular = res.data.items.filter((c) => c.popular);
  const byCountry = new Map<string, Comp[]>();
  for (const c of [...res.data.items].filter((c) => !c.popular).sort((a, b) => a.country.localeCompare(b.country, "fr") || a.name.localeCompare(b.name, "fr")))
    byCountry.set(c.country, [...(byCountry.get(c.country) ?? []), c]);
  return (
    <>
      <div className="mb-4 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Championnats</h1>
        <p className="text-sm text-steel">Classements, statistiques et prochains matchs de chaque compétition suivie.</p>
      </div>
      <div className="space-y-5">
        {popular.length > 0 && (
          <section id="grands-championnats">
            <h2 className="mb-2 flex items-center gap-2 px-1 text-sm font-bold text-night">
              <span className="text-amber" aria-hidden>★</span>Grands championnats
            </h2>
            <div className="divide-y divide-line overflow-hidden rounded-xl border border-amber/40 bg-white">
              {popular.map((c) => <Row key={c.code} c={c} showCountry />)}
            </div>
          </section>
        )}
        {[...byCountry.entries()].map(([country, comps]) => (
          <section key={country} id={country}>
            <h2 className="mb-2 flex items-center gap-2 px-1 text-sm font-bold text-steel">
              <span className="text-lg" aria-hidden>{flag(country)}</span>{country}
            </h2>
            <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
              {comps.map((c) => <Row key={c.code} c={c} />)}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
