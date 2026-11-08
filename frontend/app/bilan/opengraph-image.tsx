import { ImageResponse } from "next/og";
import { backend } from "@/lib/api";
import { AMBER, OG_SIZE, OgFrame, PITCH } from "@/lib/og";

export const alt = "Les bankers du jour et le bilan vérifié de SAM-Prédiction";
export const size = OG_SIZE;
export const contentType = "image/png";
export const revalidate = 600;

type Pick = { label: string; probability: number; match: { kickoff: string; home: { name: string }; away: { name: string } } };
type Dash = { bankers?: Pick[]; banker_performance?: { n: number; won: number } };
const TZ = "Africa/Bamako";

const pct = (p: number) => `${Math.round(p * 100)} %`;
const hour = (iso: string) => new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
const day = (iso: string) => new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date(iso));

/** Aperçu partagé avec le lien « Notre bilan » : les bankers du jour (données réelles), sinon le bilan seul. */
export default async function Image() {
  const r = await backend<Dash>(`/api/dashboard?tz=${encodeURIComponent(TZ)}`, { revalidate: 600 });
  const all = r.ok ? r.data.bankers ?? [] : [];
  const first = all[0] ? day(all[0].match.kickoff) : null;
  const list = all.filter((p) => day(p.match.kickoff) === first).slice(0, 3);
  const perf = r.ok ? r.data.banker_performance : undefined;
  const today = first === day(new Date().toISOString());
  return new ImageResponse(
    (
      <OgFrame kicker={list.length ? (today ? "Les bankers du jour" : "Les bankers de demain") : "Notre bilan"}
        title={list.length ? "Les pronostics les plus solides" : "Chaque pronostic figé avant le match"}
        footer={perf?.n ? `Bilan des bankers : ${perf.won} gagnés sur ${perf.n} · sam-prediction.vercel.app/bilan` : "sam-prediction.vercel.app/bilan"}>
        {list.map((p, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 0", borderTop: i ? "1px solid rgba(255,255,255,0.15)" : "none" }}>
            <div style={{ display: "flex", flexDirection: "column", maxWidth: 880 }}>
              <div style={{ fontSize: 30, fontWeight: 700 }}>{`${p.match.home.name} – ${p.match.away.name}`}</div>
              <div style={{ fontSize: 24, color: AMBER }}>{`${hour(p.match.kickoff)} · ${p.label}`}</div>
            </div>
            <div style={{ fontSize: 44, fontWeight: 800, color: PITCH }}>{pct(p.probability)}</div>
          </div>
        ))}
      </OgFrame>
    ),
    size,
  );
}
