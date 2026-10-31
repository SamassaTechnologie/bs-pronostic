import Link from "next/link";
import { backend } from "@/lib/api";
import { flag } from "@/lib/flags";
import { Empty, Section } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Recherche" };

type Result = {
  teams: { id: number; name: string; country: string; next: { id: number; home: { name: string }; away: { name: string } } | null }[];
  competitions: { id: number; code: string; name: string; country: string }[];
  countries: string[];
};

export default async function Recherche({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const q = ((await searchParams).q || "").trim().slice(0, 60);
  const res = q.length >= 2 ? await backend<Result>(`/api/search?q=${encodeURIComponent(q)}`) : null;
  const r = res?.ok ? res.data : null;
  return (
    <>
      <form className="mb-4" action="/recherche">
        <input name="q" defaultValue={q} type="search" placeholder="Équipe, championnat ou pays" aria-label="Rechercher"
          className="w-full rounded-xl border border-line bg-white px-4 py-3 text-[16px]" />
      </form>
      {!q || q.length < 2 ? (
        <Empty title="Que cherchez-vous ?">Tapez le nom d&apos;une équipe, d&apos;un championnat ou d&apos;un pays.</Empty>
      ) : !r || (!r.teams.length && !r.competitions.length && !r.countries.length) ? (
        <Empty title={`Aucun résultat pour « ${q} »`}>Seuls les championnats suivis par SAM-Prédiction sont consultables.</Empty>
      ) : (
        <>
          {(r.competitions.length > 0 || r.countries.length > 0) && (
            <Section title="Championnats">
              <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                {r.competitions.map((c) => (
                  <Link key={c.code} href={`/ligues/${c.code}`} className="flex items-center gap-3 px-4 py-3">
                    <span className="text-xl" aria-hidden>{flag(c.country)}</span>
                    <span className="font-semibold">{c.name}</span>
                    <span className="text-xs text-steel">{c.country}</span>
                  </Link>
                ))}
                {r.countries.map((c) => (
                  <Link key={c} href={`/ligues#${encodeURIComponent(c)}`} className="flex items-center gap-3 px-4 py-3">
                    <span className="text-xl" aria-hidden>{flag(c)}</span>
                    <span className="font-semibold">Tous les championnats : {c}</span>
                  </Link>
                ))}
              </div>
            </Section>
          )}
          {r.teams.length > 0 && (
            <Section title="Équipes">
              <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
                {r.teams.map((t) => (
                  <Link key={t.id} href={`/equipes/${t.id}`} className="flex items-center gap-3 px-4 py-3">
                    <span className="text-xl" aria-hidden>{flag(t.country)}</span>
                    <span className="min-w-0">
                      <span className="block truncate font-semibold">{t.name}</span>
                      <span className="block truncate text-xs text-steel">{t.next ? `Prochain : ${t.next.home.name} – ${t.next.away.name}` : t.country}</span>
                    </span>
                  </Link>
                ))}
              </div>
            </Section>
          )}
        </>
      )}
    </>
  );
}
