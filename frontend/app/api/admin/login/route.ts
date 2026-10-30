import { NextRequest, NextResponse } from "next/server";
import { createSessionValue, passwordMatches, SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/session";

// Redirection relative : fonctionne derrière n'importe quel domaine ou proxy.
const redirect = (location: string) => new NextResponse(null, { status: 303, headers: { Location: location } });

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const password = String(form.get("password") || "");
  if (!process.env.ADMIN_PASSWORD || !process.env.SESSION_SECRET) return redirect("/admin?erreur=config");
  if (!passwordMatches(password)) {
    await new Promise((r) => setTimeout(r, 800)); // ralentit les essais en série
    return redirect("/admin?erreur=mdp");
  }
  const res = redirect("/admin");
  res.cookies.set(SESSION_COOKIE, createSessionValue(), {
    httpOnly: true,
    secure: req.nextUrl.protocol === "https:",
    sameSite: "strict",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  return res;
}
