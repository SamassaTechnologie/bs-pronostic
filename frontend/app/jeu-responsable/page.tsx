import { Block, LegalPage } from "@/components/Legal";

export const metadata = { title: "Jeu responsable", description: "Parier doit rester un loisir : signes d'alerte, conseils et aide gratuite." };

export default function JeuResponsable() {
  return (
    <LegalPage title="Jeu responsable" intro="Parier doit rester un loisir. Si ce n'est plus le cas, de l'aide existe.">
      <Block title="Les règles de base">
        <ul className="list-disc space-y-1 pl-5">
          <li>Ne misez que l&apos;argent que vous pouvez vous permettre de perdre, jamais celui du loyer, de la nourriture ou de l&apos;école.</li>
          <li>Fixez-vous un budget et une durée avant de commencer, et tenez-vous-y.</li>
          <li>Ne cherchez jamais à « vous refaire » après une perte.</li>
          <li>Un pronostic, même à 85 %, peut perdre. Plus un combiné a de matchs, plus ses chances baissent.</li>
          <li>Ne pariez pas sous le coup de l&apos;émotion, de la fatigue ou de l&apos;alcool.</li>
        </ul>
      </Block>
      <Block title="Signes d'alerte">
        <ul className="list-disc space-y-1 pl-5">
          <li>Vous misez plus que prévu, ou de plus en plus souvent.</li>
          <li>Vous empruntez de l&apos;argent ou vendez des biens pour parier.</li>
          <li>Vous cachez vos paris à vos proches.</li>
          <li>Vous pensez aux paris en permanence, ou vous êtes irritable quand vous ne pouvez pas parier.</li>
        </ul>
        <p>Si vous vous reconnaissez, faites une pause et parlez-en à un proche de confiance ou à un professionnel de santé.</p>
      </Block>
      <Block title="Se faire aider gratuitement">
        <ul className="list-disc space-y-1 pl-5">
          <li><strong>Gambling Therapy</strong> (service mondial, en ligne) : conseils pratiques et soutien gratuits, pour les joueurs et leurs proches — <a href="https://www.gamblingtherapy.org" className="text-sky underline" target="_blank" rel="noopener noreferrer">gamblingtherapy.org</a>.</li>
          <li><strong>Joueurs Info Service</strong> (France) : <a href="tel:+33974751313" className="font-semibold text-sky underline">09 74 75 13 13</a>, 7 jours sur 7 de 8 h à 2 h, appel anonyme.</li>
          <li>Les opérateurs de paris proposent des limites de dépôt et l&apos;auto-exclusion : utilisez-les.</li>
        </ul>
      </Block>
      <Block title="Mineurs">
        <p>Les paris d&apos;argent sont interdits aux moins de 18 ans. Parents : gardez vos comptes de paris protégés par un code.</p>
      </Block>
    </LegalPage>
  );
}
