# SAM-Prédiction

**L'analyse avant le pronostic.** Application web (PWA) de pronostics football fondée sur un moteur statistique réel : modèle de Dixon-Coles pondéré dans le temps, modèles corners/cartons, calibration mesurée par backtest, indice de confiance, historique immuable et contrôle des performances.

Aucune donnée n'est inventée : quand une information manque, l'application affiche « Données insuffisantes ».

---

## 1. Architecture

```
 iPhone / ordinateur
        │  HTTPS
        ▼
 ┌─────────────────────────────┐        ┌───────────────────────────────────────┐
 │ Frontend Next.js 16 (Vercel)│  HTTP  │ Backend FastAPI (Render, Docker)       │
 │ - pages rendues serveur     │──────▶│ - API publique /api/*                  │
 │ - PWA (manifest + SW)       │ jetons │ - API admin /api/admin/* (X-Admin-Token)│
 │ - proxy /api/proxy (lecture)│ côté   │ - moteur statistique (NumPy/SciPy)     │
 │ - session admin signée      │serveur │ - synchronisation planifiée            │
 └─────────────────────────────┘        └───────────────┬───────────────────────┘
                                                        │ SQLAlchemy
                     ┌──────────────────────────────────┼─────────────────────┐
                     ▼                                  ▼                     ▼
          PostgreSQL (Supabase)          football-data.co.uk (sans clé)   API-Football / football-data.org
          matchs, cotes, analyses,       résultats, corners, cartons,     (clés optionnelles) blessures,
          historique, calibration        cotes 1X2 et +/-2,5, calendrier  cotes multi-marchés, autres ligues
```

| Dossier | Contenu |
|---|---|
| `backend/app/engine/` | Moteur : `team_model.py` (Poisson régularisé + Dixon-Coles, gradient analytique), `markets.py` (27 marchés, règlement), `calibration.py` (Platt, Brier, Log Loss), `confidence.py`, `features.py` (forme 5/10, domicile/extérieur, H2H, classement), `explain.py`, `selection.py` (niveaux A-D), `combos.py`, `backtest.py` |
| `backend/app/providers/` | Connecteurs réels : football-data.co.uk, API-Football, football-data.org, rapprochement des noms d'équipes |
| `backend/app/services/` | Synchronisation, analyse et publication, règlement et statistiques, recalibrage |
| `backend/app/api/` | Routes publiques, administration, déclenchement externe |
| `backend/tests/` | 32 tests (moteur, connecteurs, chaîne complète sur une saison réelle, API, sécurité) |
| `frontend/` | Next.js + TypeScript + Tailwind CSS 4, interface entièrement en français |

### Moteur statistique

1. **Buts** : Dixon-Coles (forces offensive/défensive, avantage du terrain, correction des scores 0-0/1-0/0-1/1-1), pondération exponentielle (demi-vie ≈ 1 an), régularisation vers la moyenne (aucune grande équipe favorisée). Fenêtre de deux saisons.
2. **Marchés** : la matrice des scores donne 1X2, double chance, plus/moins 0,5 à 3,5, BTTS. Mi-temps : part des buts avant la pause propre à chaque championnat. Corners et cartons : modèle d'équipe dédié + loi binomiale négative (surdispersion estimée).
3. **Confrontations directes** : ajustement plafonné à ±8 %, à partir de 3 matchs sur 5 ans.
4. **Calibration** : régression logistique de Platt par marché, ajustée hors échantillon ; cohérence imposée (1X2 = 100 %, lignes décroissantes, marchés complémentaires).
5. **Confiance (0-100)** : volume de données, actualité, stabilité récente, fiabilité mesurée du marché, cohérence avec les cotes, absences, fin de saison.
6. **Sélection** : niveau A ≥ 85 %, B 78-84 %, C 70-77 %, D < 70 % (réglables). Un pronostic est retenu à partir de 70 %, avec une confiance suffisante et une cote juste ≥ 1,10 ; deux marchés non redondants par match au maximum.
7. **Combinés** : produit des probabilités entre matchs différents ; pour un même match, probabilité jointe lue dans la matrice des scores (jamais de multiplication naïve) ou refus si la corrélation n'est pas modélisée.

### Backtest sur données réelles (livré)

Rejeu chronologique sur 16 championnats européens (10 587 matchs de juillet 2024 à septembre 2026, données football-data.co.uk). Évaluation hors échantillon du 1er juillet 2025 au 5 septembre 2026 (5 539 matchs) :

| Niveau | Prédictions | Probabilité annoncée | Fréquence observée |
|---|---|---|---|
| A | 8 243 | 91,3 % | 91,4 % |
| B | 7 933 | 81,2 % | 81,4 % |
| C | 13 384 | 74,0 % | 74,5 % |

Comparaison honnête : sur le 1X2, le Brier score du modèle (0,2019) reste moins bon que celui des cotes moyennes des bookmakers (0,1977) ; idem sur +/-2,5 buts (0,2459 contre 0,2429). Le marché est une référence très forte : une « valeur positive » estimée n'est pas une garantie de rentabilité. Détails : `backend/app/engine/default_calibration.json`. Relancer : voir §6.

---

## 2. Installation locale

Prérequis : Python 3.12+ et Node.js 20.9+.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env        # puis éditez : en local, DATABASE_URL=sqlite:///./sam_prediction.db
python -m pytest            # 32 tests
uvicorn app.main:app --reload --port 8000
```

Au démarrage, les tables sont créées et une première synchronisation part après 45 secondes (football-data.co.uk, sans clé). Documentation interactive de l'API : http://localhost:8000/docs

```bash
# Frontend (autre terminal)
cd frontend
cp .env.example .env.local  # BACKEND_URL=http://localhost:8000, mêmes jetons que le backend
npm install
npm run dev                 # http://localhost:3000
```

---

## 3. Clés et fournisseurs de données

| Fournisseur | Clé | Ce qu'il apporte | Offre gratuite |
|---|---|---|---|
| **football-data.co.uk** | aucune | Résultats, mi-temps, tirs, corners, cartons, cotes 1X2 et +/-2,5 de plusieurs bookmakers pour 22 divisions européennes, plus 15 « nouvelles ligues » (résultats et cotes uniquement) ; calendrier de la semaine avec cotes | entièrement gratuit |
| **API-Football** (api-sports.io) | `API_FOOTBALL_KEY` | Calendrier de plus de 1 000 compétitions (dont africaines), blessures/suspensions, cotes double chance, BTTS, mi-temps, corners, cartons | 100 requêtes/jour, tous les endpoints, saisons limitées ; Pro à 19 $/mois pour 7 500 requêtes/jour |
| **football-data.org** | `FOOTBALL_DATA_ORG_KEY` | Calendrier et résultats de 12 compétitions dont la Ligue des champions | 12 compétitions, 10 appels/minute, scores différés, ni cotes ni statistiques |
| Sportmonks | non intégré | Données très riches (xG, prédictions) | 2 ligues gratuites (Danemark, Écosse) ; plans payants par nombre de ligues. L'interface `Provider` permet de l'ajouter. |

**Obtenir la clé API-Football** : créez un compte sur https://dashboard.api-football.com, la clé apparaît dans *Account → My Access*. Collez-la dans la variable `API_FOOTBALL_KEY` du backend (jamais dans le frontend). Dans l'administration, « Tester la connexion » affiche le plan et le quota réels. Si la saison en cours n'est pas couverte par le plan gratuit, l'erreur renvoyée par API-Football est affichée telle quelle.

**Obtenir la clé football-data.org** : inscription sur https://www.football-data.org/client/register, la clé arrive par e-mail → `FOOTBALL_DATA_ORG_KEY`.

**Ajouter un championnat africain** (ex. championnat du Mali) : récupérez son identifiant via l'endpoint `/leagues?country=Mali` d'API-Football, puis :

```bash
curl -X POST https://VOTRE-API/api/admin/competitions \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"code":"MLI1","name":"Première Division","country":"Mali","api_football_id":ID,"calendar_year":false}'
```

Le modèle exige au moins 60 matchs terminés dans la compétition et 6 par équipe ; en dessous, « Données insuffisantes ».

---

## 4. Déploiement (GitHub + Supabase + Render + Vercel)

1. **GitHub** : créez un dépôt privé et poussez ce dossier.
2. **Supabase** : créez un projet (région Europe). *Project Settings → Database → Connection string → Session pooler* : copiez l'URI (compatible IPv4) et remplacez le mot de passe.
3. **Render** : *New → Blueprint*, choisissez le dépôt (fichier `render.yaml`). Renseignez `DATABASE_URL` (URI Supabase), `CORS_ORIGINS` (URL Vercel) et, si vous les avez, les clés API. `ADMIN_API_TOKEN` et `CRON_SECRET` sont générés : notez-les. Vérifiez `https://VOTRE-API.onrender.com/api/health`.
4. **Vercel** : *Add New → Project*, même dépôt, *Root Directory* = `frontend`. Variables : `BACKEND_URL` (URL Render), `BACKEND_ADMIN_TOKEN` (= `ADMIN_API_TOKEN`), `ADMIN_PASSWORD` (votre mot de passe d'administration), `SESSION_SECRET` (32 caractères aléatoires).
5. **Synchronisation planifiée** : le plan gratuit de Render met le service en veille après inactivité. Dans Supabase, deux tâches `pg_cron` réveillent le backend puis appellent `/api/cron/run` toutes les 3 heures (`sam-wake` à hh:10, `sam-sync` à hh:15, avec l'en-tête `X-Cron-Secret`). Le workflow GitHub `sync.yml` reste disponible pour un lancement manuel (secrets `BACKEND_URL` et `CRON_SECRET`).

### Déploiement en service

| Élément | Valeur |
|---|---|
| Site | https://sam-prediction.vercel.app (projet Vercel `sam-prediction`, dossier `frontend`) |
| API | https://sam-prediction-api.onrender.com (service Render `sam-prediction-api`, Frankfurt) |
| Base | Supabase `sam-prediction` (Paris), rôle dédié `sam_app`, schéma `sam` non exposé par l'API publique |
| Connexion | pooler Supabase en mode session : `aws-1-eu-west-3.pooler.supabase.com:5432` |
6. **iPhone** : ouvrez l'URL Vercel dans Safari → Partager → « Sur l'écran d'accueil ».

Générer des secrets : `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

---

## 5. Sécurité

- Clés API uniquement dans les variables d'environnement du backend ; jamais transmises au navigateur.
- Le navigateur ne parle qu'au frontend ; le proxy `/api/proxy` n'autorise que des lectures et le calcul de combinés.
- Administration : mot de passe vérifié côté serveur (comparaison à temps constant), session signée HMAC, cookie `httpOnly` + `SameSite=Strict`, jeton `X-Admin-Token` ajouté côté serveur.
- Historique immuable : probabilité, cote, niveau et date d'un pronostic publié ne peuvent plus être modifiés (contrôle appliqué par l'ORM, testé).
- En-têtes de sécurité HTTP (`X-Frame-Options`, `nosniff`, `Referrer-Policy`).

---

## 6. Exploitation

- **Administration** (`/admin`) : état des sources, test de connexion, synchronisation manuelle, seuils, championnats, journal.
- **Recalibrer** : bouton « Recalibrer le modèle » (backtest sur les 12 derniers mois en base, ≥ 300 cas par marché).
- **Backtest hors ligne** sur un CSV football-data.co.uk :
  `python -m scripts.backtest_csv chemin/fichier.csv --divisions E0,D1 --start 2024-07-01 --split 2025-07-01 --end 2026-06-30`
- **Tests** : `cd backend && python -m pytest` ; `cd frontend && npm run build`.

---

## 7. Limites connues

- Aucune garantie de gain. 85 % de probabilité signifie aussi 15 % d'échec.
- xG non disponibles dans les sources gratuites ; compositions, météo et motivation non modélisées directement (le classement et la fin de saison sont signalés).
- Les « nouvelles ligues » de football-data.co.uk n'ont ni mi-temps, ni corners, ni cartons : ces marchés y sont « Données insuffisantes ».
- Coupes européennes : équipes de championnats différents, modèle moins fiable (confiance réduite).
- Cartons : la convention du deuxième jaune varie selon la source ; vérifiez la règle de votre bookmaker.
- Migrations de schéma : `create_all` au démarrage ; passer à Alembic avant d'ajouter des colonnes en production.

Sources de données : football-data.co.uk (usage selon les conditions du site), API-Football, football-data.org. Jeu de test réel : Premier League 2025-2026 via le dépôt MIT « Club-Football-Match-Data-2000-2025 ».
