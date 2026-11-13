import Link from "next/link";
import { userTz } from "@/lib/api";
import { ComboBuilder } from "@/components/ComboBuilder";

export const dynamic = "force-dynamic";
export const metadata = { title: "Combinés" };

export default async function Combines() {
  const tz = await userTz();
  return (
    <>
      <div className="mb-4 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Combinés</h1>
        <p className="text-sm text-steel">
          Chaque match ajouté réduit les chances de passer. Le risque réel est affiché avant toute décision.
        </p>
      </div>
      <nav className="mb-5 grid grid-cols-4 gap-1.5 text-center text-[12px] font-bold" aria-label="Sections">
        <a href="#objectif" className="rounded-xl border border-line bg-white px-1 py-2.5 text-night">Objectif<br /><span className="font-semibold text-steel">de cote</span></a>
        <a href="#auto" className="rounded-xl border border-line bg-white px-1 py-2.5 text-night">Génération<br /><span className="font-semibold text-steel">automatique</span></a>
        <a href="#surmesure" className="rounded-xl border border-line bg-white px-1 py-2.5 text-night">Combiné<br /><span className="font-semibold text-steel">sur mesure</span></a>
        <Link href="/machine" className="rounded-xl bg-night px-1 py-2.5 text-white">Machine<br /><span className="font-semibold text-white/80">SAM</span></Link>
      </nav>
      <ComboBuilder tz={tz} />
    </>
  );
}
