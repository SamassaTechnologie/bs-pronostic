import Link from "next/link";
import { Block, Contact, LegalPage } from "@/components/Legal";

export const metadata = { title: "Conditions d'utilisation", description: "Conditions d'utilisation de SAM-Prédiction." };

export default function Conditions() {
  return (
    <LegalPage title="Conditions d'utilisation" intro="En utilisant SAM-Prédiction, vous acceptez les conditions ci-dessous.">
      <Block title="1. Le service">
        <p>SAM-Prédiction publie des analyses statistiques de matchs de football : probabilités, indices de confiance, statistiques, pronostics et outils (Machine SAM, assistant, alertes). L&apos;application ne prend aucun pari et ne reçoit aucune mise d&apos;argent.</p>
      </Block>
      <Block title="2. Réservé aux adultes">
        <p>L&apos;application est réservée aux personnes majeures (18 ans ou l&apos;âge légal de votre pays s&apos;il est plus élevé). Les paris d&apos;argent sont interdits aux mineurs.</p>
      </Block>
      <Block title="3. Aucune garantie de gain">
        <p>Une probabilité n&apos;est pas une certitude : un pronostic à 80 % échoue en moyenne une fois sur cinq. Les résultats passés affichés dans <Link href="/bilan" className="text-sky underline">Notre bilan</Link> ne garantissent pas les résultats futurs. Vous restez seul responsable de vos décisions et de vos éventuelles mises chez un opérateur de paris.</p>
        <p>Les cotes « justes » sont calculées par SAM ; les cotes de bookmakers sont relevées à un instant donné et peuvent avoir changé.</p>
      </Block>
      <Block title="4. Section « Jouer » et jetons">
        <p>Les jetons de la section Jouer sont fictifs : ils n&apos;ont aucune valeur monétaire, ne s&apos;achètent pas et ne s&apos;échangent pas contre de l&apos;argent ou des lots.</p>
      </Block>
      <Block title="5. Compte">
        <p>Vous êtes responsable de la confidentialité de vos identifiants. Un compte peut être suspendu en cas d&apos;abus (tentative d&apos;accès non autorisé, usage automatisé massif, contournement des limites de l&apos;assistant).</p>
      </Block>
      <Block title="6. Données et sources">
        <p>Les données proviennent de fournisseurs tiers (résultats, calendriers, cotes, compositions). Elles peuvent comporter des erreurs ou des retards ; quand elles manquent, l&apos;application affiche « Données insuffisantes » plutôt qu&apos;une estimation. Les textes de l&apos;assistant sont produits par une intelligence artificielle et peuvent contenir des erreurs.</p>
      </Block>
      <Block title="7. Disponibilité">
        <p>Le service est fourni tel quel, sans garantie de disponibilité permanente. Il peut évoluer, être interrompu pour maintenance ou modifié à tout moment.</p>
      </Block>
      <Block title="8. Contact">
        <p>Pour toute question : <Contact />.</p>
      </Block>
    </LegalPage>
  );
}
