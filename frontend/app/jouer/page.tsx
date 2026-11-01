import { userTz } from "@/lib/api";
import { JouerBoard } from "@/components/jouer/JouerBoard";

export const dynamic = "force-dynamic";
export const metadata = { title: "Jouer" };

export default async function Jouer() {
  return <JouerBoard tz={await userTz()} />;
}
