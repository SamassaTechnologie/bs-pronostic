import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";
import { DesktopNav, Logo, MobileTabs } from "@/components/Nav";
import { SwRegister } from "@/components/SwRegister";
import { SearchBox } from "@/components/SearchBox";
import { FollowsProvider } from "@/components/Follows";
import { currentMember } from "@/lib/supabase/server";

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

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const signedIn = Boolean(await currentMember());
  return (
    <html lang="fr">
      <body>
        <header className="sticky top-0 z-30 bg-night text-white" style={{ paddingTop: "env(safe-area-inset-top)" }}>
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
            <Link href="/" className="flex items-center gap-2.5">
              <Logo />
              <span className="leading-tight">
                <span className="block whitespace-nowrap font-display text-[17px] font-bold tracking-tight">SAM-Prédiction</span>
                <span className="block text-[11px] text-white/65">L&apos;analyse avant le pronostic.</span>
              </span>
            </Link>
            <div className="flex items-center gap-1">
              <DesktopNav signedIn={signedIn} />
              <Link href="/assistant" aria-label="Assistant IA"
                className="flex h-9 items-center gap-1 rounded-lg bg-pitch px-2.5 text-[13px] font-bold text-white hover:bg-pitch-deep">
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8z" />
                </svg>
                IA
              </Link>
              <SearchBox />
            </div>
          </div>
        </header>
        <FollowsProvider signedIn={signedIn}>
          <main className="mx-auto max-w-5xl px-3.5 pb-28 pt-4 md:px-6 md:pb-12">{children}</main>
        </FollowsProvider>
        <footer className="mx-auto max-w-5xl px-4 pb-28 text-center text-xs text-steel md:pb-8">
          Probabilités statistiques, aucune garantie de gain. Interdit aux mineurs. Pariez de manière responsable.
        </footer>
        <MobileTabs signedIn={signedIn} />
        <SwRegister />
      </body>
    </html>
  );
}
