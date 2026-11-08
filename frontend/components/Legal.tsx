import Link from "next/link";
import type { ReactNode } from "react";

export const UPDATED = "8 novembre 2026";

/** Adresse de contact affichée dans les pages légales (variable d'environnement publique, facultative). */
export function Contact() {
  const mail = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
  return mail ? <a href={`mailto:${mail}`} className="font-semibold text-sky underline">{mail}</a> : <span>l&apos;adresse indiquée dans l&apos;application</span>;
}

export function LegalPage({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-2xl">
      <h1 className="px-1 font-display text-2xl font-bold tracking-tight">{title}</h1>
      <p className="mt-1 px-1 text-sm text-steel">{intro} Dernière mise à jour : {UPDATED}.</p>
      <div className="mt-4 space-y-3">{children}</div>
      <nav className="mt-6 flex flex-wrap gap-x-4 gap-y-1 px-1 text-[13px] font-semibold text-sky" aria-label="Pages légales">
        <Link href="/conditions">Conditions d&apos;utilisation</Link>
        <Link href="/confidentialite">Confidentialité</Link>
        <Link href="/jeu-responsable">Jeu responsable</Link>
      </nav>
    </article>
  );
}

export function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-white p-4 text-[14px] leading-relaxed text-night">
      <h2 className="mb-1.5 text-[15px] font-bold">{title}</h2>
      <div className="space-y-2">{children}</div>
    </section>
  );
}
