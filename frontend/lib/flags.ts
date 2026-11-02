const FLAGS: Record<string, string> = {
  Angleterre: "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Écosse": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", Allemagne: "🇩🇪", Italie: "🇮🇹", Espagne: "🇪🇸", France: "🇫🇷",
  "Pays-Bas": "🇳🇱", Belgique: "🇧🇪", Portugal: "🇵🇹", Turquie: "🇹🇷", "Grèce": "🇬🇷", Europe: "🇪🇺",
  "Brésil": "🇧🇷", Argentine: "🇦🇷", Autriche: "🇦🇹", Chine: "🇨🇳", Danemark: "🇩🇰", Finlande: "🇫🇮",
  Irlande: "🇮🇪", Japon: "🇯🇵", Mexique: "🇲🇽", "Norvège": "🇳🇴", Pologne: "🇵🇱", Roumanie: "🇷🇴",
  "Suède": "🇸🇪", Suisse: "🇨🇭", "États-Unis": "🇺🇸", Afrique: "🌍", Mali: "🇲🇱", "Sénégal": "🇸🇳",
  "Côte d'Ivoire": "🇨🇮", Maroc: "🇲🇦", "Égypte": "🇪🇬", "Algérie": "🇩🇿", Tunisie: "🇹🇳",
  "Afrique du Sud": "🇿🇦", Nigeria: "🇳🇬", Ghana: "🇬🇭", Cameroun: "🇨🇲", "Guinée": "🇬🇳", "Burkina Faso": "🇧🇫",
};

export function flag(country: string | null | undefined): string {
  return (country && FLAGS[country]) || "⚽";
}
