import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const MEMBERS_ONLY = ["/pronostics", "/matchs", "/combines", "/compte", "/direct", "/assistant", "/jouer"];

/** Rafraîchit la session Supabase et protège les pages réservées aux membres. */
export async function proxy(request: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  let response = NextResponse.next({ request });
  if (!url || !key) return response;
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (list, headers) => {
        list.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        list.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
        Object.entries(headers ?? {}).forEach(([k, v]) => response.headers.set(k, v as string));
      },
    },
  });
  const path = request.nextUrl.pathname;
  const gated = MEMBERS_ONLY.some((p) => path === p || path.startsWith(`${p}/`));
  // Vérification réseau uniquement là où elle sert (pages membres et accueil) : navigation plus rapide.
  if (!gated && path !== "/") return response;
  const { data } = await supabase.auth.getUser();
  if (!data.user && MEMBERS_ONLY.some((p) => path === p || path.startsWith(`${p}/`))) {
    const login = request.nextUrl.clone();
    login.pathname = "/connexion";
    login.search = `?suite=${encodeURIComponent(path + request.nextUrl.search)}`;
    return NextResponse.redirect(login);
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icons|sw.js|offline.html|manifest.webmanifest|icon.png|api/admin).*)"],
};
