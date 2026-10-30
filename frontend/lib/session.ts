import "server-only";
import { createHmac, timingSafeEqual } from "crypto";
import { cookies } from "next/headers";

export const SESSION_COOKIE = "sam_admin";
const MAX_AGE = 60 * 60 * 12; // 12 h

function secret(): string {
  const s = process.env.SESSION_SECRET || "";
  if (s.length < 16) throw new Error("SESSION_SECRET manquant ou trop court (16 caractères minimum)");
  return s;
}

function sign(payload: string): string {
  return createHmac("sha256", secret()).update(payload).digest("base64url");
}

export function createSessionValue(): string {
  const exp = Math.floor(Date.now() / 1000) + MAX_AGE;
  const payload = `admin.${exp}`;
  return `${payload}.${sign(payload)}`;
}

export function verifySessionValue(value: string | undefined): boolean {
  if (!value) return false;
  const parts = value.split(".");
  if (parts.length !== 3) return false;
  const payload = `${parts[0]}.${parts[1]}`;
  let expected: string;
  try {
    expected = sign(payload);
  } catch {
    return false;
  }
  const a = Buffer.from(parts[2]);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return false;
  return Number(parts[1]) > Date.now() / 1000;
}

export function passwordMatches(input: string): boolean {
  const expected = process.env.ADMIN_PASSWORD || "";
  if (!expected) return false;
  const a = createHmac("sha256", "cmp").update(input).digest();
  const b = createHmac("sha256", "cmp").update(expected).digest();
  return timingSafeEqual(a, b);
}

export async function isAdmin(): Promise<boolean> {
  const c = await cookies();
  return verifySessionValue(c.get(SESSION_COOKIE)?.value);
}

export const SESSION_MAX_AGE = MAX_AGE;
