import Link from "next/link";
import { redirect } from "next/navigation";
import { userTz } from "@/lib/api";
import { currentMember } from "@/lib/supabase/server";
import { FollowList } from "@/components/Follows";
import { LogoutButton } from "@/components/AccountActions";
import { TimezoneSelect } from "@/components/TimezoneSelect";
import { Card, Section } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Mon compte" };

export default async function Compte() {
  const me = await currentMember();
  if (!me) redirect("/connexion?suite=/compte");
  const tz = await userTz();
  return (
    <>
      <h1 className="px-1 font-display text-2xl font-bold tracking-tight">Bonjour{me.name ? ` ${me.name}` : ""}</h1>
      <p className="px-1 text-sm text-steel">{me.email}</p>

      <Section title="Mes pronostics suivis">
        <FollowList tz={tz} />
      </Section>

      <Section title="Préférences">
        <Card className="p-4">
          <TimezoneSelect current={tz} />
        </Card>
      </Section>

      <div className="mt-7 grid gap-2.5">
        <Link href="/resultats" className="rounded-xl border border-line bg-white px-4 py-3.5 font-semibold">Résultats vérifiés</Link>
        <Link href="/methodologie" className="rounded-xl border border-line bg-white px-4 py-3.5 font-semibold">Comment sont calculées les probabilités</Link>
        <Link href="/plus" className="rounded-xl border border-line bg-white px-4 py-3.5 font-semibold">Sources de données et informations</Link>
        <Link href="/compte/mot-de-passe" className="rounded-xl border border-line bg-white px-4 py-3.5 font-semibold">Changer de mot de passe</Link>
        <LogoutButton />
      </div>
    </>
  );
}
