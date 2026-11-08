import type { MetadataRoute } from "next";
import { backend } from "@/lib/api";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://sam-prediction.vercel.app";
const STATS = ["btts", "plus-1-5", "plus-2-5", "plus-3-5", "moins-2-5", "mi-temps-but", "clean-sheet", "ne-marque-pas", "corners", "cartons"];

export const revalidate = 86400;

/** Pages publiques uniquement (les pages membres ne sont pas proposées aux moteurs de recherche). */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const base: { url: string; changeFrequency: "daily" | "weekly" | "monthly" | "yearly"; priority: number }[] = [
    { url: `${SITE}/`, changeFrequency: "daily", priority: 1 },
    { url: `${SITE}/bilan`, changeFrequency: "daily", priority: 0.9 },
    { url: `${SITE}/statistiques`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE}/ligues`, changeFrequency: "weekly", priority: 0.7 },
    { url: `${SITE}/resultats`, changeFrequency: "daily", priority: 0.6 },
    { url: `${SITE}/historique`, changeFrequency: "daily", priority: 0.6 },
    { url: `${SITE}/methodologie`, changeFrequency: "monthly", priority: 0.5 },
    { url: `${SITE}/jeu-responsable`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${SITE}/conditions`, changeFrequency: "yearly", priority: 0.2 },
    { url: `${SITE}/confidentialite`, changeFrequency: "yearly", priority: 0.2 },
    ...STATS.map((m) => ({ url: `${SITE}/statistiques?marche=${m}`, changeFrequency: "daily" as const, priority: 0.6 })),
  ];
  const pages: MetadataRoute.Sitemap = base.map((p) => ({ ...p, lastModified: now }));
  const comps = await backend<{ items: { code: string }[] }>("/api/competitions", { revalidate: 86400 });
  if (comps.ok) pages.push(...comps.data.items.map((c) => ({ url: `${SITE}/ligues/${c.code}`, lastModified: now, changeFrequency: "daily" as const, priority: 0.6 })));
  return pages;
}
