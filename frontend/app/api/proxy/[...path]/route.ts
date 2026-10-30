import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/api";

const GET_ALLOWED = [/^meta$/, /^predictions$/, /^matches(\/\d+)?$/, /^history$/, /^performance$/, /^calibration$/];
const POST_ALLOWED = [/^combos\/generate$/, /^combos\/evaluate$/];

async function forward(req: NextRequest, path: string[], method: "GET" | "POST") {
  const p = path.join("/");
  const allowed = (method === "GET" ? GET_ALLOWED : POST_ALLOWED).some((r) => r.test(p));
  if (!allowed) return NextResponse.json({ detail: "Ressource non autorisée" }, { status: 404 });
  try {
    const res = await fetch(`${BACKEND_URL}/api/${p}${req.nextUrl.search}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: method === "POST" ? await req.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
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
