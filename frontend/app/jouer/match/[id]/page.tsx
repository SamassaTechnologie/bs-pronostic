import { notFound } from "next/navigation";
import { userTz } from "@/lib/api";
import { JouerMatch } from "@/components/jouer/JouerMatch";

export const dynamic = "force-dynamic";
export const metadata = { title: "Jouer : marchés du match" };

export default async function JouerMatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return <JouerMatch id={Number(id)} tz={await userTz()} />;
}
