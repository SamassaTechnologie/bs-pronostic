export const DEFAULT_TZ = "Africa/Bamako";

export const TIMEZONES: { value: string; label: string }[] = [
  { value: "Africa/Bamako", label: "Mali — Bamako (GMT)" },
  { value: "Africa/Dakar", label: "Sénégal — Dakar (GMT)" },
  { value: "Africa/Abidjan", label: "Côte d'Ivoire — Abidjan (GMT)" },
  { value: "Africa/Ouagadougou", label: "Burkina Faso — Ouagadougou (GMT)" },
  { value: "Africa/Conakry", label: "Guinée — Conakry (GMT)" },
  { value: "Africa/Niamey", label: "Niger — Niamey (GMT+1)" },
  { value: "Africa/Lagos", label: "Afrique de l'Ouest (GMT+1)" },
  { value: "Africa/Casablanca", label: "Maroc — Casablanca" },
  { value: "Europe/London", label: "Royaume-Uni — Londres" },
  { value: "Europe/Paris", label: "France — Paris" },
  { value: "America/New_York", label: "États-Unis — New York" },
  { value: "UTC", label: "UTC" },
];

export function validTz(tz: string | undefined): string {
  if (!tz) return DEFAULT_TZ;
  try {
    new Intl.DateTimeFormat("fr-FR", { timeZone: tz });
    return tz;
  } catch {
    return DEFAULT_TZ;
  }
}

export function pct(p: number | null | undefined, digits = 0): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(digits).replace(".", ",")} %`;
}

export function num(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toFixed(digits).replace(".", ",");
}

export function signedPct(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  const v = Math.round(x * 100);
  return `${v > 0 ? "+" : ""}${v} %`;
}

export function time(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("fr-FR", { timeZone: tz, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function dayLabel(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("fr-FR", { timeZone: tz, weekday: "short", day: "numeric", month: "short" }).format(new Date(iso));
}

export function dateTime(iso: string | null | undefined, tz: string): string {
  if (!iso) return "jamais";
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: tz, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

export function kickoffLabel(iso: string, tz: string): string {
  const d = new Date(iso);
  const fmt = (x: Date) => new Intl.DateTimeFormat("fr-CA", { timeZone: tz }).format(x);
  const today = fmt(new Date());
  const tomorrow = fmt(new Date(Date.now() + 86400000));
  const day = fmt(d);
  const t = time(iso, tz);
  if (day === today) return `Aujourd'hui, ${t}`;
  if (day === tomorrow) return `Demain, ${t}`;
  return `${dayLabel(iso, tz)}, ${t}`;
}

export function hoursSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3600000;
}

export const RESULT_LABEL: Record<string, string> = {
  won: "Gagné",
  lost: "Perdu",
  pending: "En attente",
  void: "Annulé",
  unverifiable: "Non vérifiable",
};
