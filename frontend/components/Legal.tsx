import Link from "next/link";
import type { ReactNode } from "react";

export const UPDATED = "8 novembre 2026";

/** Coordonnées de contact affichées dans les pages légales. */
export const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "moncomptejeu10@gmail.com";
export const CONTACT_PHONE = process.env.NEXT_PUBLIC_CONTACT_PHONE || "+223 71 27 44 86";

export function Contact() {
  return (
    <>
      <a href={`mailto:${CONTACT_EMAIL}`} className="font-semibold text-sky underline">{CONTACT_EMAIL}</a>
      {" "}ou par téléphone au{" "}
      <a href={`tel:${CONTACT_PHONE.replace(/\s/g, "")}`} className="font-semibold text-sky underline">{CONTACT_PHONE}</a>
    </>
  );
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
