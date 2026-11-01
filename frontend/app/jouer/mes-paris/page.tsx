import { userTz } from "@/lib/api";
import { JouerMesParis } from "@/components/jouer/JouerMesParis";

export const dynamic = "force-dynamic";
export const metadata = { title: "Mes paris" };

export default async function MesParisPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const sp = await searchParams;
  return <JouerMesParis tz={await userTz()} justPlaced={sp.ok === "1"} />;
}
