"""
config.py — Configuration centrale d'Endo Debrief
Charge les variables d'environnement et définit les constantes du projet.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Charger le fichier .env
load_dotenv()

# ── Chemins ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── APIs ─────────────────────────────────────────────────────────────────────
OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY    = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID   = os.getenv("ELEVENLABS_VOICE_ID", "")
NCBI_API_KEY          = os.getenv("NCBI_API_KEY", "")

YOUTUBE_CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")

META_APP_ID                = os.getenv("META_APP_ID", "")
META_APP_SECRET            = os.getenv("META_APP_SECRET", "")
META_PAGE_ACCESS_TOKEN     = os.getenv("META_PAGE_ACCESS_TOKEN", "")
META_INSTAGRAM_USER_ID     = os.getenv("META_INSTAGRAM_USER_ID", "")
META_FACEBOOK_PAGE_ID      = os.getenv("META_FACEBOOK_PAGE_ID", "")

TIKTOK_ACCESS_TOKEN  = os.getenv("TIKTOK_ACCESS_TOKEN", "")
TIKTOK_OPEN_ID       = os.getenv("TIKTOK_OPEN_ID", "")

SMTP_EMAIL    = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
REVIEW_EMAIL  = os.getenv("REVIEW_EMAIL", "")

# ── Identité éditoriale ───────────────────────────────────────────────────────
CHANNEL_NAME = "Endo Debrief"
CHANNEL_HANDLE = "@EndoDebrief"
DISCLAIMER = (
    "⚠️ For educational purposes only — not medical advice. "
    "Always consult your physician."
)

# ── Articles manuels (proposés par Dr Dabi) ──────────────────────────────────
# Dépose un fichier JSON ici pour forcer l'inclusion d'un article dans la sélection.
# Format : [{"pmid": "12345678", "note": "Raison d'inclusion"}, ...]
MANUAL_ARTICLES_PATH = BASE_DIR / "manual_articles.json"

# ── PubMed search ─────────────────────────────────────────────────────────────
PUBMED_SEARCH_TERMS = [
    "endometriosis",
]
PUBMED_MAX_RESULTS = 50          # Articles récupérés avant scoring
PUBMED_DAYS_BACK   = 14          # Fenêtre de recherche (2 semaines pour ne rien rater)
ARTICLES_PER_WEEK  = 1           # Vidéos à produire par semaine

# ── Modèles OpenAI ────────────────────────────────────────────────────────────
GPT_MODEL        = "gpt-4o"
IMAGE_MODEL      = "dall-e-3"
IMAGE_SIZE       = "1792x1024"   # Format paysage pour slides YouTube
IMAGE_SIZE_SHORT = "1024x1792"   # Format portrait pour TikTok/Reels

# ── Vidéo ─────────────────────────────────────────────────────────────────────
# Format long (YouTube / Facebook)
VIDEO_WIDTH_LONG   = 1920
VIDEO_HEIGHT_LONG  = 1080
VIDEO_FPS          = 30

# Format court 9:16 (TikTok / Instagram Reels)
VIDEO_WIDTH_SHORT  = 1080
VIDEO_HEIGHT_SHORT = 1920

# ── Identité visuelle ─────────────────────────────────────────────────────────
BRAND_COLORS = {
    "primary":     "#6B2D8B",   # Violet endométriose
    "accent":      "#E8A0BF",   # Rose poudré
    "background":  "#0F0F1A",   # Noir bleuté
    "text":        "#F5F5F5",   # Blanc cassé
    "highlight":   "#C084FC",   # Violet clair
    "warning":     "#FCD34D",   # Jaune (points d'attention)
    "success":     "#4ADE80",   # Vert (résultats positifs)
}

# ── YouTube metadata ──────────────────────────────────────────────────────────
YOUTUBE_DEFAULT_TAGS = [
    "endometriosis", "endo", "endometriosis research", "science",
    "women health", "gynecology", "medical research", "endo debrief",
    "pubmed", "scientific paper", "research review", "endometriosis awareness",
]
YOUTUBE_CATEGORY_ID = "28"  # Science & Technology
YOUTUBE_PRIVACY = "private"  # "private" → tu valides → "public" via API

# ── TikTok metadata ───────────────────────────────────────────────────────────
TIKTOK_DEFAULT_HASHTAGS = (
    "#endometriosis #endo #endowarrior #endoresearch #science "
    "#womenshealth #medicalresearch #endodebrief"
)
