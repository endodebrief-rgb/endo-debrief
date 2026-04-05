# BRIEF DE RÉFÉRENCE — ENDO DEBRIEF
*Document de référence technique et éditorial — v2.0 — Avril 2026*

---

## Historique des versions

| Version | Date | Modifications |
|---------|------|---------------|
| v1.0 | Avril 2026 | Version initiale — articles PubMed uniquement |
| v2.0 | Avril 2026 | Ajout accès texte intégral, guidelines cliniques, essais cliniques ClinicalTrials.gov, scoring unifié multi-sources, recherche élargie automatique |

---

## 1. Description du projet

**Endo Debrief** est un programme d'automatisation end-to-end qui produit chaque semaine 3 vidéos de vulgarisation scientifique sur l'endométriose, publiées simultanément sur YouTube, Instagram, TikTok et Facebook.

Chaque vidéo décrypte un contenu scientifique récent — article de recherche, recommandation clinique ou essai clinique — avec une narration adaptée à son type : contexte, méthodologie, résultats, et une revue critique honnête. Le format combine des slides animées, des illustrations générées par IA, et la voix clonée du Dr Yohann Dabi.

**Cible** :
- Primaire : patientes atteintes d'endométriose (communauté anglophone mondiale)
- Secondaire : communauté scientifique et médicale internationale

**Objectif** : devenir la référence de vulgarisation scientifique sur l'endométriose — forte visibilité algorithmique, crédibilité médicale.

---

## 2. Types de contenus produits

Le pipeline gère **3 types de contenus distincts**, chacun avec sa propre structure narrative :

### 🔬 Type 1 — Article de recherche (PubMed)
Études originales, revues systématiques, méta-analyses publiées sur PubMed.
Structure : Hook → Présentation article → Contexte → Méthodes → Résultats → Critique → Conclusion.

### 📋 Type 2 — Recommandation clinique (Guidelines)
Nouvelles recommandations d'organismes de référence (ESHRE, ACOG, RCOG, Cochrane, HAS...).
Structure : Hook → Contexte organisationnel → Anciennes vs nouvelles recommandations → Impact concret pour les patientes → Points de débat → À retenir.

### 🧪 Type 3 — Essai clinique (ClinicalTrials.gov)
Essais en recrutement, essais complétés avec résultats disponibles, nouveaux essais enregistrés.
Structure narrative adaptée au statut :
- **En recrutement** → axe participation patient ("Puis-je m'inscrire ?")
- **Résultats disponibles** → axe données primaires ("Qu'ont-ils trouvé ?")
- **Nouveau essai** → axe signal de recherche ("Où va la science ?")

---

## 3. Architecture du pipeline

```
[LUNDI 6h UTC — GitHub Actions déclenche le pipeline]
          │
          ▼
┌─────────────────────────────────────────────────────┐
│            COLLECTE MULTI-SOURCES (Étape 1)         │
│                                                     │
│  🔬 PubMed (NCBI E-utilities)                       │
│     → Articles endométriose (14 jours par défaut)   │
│     → Élargissement auto à 60 jours si < 2 full-text│
│                                                     │
│  📋 Guidelines (PubMed + ESHRE + Cochrane)          │
│     → Fenêtre 180 jours (guidelines rares)          │
│     → Filtre : Practice Guideline, Meta-Analysis,   │
│       Systematic Review, Consensus Conference       │
│                                                     │
│  🧪 ClinicalTrials.gov API v2                       │
│     → Essais complétés avec résultats (180 jours)  │
│     → Essais en recrutement actif (90 jours)        │
│     → Nouveaux essais enregistrés (30 jours)        │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
          ┌─────────────────────┐
          │  SCORING UNIFIÉ     │  → GPT-4o évalue tous les items
          │  GPT-4o (scorer_v2) │    ensemble (articles + guidelines
          │                     │    + trials) avec bonus par type
          │  Quotas par type :  │    Sélectionne les 3 meilleurs
          │  • ≥1 article       │    en assurant la diversité
          │  • ≤1 guideline     │    thématique
          │  • ≤1 trial         │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  ACCÈS TEXTE        │  Cascade pour articles de recherche :
          │  INTÉGRAL           │  1. PubMed Central (XML structuré)
          │  (fulltext.py)      │  2. Europe PMC
          │                     │  3. Unpaywall (PDF Open Access)
          │                     │  4. PDF uploadé manuellement
          │                     │  5. Abstract uniquement (fallback)
          └──────────┬──────────┘
                     │ ⚠ Si payant → email Dr Dabi avec instructions
                     ▼
          ┌─────────────────────┐
          │  GÉNÉRATION SCRIPT  │  → GPT-4o génère script adapté
          │  GPT-4o             │    au type de contenu
          │                     │    Utilise le texte intégral quand
          │                     │    disponible (critique méthodologique
          │                     │    plus précise)
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  VISUELS            │  → PIL : slides de marque
          │  PIL + DALL-E 3     │    DALL-E : illustrations médicales
          │                     │    2 formats : 16:9 + 9:16
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  VOIX               │  → ElevenLabs (voix clonée Dr Dabi)
          │  ElevenLabs         │    Audio par section + version courte
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  ASSEMBLAGE VIDÉO   │  → MoviePy : slides + voix + transitions
          │  MoviePy            │    video_long.mp4 (YouTube/Facebook)
          │                     │    video_short.mp4 (Reels/TikTok)
          │                     │    thumbnail.jpg
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  VALIDATION         │  → Email HTML au Dr Dabi :
          │  review.py          │    • Scripts des 3 vidéos
          │                     │    • Articles payants à sourcer
          │                     │    • review_manifest.json éditable
          └──────────┬──────────┘
                     │ [Dr Dabi valide → déclenche "Publish" sur GitHub]
                     ▼
          ┌─────────────────────┐
          │  PUBLICATION        │  → YouTube (16:9 + thumbnail)
          │  publisher.py       │    Instagram Reels (9:16)
          │                     │    TikTok (9:16)
          │                     │    Facebook Page (16:9)
          └─────────────────────┘
```

---

## 4. Gestion de l'accès au texte intégral

L'accès au texte intégral est **indispensable** pour une revue critique méthodologique rigoureuse. Le pipeline utilise une cascade de 4 niveaux :

| Niveau | Source | Couverture estimée | Coût |
|--------|--------|--------------------|------|
| 1 | PubMed Central (PMC) | ~50% des articles endo | Gratuit |
| 2 | Europe PMC | +10-15% supplémentaires | Gratuit |
| 3 | Unpaywall (Open Access légal) | +5-10% supplémentaires | Gratuit |
| 4 | PDF uploadé manuellement | Selon disponibilité | Manuel |
| Fallback | Abstract uniquement | Toujours disponible | — |

**Workflow pour les articles payants** :
1. L'email de validation liste les articles sans accès intégral
2. Le Dr Dabi dépose le PDF dans `pdf_uploads/{PMID}.pdf`
3. Relance de la génération → pipeline utilise le PDF
4. Voies d'accès légales : accès institutionnel, ResearchGate, email aux auteurs, Open Access Button

**Impact sur le script** : GPT-4o est explicitement instruit d'être transparent en cas d'accès abstract-only, et de ne pas spéculer sur les détails méthodologiques.

**Recherche élargie automatique** : si moins de 2 articles des 14 derniers jours ont un texte intégral disponible sur PMC, le pipeline étend automatiquement la fenêtre à 60 jours pour trouver du contenu de qualité.

---

## 5. Choix techniques retenus

| Composant | Solution retenue | Justification |
|-----------|-----------------|---------------|
| Orchestration | GitHub Actions (cron hebdomadaire) | Gratuit, fiable, sans serveur permanent |
| Articles de recherche | NCBI E-utilities API | Gratuit, accès direct PubMed |
| Guidelines | PubMed (filtres publication type) + ESHRE scraping + Cochrane | Multi-source, couverture maximale |
| Essais cliniques | ClinicalTrials.gov API v2 | API officielle, gratuite, temps réel |
| Texte intégral | PMC → Europe PMC → Unpaywall → PDF manuel | Cascade légale, coût zéro |
| Extraction PDF | pypdf | Léger, sans dépendance externe |
| Scoring | OpenAI GPT-4o (scorer unifié) | Un seul scoring pour tous les types |
| Génération scripts | OpenAI GPT-4o (3 templates distincts) | Adapté à chaque type de contenu |
| Génération images | DALL-E 3 + PIL/Pillow | DALL-E pour illustrations, PIL pour slides |
| Voix | ElevenLabs API (Creator plan) | Voice cloning de la voix du Dr Dabi |
| Assemblage vidéo | MoviePy (Python) | Gratuit, flexible |
| Publication | YouTube Data v3, Meta Graph API, TikTok API | Automatisation native officielle |
| Notifications | Gmail SMTP | Simple, sans infrastructure |
| Stockage temporaire | GitHub Actions Artifacts | Gratuit, 7 jours de rétention |

---

## 6. APIs utilisées

### 6.1 NCBI E-utilities (PubMed + PMC)
- **URL** : `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- **Auth** : API key optionnelle (gratuite sur NCBI) — 3 → 10 req/s
- **Endpoints** : `esearch.fcgi`, `efetch.fcgi`, `elink.fcgi`
- **Usage** : Recherche articles, récupération abstracts, vérification PMC, texte intégral PMC
- **Coût** : Gratuit

### 6.2 ClinicalTrials.gov API v2
- **URL** : `https://clinicaltrials.gov/api/v2/`
- **Auth** : Aucune (API publique)
- **Endpoints** : `GET /studies`, `GET /studies/{nctId}`
- **Usage** : Essais en recrutement, complétés avec résultats, nouveaux essais
- **Coût** : Gratuit

### 6.3 Unpaywall API
- **URL** : `https://api.unpaywall.org/v2/{doi}`
- **Auth** : Email de contact (obligatoire, pas de clé)
- **Usage** : Détection et téléchargement des versions Open Access légales
- **Coût** : Gratuit

### 6.4 Europe PMC REST API
- **URL** : `https://www.ebi.ac.uk/europepmc/webservices/rest/`
- **Auth** : Aucune
- **Usage** : Texte intégral des articles non disponibles sur PMC US
- **Coût** : Gratuit

### 6.5 OpenAI API
- **Modèle** : `gpt-4o` pour scoring + 3 types de scripts, `dall-e-3` pour images
- **Auth** : API key (depuis platform.openai.com)
- **Usage estimé** : ~12 scripts/mois + scoring ~50 items/semaine + ~24 images/mois
- **Coût estimé** : ~10-15€/mois

### 6.6 ElevenLabs API
- **Plan** : Creator (~22€/mois) — 100 000 caractères/mois
- **Feature** : Instant Voice Cloning (voix du Dr Dabi)
- **Endpoint** : `/v1/text-to-speech/{voice_id}`
- **Usage estimé** : ~12 scripts × ~6 000 chars = ~72 000 chars/mois ✓
- **Coût** : ~22€/mois

### 6.7 YouTube Data API v3
- **Auth** : OAuth2 (Google Cloud Console)
- **Endpoints** : `videos.insert`, `thumbnails.set`
- **Quota** : 10 000 unités/jour (upload = 1 600 unités)
- **Coût** : Gratuit

### 6.8 Meta Graph API (Instagram + Facebook)
- **Auth** : Page Access Token long-lived (Facebook Business)
- **Endpoints** : `/{ig-user-id}/media`, `/{ig-user-id}/media_publish`, `/{page-id}/videos`
- **Prérequis** : Compte Instagram Business + Page Facebook + App Meta validée
- **Coût** : Gratuit

### 6.9 TikTok Content Posting API
- **Auth** : OAuth2 (TikTok for Developers)
- **Endpoints** : `v2/post/publish/video/init/`, upload direct
- **Prérequis** : Compte développeur TikTok + approbation (1-2 semaines)
- **Coût** : Gratuit

---

## 7. Structure des vidéos par type de contenu

### 🔬 Article de recherche — Format long (4-6 min)
```
[0:00–0:15]  HOOK          — Stat choc ou question provocante
[0:15–0:35]  PAPER INTRO   — Journal, auteurs, institution
[0:35–1:15]  BACKGROUND    — Pourquoi ce sujet compte pour les patients
[1:15–1:50]  METHODS       — Design de l'étude en langage simple
[1:50–3:00]  RESULTS       — Résultats clés avec données chiffrées
[3:00–3:45]  CRITICAL      — Limites, biais, nuances — basé sur texte intégral si dispo
[3:45–4:10]  TAKE-HOME     — 1 message patient + 1 message scientifique
[4:10–4:20]  OUTRO
```

### 📋 Recommandation clinique — Format long (4-6 min)
```
[0:00–0:15]  HOOK          — Ce que ça change pour les patientes
[0:15–0:40]  CONTEXT       — Organisme émetteur, autorité, portée géographique
[0:40–1:15]  BACKGROUND    — Pourquoi une mise à jour était nécessaire
[1:15–2:35]  CHANGES       — Les nouvelles recommandations clé par clé
[2:35–3:25]  IMPACT        — Ce que ça change concrètement (à demander au médecin)
[3:25–4:05]  CRITICAL      — Points de débat, ce qui reste incertain
[4:05–4:25]  TAKE-HOME     — Ce que toute patiente doit retenir
[4:25–4:35]  OUTRO
```

### 🧪 Essai clinique — Format long (4-5 min)
```
[0:00–0:15]  HOOK          — L'essai qui pourrait changer le traitement
[0:15–0:37]  TRIAL INFO    — NCT ID, phase, sponsor, lieux
[0:37–1:15]  HYPOTHESIS    — Quelle hypothèse teste-t-on ? Pourquoi ?
[1:15–2:00]  DESIGN        — Comment l'essai est conçu
[2:00–2:48]  WHAT TESTED   — L'intervention à l'étude
[2:48–3:20]  TIMELINE      — Dates, recrutement, comment participer
[3:20–4:00]  CRITICAL      — Biais potentiels, phase précoce ≠ efficacité
[4:00–4:25]  TAKE-HOME     — Puis-je participer ? / Qu'est-ce que ça signifie ?
[4:25–4:35]  OUTRO
```

### Format court 9:16 (Reels + TikTok) — 70-90 secondes
Même structure condensée pour tous les types : Hook → Finding/Change clé → Nuance → Take-home + CTA.

---

## 8. Politique de sélection hebdomadaire

Le scorer unifié sélectionne les 3 meilleures vidéos de la semaine selon ces règles :

| Règle | Valeur |
|-------|--------|
| Minimum articles de recherche | 1 par semaine |
| Maximum articles de recherche | 3 par semaine |
| Maximum guidelines | 1 par semaine |
| Maximum essais cliniques | 1 par semaine |
| Maximum doublons thématiques | 1 par topic_tag |

**Critères de scoring GPT-4o** (0-10 chacun, total /40) :
- `scientific_impact` : rigueur méthodologique, niveau de preuve, prestige de la source
- `patient_relevance` : impact concret sur la vie ou le traitement des patientes
- `pedagogical_value` : accessibilité, clarté visuelle, nouveauté pour l'audience
- `viral_potential` : accroche, résonance émotionnelle, partageabilité

**Bonus appliqués** : guideline ESHRE/ACOG/Cochrane (+1 scientific_impact), essai en recrutement (+2 patient_relevance), essai avec résultats (+2 scientific_impact).

---

## 9. Identité visuelle

| Élément | Valeur |
|---------|--------|
| Couleur principale | `#6B2D8B` (violet endométriose) |
| Couleur accent | `#E8A0BF` (rose poudré) |
| Couleur fond | `#0F0F1A` (noir bleuté) |
| Couleur texte | `#F5F5F5` (blanc cassé) |
| Couleur highlight | `#C084FC` (violet clair) |
| Police titre | Montserrat Bold |
| Police corps | Inter Regular |
| Logo | "Endo Debrief" — typographie + symbole ADN stylisé |

---

## 10. Structure des fichiers du projet

```
endo-debrief/
├── endo_debrief/
│   ├── config.py          — Configuration centrale, variables d'environnement
│   ├── content_types.py   — Classes unifiées ContentItem, ScoredContentItem
│   ├── pubmed.py          — Recherche PubMed + fallback période élargie
│   ├── recommendations.py — Guidelines (PubMed, ESHRE, Cochrane)
│   ├── clinicaltrials.py  — Essais cliniques (ClinicalTrials.gov API v2)
│   ├── fulltext.py        — Accès texte intégral (cascade PMC→Unpaywall→PDF)
│   ├── scorer_v2.py       — Scoring GPT-4o unifié multi-sources
│   ├── script.py          — Génération scripts (3 templates par type)
│   ├── visuals.py         — Slides PIL + illustrations DALL-E 3
│   ├── voice.py           — Synthèse vocale ElevenLabs
│   ├── video.py           — Assemblage vidéo MoviePy
│   ├── review.py          — Email validation + review_manifest.json
│   ├── publisher.py       — Publication YouTube/Instagram/TikTok/Facebook
│   └── pipeline.py        — Orchestration complète (modes generate/publish)
├── .github/workflows/
│   ├── weekly_generate.yml — Cron lundi 6h UTC + déclenchement manuel
│   └── publish.yml         — Publication après validation manuelle
├── pdf_uploads/            — PDFs d'articles payants déposés par le Dr Dabi
│   └── {PMID}.pdf
├── output/                 — Vidéos, slides, audio générés (ignoré par git)
├── BRIEF.md               — Ce document
├── SETUP_GUIDE.md         — Guide d'installation pas-à-pas
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 11. Estimation des coûts mensuels

| Service | Plan | Coût/mois |
|---------|------|-----------|
| ElevenLabs | Creator (voice cloning) | ~22€ |
| OpenAI API | Pay-as-you-go (GPT-4o + DALL-E 3) | ~12€ |
| GitHub Actions | Free tier | 0€ |
| NCBI / PubMed / PMC | Gratuit | 0€ |
| ClinicalTrials.gov API | Gratuit | 0€ |
| Unpaywall API | Gratuit | 0€ |
| Europe PMC | Gratuit | 0€ |
| YouTube / Meta / TikTok APIs | Gratuits | 0€ |
| **TOTAL** | | **~34€/mois** |

---

## 12. Évolutions prévues

### Phase 2 (mois 3-6)
- [ ] Sous-titres automatiques (Whisper API) pour accessibilité
- [ ] Thread X (Twitter) accompagnant chaque vidéo
- [ ] Newsletter hebdomadaire automatisée (Substack ou SendGrid)
- [ ] Dashboard analytics consolidé (vues, engagement, croissance)
- [ ] Base de données des contenus déjà traités (éviter les doublons)

### Phase 3 (mois 6-12)
- [ ] Upgrade vers HeyGen pour avatar IA du Dr Dabi (si budget augmente)
- [ ] SEO YouTube automatisé (titres, descriptions, tags optimisés)
- [ ] Collaboration avec patient advocacy groups (contenu co-brandé)
- [ ] Traduction automatique ES/FR pour expansion internationale
- [ ] Alertes immédiates pour publications très haut impact (Nature, NEJM, Lancet)

### Phase 4 (long terme)
- [ ] Application web Endo Debrief avec archive de tous les contenus
- [ ] Système de suggestion de sujets par la communauté
- [ ] Monétisation : YouTube Partner Program, sponsoring institutionnel
- [ ] Partenariats académiques (ESHRE, ASRM, sociétés savantes)

---

## 13. Considérations éthiques et légales

- **Droits d'auteur** : seuls les textes en Open Access légal sont utilisés (PMC, Europe PMC, Unpaywall). Aucun contournement de paywall. Les PDFs uploadés manuellement sont obtenus par voies légales (accès institutionnel, demande aux auteurs).
- **Exactitude médicale** : chaque script généré par IA est relu et validé par le Dr Dabi avant publication. Le pipeline est explicitement transparent sur les limites d'un accès abstract-only.
- **Disclaimer** : chaque vidéo porte la mention *"For educational purposes only — not medical advice"*.
- **Transparence IA** : mention de l'assistance IA dans les descriptions de toutes les vidéos.
- **Essais cliniques** : les informations sur les essais (critères d'inclusion, contacts) sont strictement issues de ClinicalTrials.gov — jamais modifiées ou interprétées au-delà de ce qui est enregistré.
- **RGPD** : aucune collecte de données utilisateurs dans ce pipeline.

---

*Endo Debrief — Dr Yohann Dabi — yohann.dabi@gmail.com*
*Brief rédigé et maintenu avec l'assistance de Claude (Anthropic) — Avril 2026*
