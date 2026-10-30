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
      <ComboBuilder tz={tz} />
    </>
  );
}
