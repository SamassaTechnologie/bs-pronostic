import Link from "next/link";
import { userTz } from "@/lib/api";
import { LiveBoard } from "@/components/LiveBoard";

export const dynamic = "force-dynamic";
export const metadata = { title: "En direct" };

export default async function Direct() {
  const tz = await userTz();
  return (
    <>
      <div className="mb-3 flex items-start justify-between gap-3 px-1">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">En direct</h1>
          <p className="text-sm text-steel">Les matchs en cours et l&apos;état de vos pronostics, minute par minute.</p>
        </div>
        <Link href="/matchs" className="shrink-0 rounded-lg border border-line bg-white px-3 py-1.5 text-[13px] font-bold text-night">Calendrier</Link>
      </div>
      <LiveBoard tz={tz} />
    </>
  );
}
