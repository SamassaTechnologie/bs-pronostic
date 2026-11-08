/* eslint-disable @next/next/no-img-element */
import type { ReactNode } from "react";

export const OG_SIZE = { width: 1200, height: 630 };
export const NIGHT = "#0b1d3a";
export const PITCH = "#12a150";
export const AMBER = "#e8a317";

/** Cadre commun des images d'aperçu (WhatsApp, Facebook, X…). */
export function OgFrame({ kicker, title, children, footer }: { kicker: string; title: string; children?: ReactNode; footer?: string }) {
  return (
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", background: NIGHT, color: "white", padding: "56px 64px", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ width: 56, height: 56, borderRadius: 14, background: PITCH, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 30, fontWeight: 800 }}>S</div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 30, fontWeight: 800 }}>SAM-Prédiction</div>
          <div style={{ fontSize: 20, color: "rgba(255,255,255,0.65)" }}>L&apos;analyse avant le pronostic.</div>
        </div>
      </div>
      <div style={{ marginTop: 40, fontSize: 24, fontWeight: 800, color: AMBER, textTransform: "uppercase", letterSpacing: 2 }}>{kicker}</div>
      <div style={{ marginTop: 8, fontSize: 52, fontWeight: 800, lineHeight: 1.1 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", flex: 1, marginTop: 28 }}>{children}</div>
      {footer && <div style={{ fontSize: 20, color: "rgba(255,255,255,0.6)" }}>{footer}</div>}
    </div>
  );
}
