/** Grands championnats : même liste et même ordre que le serveur (backend/app/popular.py). */
export const POPULAR = ["UCL", "ENG1", "ESP1", "ITA1", "GER1", "FRA1", "UEL", "UECL", "POR1", "NED1", "CAF1", "INT"] as const;

export function popularRank(code: string | null | undefined): number {
  const i = POPULAR.indexOf((code ?? "") as (typeof POPULAR)[number]);
  return i < 0 ? 100 : i;
}

export function isPopular(code: string | null | undefined): boolean {
  return popularRank(code) < 100;
}
