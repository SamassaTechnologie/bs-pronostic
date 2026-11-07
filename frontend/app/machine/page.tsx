import { userTz } from "@/lib/api";
import { Machine } from "@/components/Machine";

export const dynamic = "force-dynamic";
export const metadata = { title: "Machine SAM" };

export default async function MachinePage() {
  const tz = await userTz();
  return (
    <>
      <div className="mb-3 px-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">Machine SAM</h1>
        <p className="text-sm text-steel">Choisissez vos critères : la machine cherche parmi les matchs analysés ceux qui les remplissent tous.</p>
      </div>
      <Machine tz={tz} />
      <p className="mt-4 px-1 text-[11.5px] text-steel">
        Probabilités et cotes justes issues des analyses SAM ; statistiques calculées sur les matchs réellement joués. Aucun résultat n&apos;est garanti.
      </p>
    </>
  );
}
