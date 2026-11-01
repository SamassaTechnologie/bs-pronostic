"use client";
import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";
import type { Combo } from "@/lib/types";
import { kickoffLabel } from "@/lib/format";
import { ComboView } from "./ComboBuilder";

type MatchRef = { id: number; home: string; away: string; competition: string; kickoff: string };
type Msg = {
  role: "user" | "assistant";
  text: string;
  combos?: Record<string, Combo>;
  matches?: Record<string, MatchRef>;
  error?: boolean;
  meta?: string;
};

const GENERAL = [
  "Propose-moi le combiné le plus sûr pour une cote 2",
  "Analyse tous les marchés et donne-moi les 3 meilleures sélections d'aujourd'hui",
  "Un combiné cote 3 avec des corners ou des cartons",
  "Quels matchs vaut-il mieux éviter ?",
  "Quel est le bilan réel des pronostics SAM ?",
];
const STORE = "sam-assistant-v1";

function inline(text: string, matches: Record<string, MatchRef> | undefined, tz: string) {
  // **gras** et [[M:id]] → lien vers la fiche
  const parts = text.split(/(\*\*[^*]+\*\*|\[\[M:\d+\]\])/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    const m = p.match(/^\[\[M:(\d+)\]\]$/);
    if (m) {
      const info = matches?.[m[1]];
      return info ? (
        <Link key={i} href={`/matchs/${info.id}`} className="mx-0.5 inline-flex max-w-full items-center gap-1 rounded-md bg-mist px-1.5 py-0.5 text-[13px] font-semibold text-sky">
          <span className="truncate">{info.home} – {info.away}</span>
          <span className="shrink-0 font-normal text-steel">{kickoffLabel(info.kickoff, tz)}</span>
        </Link>
      ) : null;
    }
    return <Fragment key={i}>{p}</Fragment>;
  });
}

function Answer({ msg, tz }: { msg: Msg; tz: string }) {
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (k: number) => {
    if (bullets.length) {
      blocks.push(
        <ul key={`u${k}`} className="space-y-1.5">
          {bullets.map((b, i) => (
            <li key={i} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-pitch" aria-hidden /><span className="min-w-0">{inline(b, msg.matches, tz)}</span></li>
          ))}
        </ul>,
      );
      bullets = [];
    }
  };
  msg.text.split("\n").forEach((raw, k) => {
    const line = raw.trim();
    const combo = line.match(/^\[\[(C\d+)\]\]$/);
    if (combo) {
      flush(k);
      const c = msg.combos?.[combo[1]];
      if (c) blocks.push(<div key={`c${k}`} className="my-1"><ComboView c={c} tz={tz} title={`Combiné ${combo[1].slice(1)} : ${c.n_legs ?? c.legs.length} matchs`} /></div>);
      return;
    }
    const b = line.match(/^(?:-|\d+\.)\s+(.*)$/);
    if (b) { bullets.push(b[1]); return; }
    flush(k);
    if (line) blocks.push(<p key={`p${k}`}>{inline(line.replace(/\[\[C\d+\]\]/g, ""), msg.matches, tz)}</p>);
  });
  flush(9999);
  return <div className="space-y-2.5 text-[15px] leading-relaxed text-ink">{blocks}</div>;
}

export function Assistant({ tz, match }: { tz: string; match?: { id: number; label: string } | null }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const end = useRef<HTMLDivElement>(null);
  const storeKey = `${STORE}-${match?.id ?? "general"}`;

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(storeKey);
      if (saved) setMsgs(JSON.parse(saved));
    } catch {}
  }, [storeKey]);
  useEffect(() => {
    try { sessionStorage.setItem(storeKey, JSON.stringify(msgs.slice(-20))); } catch {}
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, storeKey]);
  useEffect(() => {
    if (!busy) return;
    setStep(0);
    const t = setInterval(() => setStep((s) => Math.min(s + 1, 3)), 4000);
    return () => clearInterval(t);
  }, [busy]);

  const suggestions = match
    ? [`Analyse ce match en détail`, `Quel est le marché le plus sûr pour ce match ?`, `Combine ce match avec un autre pour une cote 2`, `Y a-t-il un pari à cote intéressante sur ce match ?`]
    : GENERAL;

  async function send(text: string) {
    const question = text.trim();
    if (question.length < 2 || busy) return;
    const history = msgs.filter((m) => !m.error).slice(-8).map((m) => ({ role: m.role, text: m.text.slice(0, 3500) }));
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setQ("");
    setBusy(true);
    try {
      const r = await fetch("/api/proxy/assistant", { method: "POST", body: JSON.stringify({ question, history, match_id: match?.id ?? null }) });
      const d = await r.json();
      if (!r.ok || d.status !== "ok") {
        setMsgs((m) => [...m, { role: "assistant", text: d.message || d.detail || "Service indisponible, réessayez.", error: true }]);
      } else {
        setMsgs((m) => [...m, {
          role: "assistant", text: d.answer, combos: d.combos, matches: d.matches,
          meta: `${d.provider}${typeof d.remaining_today === "number" ? ` · ${d.remaining_today} question(s) restante(s) aujourd'hui` : ""}`,
        }]);
      }
    } catch {
      setMsgs((m) => [...m, { role: "assistant", text: "Connexion impossible, réessayez dans un instant.", error: true }]);
    } finally {
      setBusy(false);
    }
  }

  const STEPS = ["Lecture de la question…", "Consultation du moteur SAM…", "Calcul des combinaisons…", "Rédaction de la réponse…"];

  return (
    <div className="flex min-h-[60dvh] flex-col">
      {match && (
        <div className="mb-3 flex items-center justify-between gap-2 rounded-xl border border-line bg-white px-3 py-2 text-sm">
          <span className="min-w-0 truncate">À propos de <Link href={`/matchs/${match.id}`} className="font-semibold text-sky">{match.label}</Link></span>
          <Link href="/assistant" className="shrink-0 text-xs font-semibold text-steel">Question générale</Link>
        </div>
      )}

      {msgs.length === 0 && (
        <div className="rounded-2xl bg-night px-5 py-5 text-white">
          <div className="text-[11px] font-bold uppercase tracking-wide text-white/70">Assistant IA</div>
          <h1 className="mt-1 font-display text-xl font-bold leading-snug">Posez votre question, l&apos;IA interroge le moteur SAM pour vous.</h1>
          <p className="mt-2 text-sm text-white/80">
            Combinés, comparaison de tous les marchés, analyse d&apos;un match : chaque probabilité et chaque combiné affichés sont
            calculés par SAM, jamais inventés par l&apos;IA.
          </p>
        </div>
      )}

      <div className="mt-3 flex-1 space-y-3">
        {msgs.map((m, i) => m.role === "user" ? (
          <div key={i} className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-night px-4 py-2.5 text-[15px] text-white">{m.text}</div>
        ) : (
          <div key={i} className={`rounded-2xl rounded-bl-md border px-4 py-3 ${m.error ? "border-amber/40 bg-amber-soft" : "border-line bg-white"}`}>
            {m.error ? <p className="text-sm text-ink">{m.text}</p> : <Answer msg={m} tz={tz} />}
            {m.meta && <div className="mt-2 text-[11px] text-steel">Réponse IA ({m.meta}). Aucune garantie de gain.</div>}
          </div>
        ))}
        {busy && (
          <div className="rounded-2xl rounded-bl-md border border-line bg-white px-4 py-3" aria-live="polite">
            <div className="flex items-center gap-2 text-sm font-semibold text-night">
              <span className="h-2 w-2 animate-pulse rounded-full bg-pitch" aria-hidden />{STEPS[step]}
            </div>
            <p className="mt-1 text-xs text-steel">10 à 40 secondes selon la question.</p>
          </div>
        )}
        <div ref={end} />
      </div>

      {!busy && (
        <div className={`mt-3 flex gap-2 pb-1 ${msgs.length === 0 ? "flex-col" : "overflow-x-auto [scrollbar-width:none]"}`}>
          {msgs.length === 0 && <div className="px-1 text-xs font-semibold text-steel">Exemples de questions</div>}
          {suggestions.map((s) => (
            <button key={s} type="button" onClick={() => send(s)}
              className={`rounded-full border border-line bg-white px-3 py-1.5 text-[13px] font-semibold text-night ${msgs.length === 0 ? "text-left" : "shrink-0"}`}>
              {s}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={(e) => { e.preventDefault(); send(q); }}
        className="sticky bottom-[calc(env(safe-area-inset-bottom)+64px)] z-10 mt-3 flex items-end gap-2 rounded-2xl border border-line bg-white p-2 shadow-sm md:bottom-4">
        <textarea value={q} onChange={(e) => setQ(e.target.value)} rows={1} maxLength={600}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }}
          placeholder="Votre question…"
          aria-label="Votre question" className="max-h-32 min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-[16px] text-night outline-none" />
        <button type="submit" disabled={busy || q.trim().length < 2} className="h-10 shrink-0 rounded-xl bg-pitch px-4 text-sm font-bold text-white disabled:opacity-50">
          Envoyer
        </button>
      </form>
      {msgs.length > 0 && !busy && (
        <button type="button" onClick={() => setMsgs([])} className="mt-2 self-center text-xs font-semibold text-steel">Nouvelle conversation</button>
      )}
    </div>
  );
}
