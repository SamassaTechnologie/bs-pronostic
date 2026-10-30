import "server-only";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { cache } from "react";
import { authEnabled, SUPABASE_KEY, SUPABASE_URL } from "./env";

export async function supabaseServer() {
  const store = await cookies();
  return createServerClient(SUPABASE_URL, SUPABASE_KEY, {
    cookies: {
      getAll: () => store.getAll(),
      setAll: (list) => {
        try {
          list.forEach(({ name, value, options }) => store.set(name, value, options));
        } catch {
          // Appelé depuis un composant serveur : le rafraîchissement est fait par proxy.ts.
        }
      },
    },
  });
}

export type Member = { id: string; email: string | null; name: string | null } | null;

/** Utilisateur connecté (vérifié auprès de Supabase), ou null. Mis en cache pour la durée d'une requête. */
export const currentMember = cache(async (): Promise<Member> => {
  if (!authEnabled) return null;
  try {
    const sb = await supabaseServer();
    const { data } = await sb.auth.getUser();
    if (!data.user) return null;
    const meta = (data.user.user_metadata || {}) as { name?: string };
    return { id: data.user.id, email: data.user.email ?? null, name: meta.name ?? null };
  } catch {
    return null;
  }
});
