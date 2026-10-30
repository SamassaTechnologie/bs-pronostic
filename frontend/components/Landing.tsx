import Link from "next/link";
import { pct } from "@/lib/format";

type Summary = {
  competitions: number;
  upcoming_analysed: number;
  all: { total: number; n: number; won: number; hit_rate: number | null; avg_probability: number | null };
  selection: { total: number; n: number; won: number; hit_rate: number | null; avg_probability: number | null };
  backtest: { tiers: Record<string, { n: number; mean_predicted: number; observed_frequency: number }> | null; n_matches: number | null; divisions: number };
};

const STEPS: [string, string][] = [
  ["Des données réelles", "Résultats, corners, cartons et cotes de plus d'une dizaine de championnats, mis à jour toutes les 3 heures."],
  ["Un modèle statistique", "Chaque match est modélisé (Dixon-Coles), puis la probabilité est confrontée aux cotes des bookmakers."],
  ["Une sélection exigeante", "Seuls les marchés assez probables, avec des données solides, sont retenus. Les matchs incertains sont signalés."],
];

export function Landing({ s }: { s: Summary | null }) {
  const a = s?.backtest.tiers?.A;
  const sel = s?.selection;
  return (
    <div className="-mx-3.5 -mt-4 md:-mx-6">
      <section className="bg-night px-5 pb-10 pt-8 text-white md:px-10 md:pt-14">
        <div className="mx-auto max-w-3xl">
          <h1 className="font-display text-[34px] font-bold leading-[1.08] tracking-tight md:text-5xl">
            Des pronostics football calculés, vérifiés et publiés avant le coup d&apos;envoi.
          </h1>
          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-white/75">
            SAM-Prédiction estime la probabilité de chaque marché (1X2, double chance, buts, corners, cartons) et n&apos;affiche que
            les sélections solides. Chaque pronostic est daté et réglé automatiquement : rien n&apos;est effacé après coup.
          </p>
          <div className="mt-6 flex flex-col gap-2.5 sm:flex-row">
            <Link href="/connexion?mode=inscription" className="rounded-xl bg-pitch px-5 py-3.5 text-center text-[15px] font-bold text-white">
              Créer mon compte gratuit
            </Link>
            <Link href="/historique?selection=1" className="rounded-xl border border-white/25 px-5 py-3.5 text-center text-[15px] font-semibold text-white">
              Voir les résultats publiés
            </Link>
          </div>
          <p className="mt-3 text-xs text-white/55">Déjà inscrit ? <Link href="/connexion" className="font-semibold text-white underline">Se connecter</Link></p>
        </div>
      </section>

      <section className="mx-auto max-w-3xl px-5 py-8 md:px-10">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-line bg-white p-4">
            <div className="font-display text-3xl font-bold">{a ? pct(a.observed_frequency, 1) : "—"}</div>
            <p className="mt-1 text-xs text-steel">
              de réussite observée sur {a ? a.n.toLocaleString("fr-FR") : "—"} prédictions de niveau A, en test sur{" "}
              {s?.backtest.n_matches?.toLocaleString("fr-FR") ?? "—"} matchs passés (annoncé : {a ? pct(a.mean_predicted, 1) : "—"}).
            </p>
          </div>
          <div className="rounded-xl border border-line bg-white p-4">
            <div className="font-display text-3xl font-bold">{sel && sel.n ? pct(sel.hit_rate) : sel?.total ?? 0}</div>
            <p className="mt-1 text-xs text-steel">
              {sel && sel.n
                ? `de réussite sur ${sel.n} pronostics de la Sélection SAM déjà réglés en conditions réelles.`
                : "pronostics de la Sélection SAM publiés ; le bilan réel s'affiche dès les premiers résultats."}
            </p>
          </div>
        </div>
        <p className="mt-3 text-xs text-steel">
          {s ? `${s.competitions} compétitions suivies, ${s.upcoming_analysed} matchs à venir analysés.` : ""} Les chiffres de test proviennent
          d&apos;un rejeu sur des matchs que le modèle n&apos;avait pas vus. Ils ne garantissent pas les résultats futurs.
        </p>

        <h2 className="mt-9 font-display text-xl font-bold tracking-tight">Comment ça marche</h2>
        <ol className="mt-3 space-y-3">
          {STEPS.map(([t, d], i) => (
            <li key={t} className="flex gap-3 rounded-xl border border-line bg-white p-4">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-night text-sm font-bold text-white">{i + 1}</span>
              <div>
                <h3 className="font-semibold">{t}</h3>
                <p className="mt-0.5 text-sm leading-relaxed text-ink">{d}</p>
              </div>
            </li>
          ))}
        </ol>

        <h2 className="mt-9 font-display text-xl font-bold tracking-tight">Avec un compte gratuit</h2>
        <ul className="mt-3 space-y-2 text-[15px]">
          {[
            "La Sélection SAM du jour : 5 pronostics au maximum, les plus solides",
            "Toutes les probabilités par match, avec explication et facteurs",
            "Le générateur de combinés qui calcule le risque réel",
            "Le suivi de vos pronostics favoris",
          ].map((t) => (
            <li key={t} className="flex gap-2.5">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-pitch" />
              {t}
            </li>
          ))}
        </ul>
        <Link href="/connexion?mode=inscription" className="mt-6 block rounded-xl bg-night px-5 py-3.5 text-center text-[15px] font-bold text-white">
          Créer mon compte gratuit
        </Link>
        <p className="mt-6 text-xs leading-relaxed text-steel">
          Réservé aux personnes majeures. Les pronostics sont des estimations statistiques : aucune garantie de gain. Ne misez que ce
          que vous pouvez vous permettre de perdre. <Link href="/methodologie" className="font-semibold text-sky">Méthodologie</Link>
        </p>
      </section>
    </div>
  );
}
