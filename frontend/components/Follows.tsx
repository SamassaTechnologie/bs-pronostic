"use client";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";
import { authEnabled } from "@/lib/supabase/env";
import type { PickCard } from "@/lib/types";
import { kickoffLabel, pct } from "@/lib/format";

type Follow = {
  id: number;
  match_id: number;
  market_key: string;
  market_label: string;
  match_label: string;
  competition: string | null;
  kickoff: string;
  probability: number;
};

type Ctx = {
  signedIn: boolean;
  ready: boolean;
  follows: Follow[];
  isFollowed: (matchId: number, key: string) => boolean;
  toggle: (p: PickCard) => Promise<void>;
  remove: (id: number) => Promise<void>;
};

const FollowCtx = createContext<Ctx | null>(null);

export function FollowsProvider({ signedIn, children }: { signedIn: boolean; children: React.ReactNode }) {
  const [follows, setFollows] = useState<Follow[]>([]);
  const [ready, setReady] = useState(!signedIn);

  useEffect(() => {
    if (!signedIn || !authEnabled) return;
    supabaseBrowser()
      .from("user_follows")
      .select("id,match_id,market_key,market_label,match_label,competition,kickoff,probability")
      .order("kickoff", { ascending: false })
      .limit(300)
      .then(({ data }: { data: Follow[] | null }) => {
        setFollows(data ?? []);
        setReady(true);
      });
  }, [signedIn]);

  const isFollowed = useCallback(
    (matchId: number, key: string) => follows.some((f) => f.match_id === matchId && f.market_key === key),
    [follows],
  );

  const remove = useCallback(async (id: number) => {
    await supabaseBrowser().from("user_follows").delete().eq("id", id);
    setFollows((fs) => fs.filter((f) => f.id !== id));
  }, []);

  const toggle = useCallback(
    async (p: PickCard) => {
      const existing = follows.find((f) => f.match_id === p.match.id && f.market_key === p.market_key);
      if (existing) return remove(existing.id);
      const row = {
        match_id: p.match.id,
        market_key: p.market_key,
        market_label: p.label,
        match_label: `${p.match.home.name} – ${p.match.away.name}`,
        competition: `${p.match.competition.name}, ${p.match.competition.country}`,
        kickoff: p.match.kickoff,
        probability: p.probability,
      };
      const { data } = await supabaseBrowser().from("user_follows").insert(row).select().single();
      if (data) setFollows((fs) => [data as Follow, ...fs]);
    },
    [follows, remove],
  );

  const value = useMemo(() => ({ signedIn, ready, follows, isFollowed, toggle, remove }), [signedIn, ready, follows, isFollowed, toggle, remove]);
  return <FollowCtx.Provider value={value}>{children}</FollowCtx.Provider>;
}

function useFollows(): Ctx | null {
  return useContext(FollowCtx);
}

function shareText(p: PickCard): string {
  return `${p.match.home.name} – ${p.match.away.name} (${p.match.competition.name})\n${p.label} : ${Math.round(p.probability * 100)} % selon SAM-Prédiction.\nL'analyse avant le pronostic. Aucune garantie de gain, 18+.`;
}

export function PickActions({ pick }: { pick: PickCard }) {
  const ctx = useFollows();
  const [copied, setCopied] = useState(false);
  const followed = ctx?.isFollowed(pick.match.id, pick.market_key) ?? false;

  async function share() {
    const url = `${window.location.origin}/matchs/${pick.match.id}`;
    const text = shareText(pick);
    if (navigator.share) {
      try {
        await navigator.share({ title: "SAM-Prédiction", text, url });
        return;
      } catch {
        return;
      }
    }
    try {
      await navigator.clipboard.writeText(`${text}\n${url}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.open(`https://wa.me/?text=${encodeURIComponent(`${text}\n${url}`)}`, "_blank", "noopener");
    }
  }

  return (
    <div className="flex items-center gap-2 border-t border-line px-4 py-2.5">
      {ctx?.signedIn ? (
        <button type="button" onClick={() => ctx.toggle(pick)} disabled={!ctx.ready} aria-pressed={followed}
          className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold ${followed ? "bg-pitch-soft text-pitch-deep" : "bg-mist text-night"}`}>
          {followed ? "Suivi" : "Suivre"}
        </button>
      ) : (
        <Link href="/connexion?mode=inscription" className="flex-1 rounded-lg bg-mist px-3 py-2 text-center text-sm font-semibold text-night">
          Suivre
        </Link>
      )}
      <button type="button" onClick={share} className="flex-1 rounded-lg bg-mist px-3 py-2 text-sm font-semibold text-night">
        {copied ? "Copié" : "Partager"}
      </button>
    </div>
  );
}

export function FollowList({ tz }: { tz: string }) {
  const ctx = useFollows();
  if (!ctx || !ctx.ready) return <p className="text-sm text-steel">Chargement…</p>;
  if (!ctx.follows.length)
    return (
      <p className="rounded-xl border border-dashed border-line bg-white/60 p-4 text-center text-sm text-steel">
        Aucun pronostic suivi. Touchez « Suivre » sur un pronostic pour le retrouver ici.
      </p>
    );
  return (
    <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
      {ctx.follows.map((f) => (
        <div key={f.id} className="flex items-center gap-3 px-4 py-3">
          <Link href={`/matchs/${f.match_id}`} className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">{f.match_label}</div>
            <div className="truncate text-xs text-steel">
              {f.market_label}, {pct(f.probability)}, {kickoffLabel(f.kickoff, tz)}
            </div>
          </Link>
          <button type="button" onClick={() => ctx.remove(f.id)} className="shrink-0 text-xs font-semibold text-brick">
            Retirer
          </button>
        </div>
      ))}
    </div>
  );
}
