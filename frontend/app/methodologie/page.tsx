import { backend } from "@/lib/api";
import { num, pct } from "@/lib/format";
import type { Meta } from "@/lib/types";
import { Card, Section } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Méthodologie" };

const STEPS: [string, string][] = [
  ["Données réelles", "Résultats, scores à la mi-temps, corners, cartons et cotes proviennent de football-data.co.uk (gratuit) et, si les clés sont configurées, d'API-Football (absences, cotes multi-marchés) et de football-data.org. Une donnée absente n'est jamais remplacée par une valeur inventée : le marché concerné affiche « Données insuffisantes »."],
  ["Modèle des buts", "Modèle de Dixon-Coles : chaque équipe reçoit une force offensive et défensive, avec un avantage du terrain et une correction des petits scores (0-0, 1-0, 0-1, 1-1). Les matchs récents pèsent davantage (demi-vie d'environ un an) et chaque équipe est ramenée vers la moyenne quand ses données sont peu nombreuses : aucune « grande équipe » n'est favorisée par défaut."],
  ["Tous les marchés", "La matrice des scores donne 1X2, double chance, plus/moins de buts et « les deux équipes marquent ». La mi-temps utilise la part des buts inscrits avant la pause dans chaque championnat. Corners et cartons ont leur propre modèle (loi binomiale négative, adaptée à leur forte variabilité)."],
  ["Confrontations directes", "Elles ajustent les buts attendus de 8 % au plus et uniquement à partir de trois rencontres sur cinq ans : elles ne décident jamais seules d'un pronostic."],
  ["Calibration", "Les probabilités brutes sont corrigées par une régression logistique ajustée sur un backtest chronologique (le modèle ne voit jamais les matchs qu'il prédit). Objectif : quand l'application annonce 80 %, l'événement doit se produire environ 8 fois sur 10."],
  ["Confiance", "Indice distinct de la probabilité, de 0 à 100 : volume de données, actualité, stabilité des performances récentes, fiabilité mesurée du modèle sur ce marché et cohérence avec les cotes du marché."],
  ["Sélection", "Un pronostic est retenu s'il atteint 70 % de probabilité, une confiance suffisante et une cote juste d'au moins 1,10 (les quasi-certitudes sans intérêt sont écartées). Au plus deux marchés non redondants par match. Les matchs trop incertains sont signalés comme « à éviter »."],
];

export default async function Methodologie() {
  const meta = await backend<Meta>("/api/meta");
  const cal = meta.data?.calibration;
  const bench = cal?.market_benchmark;
  return (
    <>
      <h1 className="px-1 font-display text-2xl font-bold tracking-tight">Comment sont calculées les probabilités</h1>
      <p className="mt-1 px-1 text-sm text-steel">L&apos;analyse avant le pronostic : chaque chiffre affiché est recalculable à partir des données.</p>
      <div className="mt-4 space-y-2.5">
        {STEPS.map(([t, d]) => (
          <Card key={t} className="p-4">
            <h2 className="font-semibold">{t}</h2>
            <p className="mt-1 text-sm leading-relaxed text-ink">{d}</p>
          </Card>
        ))}
      </div>

      {cal?.tiers && (
        <Section title="Vérification sur données historiques">
          <Card className="p-4 text-sm">
            <p>
              Backtest sur {cal.n_matches?.toLocaleString("fr-FR")} matchs réels ({cal.divisions?.length} championnats européens),
              période d&apos;évaluation hors échantillon du {cal.period?.split} au {cal.period?.end}.
            </p>
            <table className="mt-3 w-full">
              <thead>
                <tr className="text-xs text-steel">
                  <th className="py-1 text-left font-normal">Niveau</th>
                  <th className="py-1 text-right font-normal">Prédictions</th>
                  <th className="py-1 text-right font-normal">Annoncé</th>
                  <th className="py-1 text-right font-normal">Observé</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(cal.tiers).map(([t, v]) => (
                  <tr key={t} className="border-t border-line">
                    <td className="py-1.5 font-semibold">Niveau {t}</td>
                    <td className="py-1.5 text-right">{v.n.toLocaleString("fr-FR")}</td>
                    <td className="py-1.5 text-right">{pct(v.mean_predicted, 1)}</td>
                    <td className="py-1.5 text-right font-semibold">{pct(v.observed_frequency, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {bench && (
              <p className="mt-3 text-steel">
                Comparaison honnête : sur le 1X2, le Brier score du modèle ({num(bench["1X2"]?.brier_model, 4)}) reste moins bon que celui des
                cotes moyennes des bookmakers ({num(bench["1X2"]?.brier_market, 4)}). Le marché est une référence très solide : une « valeur
                positive » estimée n&apos;est pas une garantie de rentabilité.
              </p>
            )}
          </Card>
        </Section>
      )}

      <Section title="Limites">
        <Card className="p-4 text-sm">
          <ul className="list-disc space-y-1 pl-5">
            <li>Aucune garantie de gain : une probabilité de 85 % signifie aussi 15 % d&apos;échec.</li>
            <li>Compositions d&apos;équipes, météo et motivation ne sont pas modélisées directement.</li>
            <li>Les xG ne sont pas fournis par les sources gratuites actuelles.</li>
            <li>Cartons : chaque source a sa convention (deuxième jaune). Vérifiez la règle de votre bookmaker.</li>
            <li>Les combinés supposent l&apos;indépendance entre matchs différents.</li>
          </ul>
        </Card>
      </Section>
    </>
  );
}
