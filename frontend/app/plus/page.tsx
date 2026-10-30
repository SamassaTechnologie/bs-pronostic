import Link from "next/link";
import { backend, userTz } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { Meta } from "@/lib/types";
import { TimezoneSelect } from "@/components/TimezoneSelect";
import { Card, Section } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Plus" };

export default async function Plus() {
  const tz = await userTz();
  const meta = await backend<Meta>("/api/meta");
  const m = meta.data;
  return (
    <>
      <h1 className="mb-3 px-1 font-display text-2xl font-bold tracking-tight">Réglages et informations</h1>
      <Card className="p-4">
        <TimezoneSelect current={tz} />
      </Card>

      <Section title="Sources de données">
        <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
          {m?.providers.map((p) => (
            <div key={p.name} className="px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{p.label}</span>
                <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${p.configured && p.enabled ? "bg-pitch-soft text-pitch-deep" : "bg-mist text-steel"}`}>
                  {!p.configured ? "Non configurée" : p.enabled ? "Active" : "Désactivée"}
                </span>
              </div>
              <div className="text-xs text-steel">
                {p.capabilities.join(", ")}. Dernière synchronisation réussie : {dateTime(p.last_ok, tz)}.
              </div>
            </div>
          )) ?? <p className="p-4 text-sm text-steel">{meta.error}</p>}
        </div>
      </Section>

      <Section title="Championnats suivis">
        <Card className="p-4 text-sm">
          {m?.competitions.length ? m.competitions.map((c) => `${c.name} (${c.country})`).join(", ") : "Aucun championnat activé."}
        </Card>
      </Section>

      <div className="mt-7 grid gap-2.5">
        <Link href="/methodologie" className="rounded-xl border border-line bg-white px-4 py-3.5 font-semibold">Comment sont calculées les probabilités</Link>
        <Link href="/admin" className="rounded-xl border border-line bg-white px-4 py-3.5 font-semibold">Administration</Link>
      </div>

      <p className="mt-6 px-1 text-xs text-steel">{m?.disclaimer}</p>
      <p className="mt-2 px-1 text-xs text-steel">
        Sur iPhone : ouvrez le site dans Safari, touchez Partager puis « Sur l&apos;écran d&apos;accueil » pour l&apos;utiliser comme une application.
      </p>
    </>
  );
}
