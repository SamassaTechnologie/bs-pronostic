"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { flag } from "@/lib/flags";

type Team = { id: number; name: string; country: string };

/** Choix d'une équipe du comparateur (recherche avec suggestions). */
export function TeamPicker({ slot, current }: { slot: "a" | "b"; current: Team | null }) {
  const router = useRouter();
  const sp = useSearchParams();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Team[]>([]);
  const [editing, setEditing] = useState(!current);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setItems([]); return; }
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/proxy/search?q=${encodeURIComponent(term)}`, { signal: ctl.signal });
        if (r.ok) setItems(((await r.json()).teams || []).slice(0, 8));
      } catch {}
    }, 250);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q]);

  function pick(t: Team) {
    const u = new URLSearchParams(sp.toString());
    u.set(slot, String(t.id));
    setEditing(false);
    setQ("");
    router.push(`/comparer?${u}`, { scroll: false });
  }

  if (current && !editing) {
    return (
      <button type="button" onClick={() => setEditing(true)}
        className="flex w-full min-w-0 items-center gap-2 rounded-xl border border-line bg-white px-3 py-2.5 text-left">
        <span aria-hidden>{flag(current.country)}</span>
        <span className="min-w-0 flex-1 truncate font-display text-[15px] font-bold">{current.name}</span>
        <span className="text-[11px] font-semibold text-sky">Changer</span>
      </button>
    );
  }
  return (
    <div className="relative min-w-0">
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} autoFocus={Boolean(current)}
        placeholder={slot === "a" ? "Équipe 1" : "Équipe 2"} aria-label={slot === "a" ? "Première équipe" : "Deuxième équipe"}
        className="w-full rounded-xl border border-line bg-white px-3 py-2.5 text-[15px]" />
      {items.length > 0 && (
        <ul className="absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded-xl border border-line bg-white shadow-lg">
          {items.map((t) => (
            <li key={t.id}>
              <button type="button" onClick={() => pick(t)} className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm hover:bg-mist">
                <span aria-hidden>{flag(t.country)}</span>
                <span className="min-w-0 flex-1 truncate font-semibold">{t.name}</span>
                <span className="text-[11px] text-steel">{t.country}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
