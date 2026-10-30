import "server-only";
import { cookies } from "next/headers";
import { validTz } from "./format";

const BACKEND = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

export type Result<T> = { ok: true; data: T; error: null } | { ok: false; data: null; error: string };

/** Appel serveur → backend FastAPI. L'URL et les jetons ne quittent jamais le serveur. */
export async function backend<T>(path: string, init?: RequestInit & { admin?: boolean }): Promise<Result<T>> {
  const headers = new Headers(init?.headers);
  if (init?.admin) headers.set("X-Admin-Token", process.env.BACKEND_ADMIN_TOKEN || "");
  if (init?.body) headers.set("Content-Type", "application/json");
  try {
    const res = await fetch(`${BACKEND}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(init?.admin ? 120000 : 60000),
    });
    if (!res.ok) {
      let detail = `${res.status}`;
      try {
        const j = await res.json();
        detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
      } catch {}
      return { ok: false, data: null, error: `Le service d'analyse a répondu ${detail}` };
    }
    return { ok: true, data: (await res.json()) as T, error: null };
  } catch {
    return {
      ok: false,
      data: null,
      error: "Le service d'analyse est injoignable pour le moment. S'il était en veille, il redémarre : réessayez dans une minute.",
    };
  }
}

export async function userTz(): Promise<string> {
  const c = await cookies();
  return validTz(c.get("sam_tz")?.value);
}

export const BACKEND_URL = BACKEND;
