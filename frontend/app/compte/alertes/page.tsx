import Link from "next/link";
import { redirect } from "next/navigation";
import { backend } from "@/lib/api";
import { currentMember } from "@/lib/supabase/server";
import { AlertsManager } from "@/components/AlertsManager";

export const dynamic = "force-dynamic";
export const metadata = { title: "Mes alertes" };

export default async function Alertes() {
  const me = await currentMember();
  if (!me) redirect("/connexion?suite=/compte/alertes");
  const comps = await backend<{ items: { code: string; name: string; country: string; popular: boolean }[] }>("/api/competitions", { revalidate: 600 });
  return (
    <>
      <Link href="/compte" className="px-1 text-sm font-semibold text-sky">‹ Mon compte</Link>
      <h1 className="mt-1 px-1 font-display text-2xl font-bold tracking-tight">Mes alertes</h1>
      <p className="mb-4 px-1 text-sm text-steel">Recevez les bankers du jour et les nouveaux pronostics sans ouvrir l&apos;application. Gratuit, désactivable à tout moment.</p>
      <AlertsManager comps={comps.ok ? comps.data.items : []} />
    </>
  );
}
