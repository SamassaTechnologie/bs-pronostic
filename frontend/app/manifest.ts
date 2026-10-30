import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SAM-Prédiction",
    short_name: "SAM-Prédiction",
    description: "L'analyse avant le pronostic.",
    lang: "fr",
    start_url: "/",
    display: "standalone",
    background_color: "#0b1d3a",
    theme_color: "#0b1d3a",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
