"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { flag } from "@/lib/flags";

type Result = {
  teams: { id: number; name: string; country: string; next: { id: number; kickoff: string; home: { name: string }; away: { name: string } } | null }[];
  competitions: { id: number; code: string; name: string; country: string }[];
  countries: string[];
};

/** Recherche globale (équipes, championnats, pays) dans l'en-tête. */
export function SearchBox() {
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 30);
  }, [open]);
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setRes(null);
      return;
    }
    setBusy(true);
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/proxy/search?q=${encodeURIComponent(term)}`, { signal: ctl.signal });
        if (r.ok) setRes(await r.json());
      } catch {}
      setBusy(false);
    }, 250);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [q]);

  const empty = res && !res.teams.length && !res.competitions.length && !res.countries.length;

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-label="Rechercher une équipe ou un championnat"
        className="flex h-10 w-10 items-center justify-center rounded-lg text-white/85 hover:bg-white/10 md:w-auto md:gap-2 md:px-3">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
        </svg>
        <span className="hidden text-sm font-semibold md:inline">Rechercher</span>
      </button>
      {open && (
        <div className="fixed inset-0 z-50 bg-night/60" onClick={() => setOpen(false)}>
          <div className="mx-auto mt-0 max-w-xl bg-white text-night md:mt-16 md:rounded-2xl" onClick={(e) => e.stopPropagation()}
            style={{ paddingTop: "env(safe-area-inset-top)" }}>
            <form className="flex items-center gap-2 border-b border-line px-3 py-2.5"
              onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 2) router.push(`/recherche?q=${encodeURIComponent(q.trim())}`); }}>
              <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-steel" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
              </svg>
              <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} type="search" enterKeyHint="search"
                placeholder="Équipe, championnat ou pays" aria-label="Rechercher"
                className="min-w-0 flex-1 bg-transparent py-1.5 text-[16px] text-night outline-none" />
              <button type="button" onClick={() => setOpen(false)} className="px-2 text-sm font-semibold text-sky">Fermer</button>
            </form>
            <div className="max-h-[70dvh] overflow-y-auto pb-2">
              {q.trim().length < 2 && <p className="px-4 py-4 text-sm text-steel">Tapez au moins 2 lettres, par exemple « Arsenal », « Liga » ou « France ».</p>}
              {busy && !res && <p className="px-4 py-4 text-sm text-steel">Recherche…</p>}
              {empty && <p className="px-4 py-4 text-sm text-steel">Aucun résultat pour « {q} » dans les championnats suivis.</p>}
              {res && res.competitions.length + res.countries.length > 0 && (
                <div className="py-1">
                  <div className="px-4 pt-2 text-xs text-steel">Championnats et pays</div>
                  {res.competitions.map((c) => (
                    <Link key={c.code} href={`/ligues/${c.code}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-mist">
                      <span className="text-xl" aria-hidden>{flag(c.country)}</span>
                      <span className="text-sm font-semibold">{c.name}</span>
                      <span className="text-xs text-steel">{c.country}</span>
                    </Link>
                  ))}
                  {res.countries.map((c) => (
                    <Link key={c} href={`/ligues#${encodeURIComponent(c)}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-mist">
                      <span className="text-xl" aria-hidden>{flag(c)}</span>
                      <span className="text-sm font-semibold">Tous les championnats : {c}</span>
                    </Link>
                  ))}
                </div>
              )}
              {res && res.teams.length > 0 && (
                <div className="py-1">
                  <div className="px-4 pt-2 text-xs text-steel">Équipes</div>
                  {res.teams.map((t) => (
                    <Link key={t.id} href={`/equipes/${t.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-mist">
                      <span className="text-xl" aria-hidden>{flag(t.country)}</span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold">{t.name}</span>
                        <span className="block truncate text-xs text-steel">
                          {t.next ? `Prochain match : ${t.next.home.name} – ${t.next.away.name}` : t.country}
                        </span>
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
