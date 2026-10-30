"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";

type Mode = "login" | "signup" | "reset";

const MESSAGES: Record<string, string> = {
  "Invalid login credentials": "E-mail ou mot de passe incorrect.",
  "Email not confirmed": "Confirmez d'abord votre adresse : ouvrez le lien reçu par e-mail.",
  "User already registered": "Un compte existe déjà avec cet e-mail. Connectez-vous.",
};

function translate(msg: string): string {
  if (MESSAGES[msg]) return MESSAGES[msg];
  if (/rate limit/i.test(msg)) return "Trop de tentatives. Patientez quelques minutes puis réessayez.";
  if (/password/i.test(msg) && /6|characters/i.test(msg)) return "Le mot de passe doit contenir au moins 8 caractères.";
  return msg;
}

const field = "mt-1 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-[15px]";

export function AuthForm({ next, initialMode }: { next: string; initialMode: Mode }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function submit(form: FormData) {
    setBusy(true);
    setError(null);
    setInfo(null);
    const sb = supabaseBrowser();
    const email = String(form.get("email") || "").trim();
    const password = String(form.get("password") || "");
    const origin = window.location.origin;
    try {
      if (mode === "login") {
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) throw error;
        router.replace(next);
        router.refresh();
      } else if (mode === "signup") {
        if (password.length < 8) throw new Error("Le mot de passe doit contenir au moins 8 caractères.");
        if (!form.get("adult")) throw new Error("L'accès est réservé aux personnes majeures.");
        const { data, error } = await sb.auth.signUp({
          email,
          password,
          options: {
            data: { name: String(form.get("name") || "").trim().slice(0, 60) },
            emailRedirectTo: `${origin}/auth/callback?suite=${encodeURIComponent(next)}`,
          },
        });
        if (error) throw error;
        if (data.session) {
          router.replace(next);
          router.refresh();
        } else {
          setInfo("Compte créé. Ouvrez le lien de confirmation envoyé à votre adresse e-mail pour l'activer.");
        }
      } else {
        const { error } = await sb.auth.resetPasswordForEmail(email, {
          redirectTo: `${origin}/auth/callback?suite=${encodeURIComponent("/compte/mot-de-passe")}`,
        });
        if (error) throw error;
        setInfo("Si un compte existe pour cette adresse, un lien de réinitialisation vient d'être envoyé.");
      }
    } catch (e) {
      setError(translate(e instanceof Error ? e.message : "Erreur inattendue"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-line bg-white p-4">
      {mode !== "reset" && (
        <div className="mb-4 grid grid-cols-2 gap-1 rounded-lg bg-mist p-1" role="tablist">
          {(["login", "signup"] as const).map((m) => (
            <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setError(null); setInfo(null); }}
              className={`rounded-md py-2 text-sm font-bold ${mode === m ? "bg-white text-night shadow-sm" : "text-steel"}`}>
              {m === "login" ? "Se connecter" : "Créer un compte"}
            </button>
          ))}
        </div>
      )}
      <form action={submit} className="space-y-3">
        {mode === "signup" && (
          <label className="block text-xs text-steel">
            Prénom ou pseudo
            <input name="name" autoComplete="nickname" maxLength={60} className={field} />
          </label>
        )}
        <label className="block text-xs text-steel">
          Adresse e-mail
          <input name="email" type="email" required autoComplete="email" inputMode="email" className={field} />
        </label>
        {mode !== "reset" && (
          <label className="block text-xs text-steel">
            Mot de passe{mode === "signup" ? " (8 caractères minimum)" : ""}
            <input name="password" type="password" required minLength={mode === "signup" ? 8 : 1}
              autoComplete={mode === "signup" ? "new-password" : "current-password"} className={field} />
          </label>
        )}
        {mode === "signup" && (
          <label className="flex items-start gap-2 text-sm text-ink">
            <input type="checkbox" name="adult" value="1" className="mt-1 h-4 w-4" />
            <span>J&apos;ai 18 ans ou plus et je comprends que les pronostics ne garantissent aucun gain.</span>
          </label>
        )}
        {error && <p className="rounded-lg bg-brick-soft px-3 py-2 text-sm text-brick" role="alert">{error}</p>}
        {info && <p className="rounded-lg bg-pitch-soft px-3 py-2 text-sm text-pitch-deep" role="status">{info}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-night py-3 text-sm font-bold text-white disabled:opacity-60">
          {busy ? "Un instant…" : mode === "login" ? "Se connecter" : mode === "signup" ? "Créer mon compte" : "Recevoir le lien"}
        </button>
      </form>
      <div className="mt-3 text-center text-sm">
        {mode === "reset" ? (
          <button type="button" onClick={() => setMode("login")} className="font-semibold text-sky">Retour à la connexion</button>
        ) : mode === "login" ? (
          <button type="button" onClick={() => setMode("reset")} className="font-semibold text-sky">Mot de passe oublié ?</button>
        ) : null}
      </div>
    </div>
  );
}
