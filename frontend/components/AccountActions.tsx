"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";

export function LogoutButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={async () => {
        await supabaseBrowser().auth.signOut();
        router.replace("/");
        router.refresh();
      }}
      className="w-full rounded-xl border border-line bg-white px-4 py-3.5 text-left font-semibold text-brick"
    >
      Se déconnecter
    </button>
  );
}

export function NewPasswordForm() {
  const router = useRouter();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="mt-4 space-y-3 rounded-xl border border-line bg-white p-4"
      action={async (f) => {
        const pwd = String(f.get("password") || "");
        if (pwd.length < 8) return setMsg({ ok: false, text: "8 caractères minimum." });
        const { error } = await supabaseBrowser().auth.updateUser({ password: pwd });
        if (error) return setMsg({ ok: false, text: "Impossible de modifier le mot de passe : demandez un nouveau lien." });
        setMsg({ ok: true, text: "Mot de passe modifié." });
        setTimeout(() => router.replace("/compte"), 1200);
      }}
    >
      <label className="block text-xs text-steel">
        Nouveau mot de passe
        <input name="password" type="password" minLength={8} required autoComplete="new-password" className="mt-1 w-full rounded-lg border border-line px-3 py-2.5" />
      </label>
      {msg && <p className={`text-sm ${msg.ok ? "text-pitch-deep" : "text-brick"}`}>{msg.text}</p>}
      <button className="w-full rounded-lg bg-night py-3 text-sm font-bold text-white">Enregistrer</button>
    </form>
  );
}
