import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/api";
import { isAdmin } from "@/lib/session";

async function forward(req: NextRequest, path: string[], method: string) {
  if (!(await isAdmin())) return NextResponse.json({ detail: "Session expirée : reconnectez-vous." }, { status: 401 });
  const p = path.join("/");
  if (!/^[a-z0-9_\-/]+$/i.test(p)) return NextResponse.json({ detail: "Chemin invalide" }, { status: 400 });
  try {
    const res = await fetch(`${BACKEND_URL}/api/admin/${p}${req.nextUrl.search}`, {
      method,
      headers: { "Content-Type": "application/json", "X-Admin-Token": process.env.BACKEND_ADMIN_TOKEN || "" },
      body: method === "GET" ? undefined : await req.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(120000),
    });
    return new NextResponse(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return NextResponse.json({ detail: "Service d'analyse injoignable." }, { status: 503 });
  }
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path, "GET"); }
export async function POST(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path, "POST"); }
export async function PUT(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path, "PUT"); }
