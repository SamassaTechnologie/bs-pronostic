import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabase/server";

/** Retour des liens envoyés par e-mail (confirmation d'inscription, nouveau mot de passe). */
export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code");
  const suite = req.nextUrl.searchParams.get("suite") || "/";
  const next = suite.startsWith("/") && !suite.startsWith("//") ? suite : "/";
  if (code) {
    const sb = await supabaseServer();
    const { error } = await sb.auth.exchangeCodeForSession(code);
    if (!error) return new NextResponse(null, { status: 303, headers: { Location: next } });
  }
  return new NextResponse(null, { status: 303, headers: { Location: "/connexion?erreur=lien" } });
}
