import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";
import { DesktopNav, Logo, MobileTabs } from "@/components/Nav";
import { SwRegister } from "@/components/SwRegister";

export const metadata: Metadata = {
  title: { default: "SAM-Prédiction", template: "%s · SAM-Prédiction" },
  description: "L'analyse avant le pronostic. Probabilités football calculées sur données réelles.",
  applicationName: "SAM-Prédiction",
  appleWebApp: { capable: true, title: "SAM-Prédiction", statusBarStyle: "black-translucent" },
  icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#0b1d3a",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>
        <header className="sticky top-0 z-30 bg-night text-white" style={{ paddingTop: "env(safe-area-inset-top)" }}>
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
            <Link href="/" className="flex items-center gap-2.5">
              <Logo />
              <span className="leading-tight">
                <span className="block font-display text-[17px] font-bold tracking-tight">SAM-Prédiction</span>
                <span className="block text-[11px] text-white/65">L&apos;analyse avant le pronostic.</span>
              </span>
            </Link>
            <DesktopNav />
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-3.5 pb-28 pt-4 md:px-6 md:pb-12">{children}</main>
        <footer className="mx-auto max-w-5xl px-4 pb-28 text-center text-xs text-steel md:pb-8">
          Probabilités statistiques, aucune garantie de gain. Interdit aux mineurs. Pariez de manière responsable.
        </footer>
        <MobileTabs />
        <SwRegister />
      </body>
    </html>
  );
}
