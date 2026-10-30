import { isAdmin } from "@/lib/session";
import { AdminPanel } from "@/components/AdminPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "Administration", robots: { index: false } };

const ERRORS: Record<string, string> = {
  mdp: "Mot de passe incorrect.",
  config: "Administration non configurée : définissez ADMIN_PASSWORD et SESSION_SECRET sur le serveur du site.",
};

export default async function Admin({ searchParams }: { searchParams: Promise<{ erreur?: string }> }) {
  const sp = await searchParams;
  if (!(await isAdmin())) {
    return (
      <div className="mx-auto max-w-sm pt-6">
        <h1 className="px-1 font-display text-2xl font-bold tracking-tight">Administration</h1>
        <p className="mt-1 px-1 text-sm text-steel">Accès réservé. Les clés API restent sur le serveur et ne sont jamais affichées.</p>
        <form method="post" action="/api/admin/login" className="mt-4 space-y-3 rounded-xl border border-line bg-white p-4">
          <label className="block text-xs text-steel">
            Mot de passe
            <input type="password" name="password" required autoComplete="current-password" className="mt-1 w-full rounded-lg border border-line px-3 py-2.5 text-sm" />
          </label>
          {sp.erreur && <p className="text-sm text-brick">{ERRORS[sp.erreur] ?? "Erreur de connexion."}</p>}
          <button className="w-full rounded-lg bg-night py-2.5 text-sm font-bold text-white">Se connecter</button>
        </form>
      </div>
    );
  }
  return <AdminPanel />;
}
