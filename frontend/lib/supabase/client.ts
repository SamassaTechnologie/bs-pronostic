"use client";
import { createBrowserClient } from "@supabase/ssr";
import { SUPABASE_KEY, SUPABASE_URL } from "./env";

let client: ReturnType<typeof createBrowserClient> | null = null;

export function supabaseBrowser() {
  if (!client) client = createBrowserClient(SUPABASE_URL, SUPABASE_KEY);
  return client;
}
