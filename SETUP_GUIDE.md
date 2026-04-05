# ENDO DEBRIEF — Guide de Setup Complet
*À faire une seule fois — environ 2-3 heures*

---

## Vue d'ensemble

```
Ce que tu vas configurer :
  ✅ GitHub (hébergement du code + automatisation gratuite)
  ✅ OpenAI API (GPT-4o + DALL-E)
  ✅ ElevenLabs (clonage de ta voix)
  ✅ NCBI / PubMed (accès aux articles)
  ✅ YouTube (publication automatique)
  ✅ Instagram + Facebook (publication automatique)
  ✅ TikTok (publication automatique)
  ✅ Gmail (notifications email)
```

---

## ÉTAPE 1 — GitHub (20 min)

### 1.1 Créer un compte GitHub
→ https://github.com/join (gratuit)

### 1.2 Créer un nouveau repository
1. Aller sur https://github.com/new
2. Name : `endo-debrief`
3. Private (recommandé, pour protéger tes secrets)
4. Cliquer "Create repository"

### 1.3 Uploader le code
1. Télécharger ce dossier "Endo Debrief" sur ton ordinateur
2. Dans le terminal (ou GitHub Desktop) :

```bash
cd "Endo Debrief"
git init
git add .
git commit -m "Initial Endo Debrief setup"
git remote add origin https://github.com/TON-USERNAME/endo-debrief.git
git push -u origin main
```

> 💡 Alternative sans terminal : utiliser [GitHub Desktop](https://desktop.github.com/) (interface graphique)

---

## ÉTAPE 2 — OpenAI API (15 min)

Tu as déjà un abonnement ChatGPT Plus → ton compte OpenAI existe déjà.

### 2.1 Obtenir une clé API
1. Aller sur https://platform.openai.com/api-keys
2. Cliquer "Create new secret key"
3. Name : "Endo Debrief"
4. **Copier la clé** (commence par `sk-proj-...`) — elle ne sera plus visible ensuite

### 2.2 Ajouter des crédits
→ https://platform.openai.com/settings/organization/billing
- Recharger avec ~20€ pour commencer (durera 2-3 mois)
- Le coût estimé est ~8-12€/mois

---

## ÉTAPE 3 — ElevenLabs (30 min — clonage de ta voix)

### 3.1 Créer un compte
→ https://elevenlabs.io/
- S'inscrire avec ton email
- Plan recommandé : **Creator** (~22€/mois)

### 3.2 Cloner ta voix
1. Dans l'interface ElevenLabs → "Voices" → "Add Voice"
2. Choisir "Instant Voice Clone"
3. **Enregistrer 1-2 minutes de ta voix** :
   - Parle clairement, à ton rythme naturel
   - Contenu suggéré : lis un résumé d'article scientifique en anglais
   - Environnement calme, micro de bonne qualité
   - Format : MP3 ou WAV
4. Uploader le fichier audio
5. Nommer la voix : "Dr Dabi"
6. Cliquer "Create"

### 3.3 Récupérer le Voice ID
1. Aller dans "Voices" → cliquer sur ta voix clonée
2. Dans l'URL ou dans les paramètres, copier le `voice_id`
   (ex: `abc123def456ghi789`)

### 3.4 Obtenir la clé API
→ https://elevenlabs.io/app/settings/api-keys
- Cliquer "Create API Key"
- Copier la clé

---

## ÉTAPE 4 — NCBI / PubMed (5 min)

Une clé NCBI est optionnelle mais augmente le rate limit de 3 à 10 requêtes/seconde.

1. Créer un compte sur https://www.ncbi.nlm.nih.gov/account/
2. Aller dans Account Settings → API Key Management
3. Générer une clé
4. Copier la clé (gratuite)

---

## ÉTAPE 5 — YouTube API (45 min)

### 5.1 Créer un projet Google Cloud
1. Aller sur https://console.cloud.google.com/
2. Créer un nouveau projet : "Endo Debrief"
3. Aller dans "APIs & Services" → "Library"
4. Rechercher et activer "YouTube Data API v3"

### 5.2 Configurer OAuth2
1. "APIs & Services" → "Credentials"
2. "Create Credentials" → "OAuth client ID"
3. Application type : "Desktop app"
4. Name : "Endo Debrief"
5. Télécharger le fichier `client_secrets.json`
6. Copier `client_id` et `client_secret` depuis ce fichier

### 5.3 Obtenir le Refresh Token
Lance ce script une seule fois sur ton ordinateur :

```python
# save as get_youtube_token.py
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secrets.json",
    scopes=["https://www.googleapis.com/auth/youtube.upload"]
)
creds = flow.run_local_server(port=0)
print("REFRESH TOKEN:", creds.refresh_token)
```

```bash
pip install google-auth-oauthlib
python get_youtube_token.py
```
→ Un navigateur s'ouvre, connecte-toi avec le compte YouTube Endo Debrief
→ Copier le refresh token affiché dans le terminal

---

## ÉTAPE 6 — Instagram + Facebook (60 min)

Cette étape nécessite un compte **Facebook Business**.

### 6.1 Créer une Page Facebook "Endo Debrief"
1. https://www.facebook.com/pages/create/
2. Choisir "Business or Brand"
3. Nom : "Endo Debrief"
4. Copier l'URL de la page → noter le **Page ID** (dans l'URL)

### 6.2 Connecter Instagram à Facebook
1. Créer un compte Instagram "endodebrief"
2. Passer en compte **Professional** (Creator ou Business)
3. Dans les paramètres Instagram → "Accounts Center" → lier à ta Page Facebook

### 6.3 Créer une App Meta
1. Aller sur https://developers.facebook.com/
2. "My Apps" → "Create App"
3. Use case : "Other" → Business
4. App name : "Endo Debrief"
5. Copier `App ID` et `App Secret`

### 6.4 Configurer les permissions
1. Dans ton App → "Add a Product" → "Instagram Graph API"
2. "Add a Product" → "Facebook Login"
3. Dans les permissions, ajouter :
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `instagram_content_publish`
   - `instagram_basic`

### 6.5 Obtenir le Page Access Token
1. Aller sur https://developers.facebook.com/tools/explorer/
2. Sélectionner ton App
3. Générer un token avec les permissions listées ci-dessus
4. Échanger le token pour un token **long-lived** (60 jours) :

```bash
curl -X GET \
  "https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_LIVED_TOKEN"
```

5. Obtenir l'Instagram User ID :
```bash
curl -X GET "https://graph.facebook.com/v19.0/me/accounts?access_token=LONG_LIVED_TOKEN"
# Trouver l'id de la page
curl -X GET "https://graph.facebook.com/v19.0/PAGE_ID?fields=instagram_business_account&access_token=TOKEN"
```

> ⚠️ Pour une publication automatique permanente, il faut soumettre l'app pour review Meta.
> En attendant, le token long-lived fonctionne pendant 60 jours (renouvellement automatisable).

---

## ÉTAPE 7 — TikTok API (30 min)

### 7.1 Créer un compte développeur TikTok
→ https://developers.tiktok.com/

### 7.2 Créer une App
1. "My Apps" → "Create App"
2. App Name : "Endo Debrief"
3. Catégorie : "Educational"
4. Ajouter le produit : **Content Posting API**

### 7.3 Obtenir le Access Token
1. Dans ton App → "Manage" → "Auth"
2. Suivre le flow OAuth2 pour connecter le compte TikTok @EndoDebrief
3. Copier l'`access_token` résultant

> ⚠️ TikTok Content Posting API nécessite une approbation. Compter 1-2 semaines.
> En attendant, le pipeline peut tout préparer et publier manuellement.

---

## ÉTAPE 8 — Gmail (Notifications email)

### 8.1 Activer la vérification en 2 étapes
→ https://myaccount.google.com/security

### 8.2 Créer un App Password Gmail
1. Aller sur https://myaccount.google.com/apppasswords
2. App : "Mail"
3. Device : "Other" → "Endo Debrief"
4. Copier le mot de passe à 16 caractères généré (ex: `abcd efgh ijkl mnop`)

> ⚠️ Utiliser ce mot de passe dans `.env`, pas ton mot de passe Gmail habituel.

---

## ÉTAPE 9 — Configurer les secrets GitHub (15 min)

C'est ici que toutes tes clés API sont stockées de manière sécurisée.

1. Aller sur https://github.com/TON-USERNAME/endo-debrief/settings/secrets/actions
2. Cliquer "New repository secret" pour chaque secret :

| Secret Name | Valeur |
|-------------|--------|
| `OPENAI_API_KEY` | Ta clé OpenAI |
| `ELEVENLABS_API_KEY` | Ta clé ElevenLabs |
| `ELEVENLABS_VOICE_ID` | L'ID de ta voix clonée |
| `NCBI_API_KEY` | Ta clé NCBI (optionnelle) |
| `YOUTUBE_CLIENT_ID` | Ton client ID Google |
| `YOUTUBE_CLIENT_SECRET` | Ton client secret Google |
| `YOUTUBE_REFRESH_TOKEN` | Le refresh token YouTube |
| `META_APP_ID` | Ton App ID Meta |
| `META_APP_SECRET` | Ton App Secret Meta |
| `META_PAGE_ACCESS_TOKEN` | Le Page Access Token Facebook |
| `META_INSTAGRAM_USER_ID` | Ton Instagram User ID |
| `META_FACEBOOK_PAGE_ID` | Ton Facebook Page ID |
| `TIKTOK_ACCESS_TOKEN` | Ton TikTok Access Token |
| `SMTP_EMAIL` | yohann.dabi@gmail.com |
| `SMTP_PASSWORD` | L'App Password Gmail (16 chars) |
| `REVIEW_EMAIL` | yohann.dabi@gmail.com |

---

## ÉTAPE 10 — Premier test (10 min)

### 10.1 Test en dry-run (sans générer les vidéos)
1. Aller sur GitHub → onglet "Actions"
2. Cliquer "🔬 Endo Debrief — Weekly Generation"
3. "Run workflow" → activer "Dry run" → "Run workflow"
4. Observer les logs — tu dois voir les articles PubMed trouvés et scorés

### 10.2 Premier vrai run
1. Même workflow, dry_run = false
2. Compter ~45-60 minutes pour tout générer (3 vidéos)
3. Tu recevras un email avec les scripts et liens de téléchargement

### 10.3 Publication manuelle
1. Télécharger les vidéos depuis les Artifacts GitHub
2. Les regarder et valider
3. Si OK : aller dans "Actions" → "🚀 Endo Debrief — Publish Videos"
4. Entrer le numéro du run de génération (visible dans l'URL)
5. Taper "PUBLISH" pour confirmer
6. Les vidéos seront publiées automatiquement

---

## Calendrier hebdomadaire automatique

| Jour | Action |
|------|--------|
| **Lundi 6h UTC** | GitHub Actions démarre la génération |
| **Lundi ~8h UTC** | Tu reçois l'email avec les 3 vidéos |
| **Mardi-Mercredi** | Tu télécharges, regardes, valides |
| **Mercredi** | Tu déclenches la publication |
| **Mercredi-Vendredi** | Vidéos en ligne sur toutes les plateformes |

---

## Coûts mensuels récapitulatifs

| Service | Plan | Coût |
|---------|------|------|
| ElevenLabs | Creator | ~22€ |
| OpenAI API | Pay-as-you-go | ~10€ |
| GitHub | Free | 0€ |
| NCBI / PubMed | Gratuit | 0€ |
| YouTube / Meta / TikTok | Gratuits | 0€ |
| **Total** | | **~32€/mois** |

---

## Problèmes courants

**"No articles found on PubMed"**
→ Élargir la fenêtre temporelle dans `config.py` : `PUBMED_DAYS_BACK = 30`

**"ElevenLabs API key invalid"**
→ Vérifier que le secret GitHub `ELEVENLABS_API_KEY` est bien configuré

**"YouTube quota exceeded"**
→ Attendre 24h. Le quota est de 10 000 unités/jour, un upload = 1 600 unités.

**"Instagram media processing failed"**
→ Vérifier que la vidéo fait moins de 1 Go et moins de 15 minutes. Format MP4/H.264.

**"TikTok access token expired"**
→ Les tokens TikTok expirent. Renouveler via le dashboard développeur TikTok.

---

## Support

Contact : yohann.dabi@gmail.com

Pour signaler un bug : ouvrir une issue sur le repository GitHub.

---
*Endo Debrief — Guide rédigé avec l'assistance de Claude (Anthropic) — Avril 2026*
