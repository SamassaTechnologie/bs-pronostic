import { Block, Contact, LegalPage } from "@/components/Legal";

export const metadata = { title: "Confidentialité", description: "Données personnelles traitées par SAM-Prédiction." };

export default function Confidentialite() {
  return (
    <LegalPage title="Politique de confidentialité" intro="Quelles données SAM-Prédiction conserve, pourquoi, et comment les supprimer.">
      <Block title="Données conservées">
        <ul className="list-disc space-y-1 pl-5">
          <li><strong>Compte</strong> : adresse e-mail et identifiant de membre, pour vous connecter.</li>
          <li><strong>Utilisation de l&apos;assistant</strong> : nombre de questions posées par jour (pour appliquer les limites) ; le texte des questions n&apos;est pas conservé dans votre profil.</li>
          <li><strong>Section Jouer</strong> : vos paris en jetons fictifs et votre solde.</li>
          <li><strong>Alertes</strong> : si vous les activez, l&apos;adresse technique d&apos;envoi fournie par votre navigateur et vos préférences (types d&apos;alertes, championnats favoris).</li>
          <li><strong>Sur votre appareil uniquement</strong> : coupon, filtres enregistrés de la Machine SAM, fuseau horaire.</li>
        </ul>
      </Block>
      <Block title="Ce que nous ne faisons pas">
        <p>Aucune vente ni location de vos données, aucune publicité ciblée, aucun suivi publicitaire.</p>
      </Block>
      <Block title="Hébergement et prestataires">
        <ul className="list-disc space-y-1 pl-5">
          <li>Base de données et connexion : Supabase (serveurs à Paris).</li>
          <li>Serveur d&apos;analyse : Render (Francfort).</li>
          <li>Pages de l&apos;application : Vercel.</li>
          <li>Assistant : questions transmises à un fournisseur d&apos;intelligence artificielle (Google Gemini ou Groq) pour produire la réponse, sans votre adresse e-mail.</li>
          <li>Alertes : acheminées par le service de notification de votre navigateur ou de votre téléphone (Apple, Google, Mozilla…).</li>
        </ul>
      </Block>
      <Block title="Durée de conservation">
        <p>Les données du compte sont conservées tant que le compte existe. Un appareil qui n&apos;accepte plus les alertes est retiré automatiquement.</p>
      </Block>
      <Block title="Vos droits">
        <p>Vous pouvez désactiver les alertes à tout moment dans « Mes alertes », et demander l&apos;accès, la correction ou la suppression de votre compte et de vos données en écrivant à <Contact />.</p>
      </Block>
    </LegalPage>
  );
}
