import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/api";
import { currentMember } from "@/lib/supabase/server";
import { authEnabled } from "@/lib/supabase/env";

export const maxDuration = 120;

const MEMBERS_ONLY = [/^jeu\//, /^assistant$/, /^live$/, /^predictions$/, /^matches\/\d+$/, /^matches\/\d+\/ai$/, /^combos\//];

const GET_ALLOWED = [/^jeu\/(board|mes-paris|matchs\/\d+)$/, /^matches\/\d+\/(live|insights|ai)$/, /^search$/, /^competitions$/, /^competitions\/[A-Za-z0-9_-]+$/, /^teams\/\d+$/, /^live$/, /^recent-results$/, /^meta$/, /^predictions$/, /^matches(\/\d+)?$/, /^history$/, /^performance$/, /^calibration$/];
const POST_ALLOWED = [/^combos\/generate$/, /^combos\/evaluate$/, /^combos\/target$/, /^assistant$/, /^jeu\/(paris|devis)$/];

async function forward(req: NextRequest, path: string[], method: "GET" | "POST") {
  const p = path.join("/");
  const allowed = (method === "GET" ? GET_ALLOWED : POST_ALLOWED).some((r) => r.test(p));
  if (!allowed) return NextResponse.json({ detail: "Ressource non autorisée" }, { status: 404 });
  const member = authEnabled && MEMBERS_ONLY.some((r) => r.test(p)) ? await currentMember() : null;
  if (authEnabled && MEMBERS_ONLY.some((r) => r.test(p)) && !member) {
    return NextResponse.json({ detail: "Connectez-vous pour accéder aux pronostics." }, { status: 401 });
  }
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (p === "assistant") {
    headers["X-Assistant-Token"] = process.env.ASSISTANT_TOKEN || "";
    if (member) headers["X-Member-Id"] = member.id;
  }
  if (p.startsWith("jeu/")) {
    // Section Jouer : identité du membre ajoutée ici, côté serveur (jamais fournie par le navigateur).
    headers["X-App-Token"] = process.env.ASSISTANT_TOKEN || "";
    if (member) {
      headers["X-Member-Id"] = member.id;
      headers["X-Member-Name"] = encodeURIComponent(member.name || `Membre ${member.id.slice(0, 4).toUpperCase()}`);
    } else if (!authEnabled) {
      headers["X-Member-Id"] = "local-demo";
    }
  }
  try {
    const res = await fetch(`${BACKEND_URL}/api/${p}${req.nextUrl.search}`, {
      method,
      headers,
      body: method === "POST" ? await req.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(p === "assistant" ? 115000 : 60000),
    });
    return new NextResponse(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return NextResponse.json({ detail: "Service d'analyse injoignable, réessayez dans une minute." }, { status: 503 });
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path, "GET");
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path, "POST");
}
