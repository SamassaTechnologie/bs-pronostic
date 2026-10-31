"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const BASE = [
  { href: "/", label: "Accueil", icon: "M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" },
  { href: "/pronostics", label: "Pronostics", icon: "M4 19h16M6 16V9m6 7V5m6 11v-4" },
  { href: "/direct", label: "Direct", icon: "M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M4.9 4.9a10 10 0 0 0 0 14.2M19.1 4.9a10 10 0 0 1 0 14.2" },
  { href: "/ligues", label: "Ligues", icon: "M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0zM7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3" },
];
const RESULTS = { href: "/historique", label: "Résultats", icon: "M12 7v5l3 2M21 12a9 9 0 1 1-3-6.7M21 4v4h-4" };
const ACCOUNT_ICON = "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0";

function links(signedIn: boolean) {
  return [...BASE, signedIn
    ? { href: "/compte", label: "Compte", icon: ACCOUNT_ICON }
    : { href: "/connexion", label: "Connexion", icon: ACCOUNT_ICON }];
}

function active(path: string, href: string) {
  return href === "/" ? path === "/" : path.startsWith(href);
}

export function DesktopNav({ signedIn }: { signedIn: boolean }) {
  const path = usePathname();
  const all = links(signedIn);
  const LINKS = [...all.slice(0, -1), RESULTS, all[all.length - 1]];
  return (
    <nav className="hidden items-center gap-1 md:flex" aria-label="Navigation principale">
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${active(path, l.href) ? "bg-white/15 text-white" : "text-white/70 hover:text-white"}`}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

export function MobileTabs({ signedIn }: { signedIn: boolean }) {
  const path = usePathname();
  const LINKS = links(signedIn);
  return (
    <nav className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white/95 backdrop-blur md:hidden" aria-label="Navigation">
      <ul className="mx-auto grid max-w-md grid-cols-5">
        {LINKS.map((l) => {
          const on = active(path, l.href);
          return (
            <li key={l.href}>
              <Link href={l.href} className={`flex flex-col items-center gap-0.5 pt-2 pb-1 text-[11px] font-semibold ${on ? "text-night" : "text-steel/80"}`} aria-current={on ? "page" : undefined}>
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={on ? 2.2 : 1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d={l.icon} />
                </svg>
                {l.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="14" fill="#13294b" />
      <circle cx="32" cy="32" r="19" fill="none" stroke="#fff" strokeWidth="3.5" />
      <path d="M17 39 27 30l7 6 13-14" fill="none" stroke="#12a150" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
