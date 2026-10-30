import { redirect } from "next/navigation";
import { currentMember } from "@/lib/supabase/server";
import { authEnabled } from "@/lib/supabase/env";
import { AuthForm } from "@/components/AuthForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Connexion" };

function safeNext(v: string | undefined): string {
  return v && v.startsWith("/") && !v.startsWith("//") ? v : "/";
}

export default async function Connexion({ searchParams }: { searchParams: Promise<{ suite?: string; mode?: string; erreur?: string }> }) {
  const sp = await searchParams;
  const next = safeNext(sp.suite);
  if (await currentMember()) redirect(next);
  return (
    <div className="mx-auto max-w-sm pt-4">
      <h1 className="px-1 font-display text-2xl font-bold tracking-tight">
        {sp.mode === "inscription" ? "Créer un compte gratuit" : "Connexion"}
      </h1>
      <p className="mt-1 px-1 text-sm text-steel">
        L&apos;inscription est gratuite. Elle donne accès aux pronostics détaillés, aux combinés et au suivi de vos sélections.
      </p>
      {sp.erreur && (
        <p className="mt-3 rounded-lg bg-brick-soft px-3 py-2 text-sm text-brick">Le lien a expiré ou n&apos;est plus valide. Recommencez.</p>
      )}
      {authEnabled ? (
        <AuthForm next={next} initialMode={sp.mode === "inscription" ? "signup" : "login"} />
      ) : (
        <p className="mt-4 rounded-lg bg-amber-soft px-3 py-2 text-sm">Les comptes ne sont pas encore configurés sur ce serveur.</p>
      )}
    </div>
  );
}
