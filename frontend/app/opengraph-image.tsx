import { ImageResponse } from "next/og";
import { OG_SIZE, OgFrame } from "@/lib/og";

export const alt = "SAM-Prédiction : probabilités football calculées sur données réelles";
export const size = OG_SIZE;
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <OgFrame kicker="Pronostics football" title="Probabilités calculées sur données réelles, bilan public vérifié."
        footer="Bankers du jour · Sélection SAM · Statistiques · Direct">
        <div style={{ display: "flex", gap: 20, fontSize: 26, color: "rgba(255,255,255,0.85)" }}>
          <div style={{ display: "flex" }}>Aucune donnée inventée</div>
          <div style={{ display: "flex" }}>·</div>
          <div style={{ display: "flex" }}>Chaque pronostic figé avant le match</div>
        </div>
      </OgFrame>
    ),
    size,
  );
}
