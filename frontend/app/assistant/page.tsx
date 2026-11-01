import { backend, userTz } from "@/lib/api";
import { Assistant } from "@/components/Assistant";

export const dynamic = "force-dynamic";
export const metadata = { title: "Assistant IA" };

type Detail = { match: { id: number; home: { name: string }; away: { name: string } } };

export default async function AssistantPage({ searchParams }: { searchParams: Promise<{ match?: string }> }) {
  const sp = await searchParams;
  const tz = await userTz();
  let match: { id: number; label: string } | null = null;
  if (sp.match && /^\d+$/.test(sp.match)) {
    const r = await backend<Detail>(`/api/matches/${sp.match}`);
    if (r.ok) match = { id: r.data.match.id, label: `${r.data.match.home.name} – ${r.data.match.away.name}` };
  }
  return <Assistant tz={tz} match={match} />;
}
