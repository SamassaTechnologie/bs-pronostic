import { redirect } from "next/navigation";

export default function Resultats() {
  redirect("/historique?selection=1");
}
