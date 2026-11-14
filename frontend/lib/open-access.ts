/**
 * Accès libre temporaire : la connexion (Supabase Auth) est suspendue jusqu'au renouvellement du quota, le 30 novembre 2026.
 * Pendant cette période, les pages membres s'affichent sans compte. Après la date ci-dessous, la connexion redevient
 * obligatoire automatiquement, sans nouvelle mise à jour.
 */
const OPEN_UNTIL = Date.parse("2026-12-01T00:00:00Z");

export function openAccess(): boolean {
  return Date.now() < OPEN_UNTIL;
}
