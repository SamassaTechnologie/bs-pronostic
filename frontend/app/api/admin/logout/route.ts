import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

export async function POST() {
  const res = new NextResponse(null, { status: 303, headers: { Location: "/admin" } });
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
