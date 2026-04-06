"""
visuals.py — Génération des slides et illustrations visuelles

Crée 2 types de visuels :
1. Slides de marque (PIL) — fond coloré, texte, bullets, logo Endo Debrief
2. Illustrations IA (DALL-E 3) — pour HOOK, BACKGROUND et RESULTS uniquement

Format long (YouTube) : 1920x1080
Format court (Reels/TikTok) : 1080x1920
"""

import io
import os
import logging
import textwrap
import urllib.request
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
import requests
from openai import OpenAI

from . import config
from .script import VideoScript, VideoSection

logger = logging.getLogger(__name__)

# ── Constantes de design ──────────────────────────────────────────────────────
BG_COLOR        = (15, 15, 26)       # #0F0F1A
PRIMARY_COLOR   = (107, 45, 139)     # #6B2D8B
ACCENT_COLOR    = (232, 160, 191)    # #E8A0BF
TEXT_COLOR      = (245, 245, 245)    # #F5F5F5
HIGHLIGHT_COLOR = (192, 132, 252)    # #C084FC
WARNING_COLOR   = (252, 211, 77)     # #FCD34D

# Tailles d'image
LONG_W, LONG_H   = 1920, 1080
SHORT_W, SHORT_H = 1080, 1920


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Charge une police système ou retourne la police par défaut."""
    font_paths = []
    if bold:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        ]

    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

    # Fallback absolu
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _draw_gradient_background(
    draw: ImageDraw.Draw,
    width: int,
    height: int,
    color1: tuple = BG_COLOR,
    color2: tuple = PRIMARY_COLOR,
    direction: str = "diagonal",
):
    """Dessine un fond dégradé."""
    for y in range(height):
        ratio = y / height
        r = int(color1[0] * (1 - ratio * 0.3) + color2[0] * ratio * 0.3)
        g = int(color1[1] * (1 - ratio * 0.3) + color2[1] * ratio * 0.3)
        b = int(color1[2] * (1 - ratio * 0.3) + color2[2] * ratio * 0.3)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def _draw_logo_text(
    draw: ImageDraw.Draw,
    x: int,
    y: int,
    size: int = 28,
):
    """Dessine le logo textuel 'Endo Debrief'."""
    font = _get_font(size, bold=True)
    draw.text((x, y), "ENDO", font=font, fill=PRIMARY_COLOR)
    endo_bbox = draw.textbbox((x, y), "ENDO", font=font)
    draw.text((endo_bbox[2] + 6, y), "DEBRIEF", font=font, fill=ACCENT_COLOR)


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Découpe le texte en lignes avec un maximum de caractères."""
    return textwrap.wrap(text, width=max_chars)


def create_slide_long(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    illustration: Optional[Image.Image] = None,
) -> Image.Image:
    """
    Crée une slide 1920x1080 (format YouTube).
    Si une illustration est fournie, elle est placée à droite.
    """
    img = Image.new("RGB", (LONG_W, LONG_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Fond dégradé
    _draw_gradient_background(draw, LONG_W, LONG_H)

    # Bande colorée latérale gauche
    draw.rectangle([0, 0, 8, LONG_H], fill=PRIMARY_COLOR)

    # Barre de progression en bas
    progress = (slide_index + 1) / total_slides
    draw.rectangle([0, LONG_H - 6, LONG_W, LONG_H], fill=(40, 40, 60))
    draw.rectangle([0, LONG_H - 6, int(LONG_W * progress), LONG_H], fill=PRIMARY_COLOR)

    # Logo en haut à droite
    _draw_logo_text(draw, LONG_W - 300, 30)

    # Zone de texte : toute la largeur ou 60% si illustration
    text_width = int(LONG_W * 0.58) if illustration else int(LONG_W * 0.88)
    text_x = 80

    # Titre de section (petite étiquette colorée)
    section_labels = {
        "HOOK": ("⚡", ACCENT_COLOR),
        "PAPER": ("📄", HIGHLIGHT_COLOR),
        "BACKGROUND": ("🔬", HIGHLIGHT_COLOR),
        "METHODS": ("⚙️", HIGHLIGHT_COLOR),
        "RESULTS": ("📊", ACCENT_COLOR),
        "CRITICAL": ("⚠️", WARNING_COLOR),
        "TAKE_HOME": ("✅", (74, 222, 128)),
        "OUTRO": ("🎬", ACCENT_COLOR),
    }
    emoji, label_color = section_labels.get(section.name, ("•", HIGHLIGHT_COLOR))

    label_font = _get_font(22, bold=True)
    draw.text((text_x, 80), f"{emoji}  {section.name}", font=label_font, fill=label_color)

    # Titre principal
    title_font = _get_font(72, bold=True)
    title_lines = _wrap_text(section.slide_title, 28)
    y = 140
    for line in title_lines[:3]:
        draw.text((text_x, y), line, font=title_font, fill=TEXT_COLOR)
        bbox = draw.textbbox((text_x, y), line, font=title_font)
        y += bbox[3] - bbox[1] + 12

    # Séparateur
    if section.slide_bullets:
        draw.rectangle([text_x, y + 20, text_x + 60, y + 24], fill=PRIMARY_COLOR)
        y += 50

        # Bullets
        bullet_font = _get_font(36)
        for bullet in section.slide_bullets[:4]:
            bullet_lines = _wrap_text(f"› {bullet}", 55)
            for bline in bullet_lines[:2]:
                if y + 50 < LONG_H - 100:
                    draw.text((text_x, y), bline, font=bullet_font, fill=TEXT_COLOR)
                    y += 48

    # Illustration (si disponible) — placée à droite
    if illustration:
        ill_w = int(LONG_W * 0.38)
        ill_h = int(LONG_H * 0.75)
        ill_resized = illustration.resize((ill_w, ill_h), Image.LANCZOS)

        # Masque arrondi pour l'illustration
        ill_x = int(LONG_W * 0.60)
        ill_y = (LONG_H - ill_h) // 2
        img.paste(ill_resized, (ill_x, ill_y))

        # Overlay semi-transparent sur les bords de l'illustration
        for offset in range(30):
            alpha = int(255 * (1 - offset / 30))
            draw.line(
                [(ill_x + offset, ill_y), (ill_x + offset, ill_y + ill_h)],
                fill=(*BG_COLOR, alpha),
            )

    # Disclaimer en bas à gauche (sections finales)
    if section.name in ("TAKE_HOME", "OUTRO"):
        disclaimer_font = _get_font(18)
        draw.text(
            (text_x, LONG_H - 50),
            config.DISCLAIMER,
            font=disclaimer_font,
            fill=(120, 120, 140),
        )

    return img


def create_slide_short(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    illustration: Optional[Image.Image] = None,
) -> Image.Image:
    """
    Crée une slide 1080x1920 (format TikTok/Reels 9:16).
    """
    img = Image.new("RGB", (SHORT_W, SHORT_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    _draw_gradient_background(draw, SHORT_W, SHORT_H)

    # Barre de progression en haut
    progress = (slide_index + 1) / total_slides
    draw.rectangle([0, 0, SHORT_W, 8], fill=(40, 40, 60))
    draw.rectangle([0, 0, int(SHORT_W * progress), 8], fill=PRIMARY_COLOR)

    # Logo en haut au centre
    logo_font = _get_font(32, bold=True)
    draw.text((SHORT_W // 2 - 100, 30), "ENDO DEBRIEF", font=logo_font, fill=ACCENT_COLOR)

    # Illustration en haut (si disponible)
    content_y = 100
    if illustration:
        ill_w = SHORT_W - 80
        ill_h = int(SHORT_H * 0.35)
        ill_resized = illustration.resize((ill_w, ill_h), Image.LANCZOS)
        img.paste(ill_resized, (40, content_y))
        content_y += ill_h + 40

    # Titre
    title_font = _get_font(56, bold=True)
    title_lines = _wrap_text(section.slide_title, 20)
    for line in title_lines[:3]:
        draw.text((60, content_y), line, font=title_font, fill=TEXT_COLOR)
        bbox = draw.textbbox((60, content_y), line, font=title_font)
        content_y += bbox[3] - bbox[1] + 10

    content_y += 30

    # Bullets
    if section.slide_bullets:
        bullet_font = _get_font(34)
        for bullet in section.slide_bullets[:3]:
            bullet_lines = _wrap_text(f"› {bullet}", 30)
            for bline in bullet_lines[:2]:
                if content_y + 45 < SHORT_H - 120:
                    draw.text((60, content_y), bline, font=bullet_font, fill=TEXT_COLOR)
                    content_y += 44

    # Hashtags en bas
    hashtag_font = _get_font(24)
    draw.text(
        (60, SHORT_H - 80),
        "#endometriosis #endodebrief",
        font=hashtag_font,
        fill=HIGHLIGHT_COLOR,
    )

    return img


def _sanitize_dalle_prompt(prompt: str) -> str:
    """
    Reformule les termes anatomiques en langage de diagramme médical didactique
    compatible avec la politique de contenu de DALL-E 3.

    Principe : conserver la précision scientifique (quel organe, quel processus,
    quelle comparaison) en utilisant le vocabulaire des schémas anatomiques
    éducatifs — comme dans un manuel de gynécologie ou une infographie médicale.
    Les illustrations restent fidèles au contenu de l'article ; elles adoptent
    simplement le style d'un diagramme anatomique étiqueté plutôt qu'une image
    clinique directe.
    """
    import re as _re

    # Expressions multi-mots en premier pour éviter les remplacements partiels
    replacements = [
        # Organes — vocabulaire de schéma anatomique éducatif
        ("fallopian tubes",  "fallopian ducts (anatomical schematic)"),
        ("fallopian tube",   "fallopian duct (anatomical schematic)"),
        ("pelvic cavity",    "lower abdominal cavity (anatomical cross-section)"),
        ("uterus",           "uterine organ (labeled anatomical cross-section)"),
        ("uteri",            "uterine organs (anatomical cross-sections)"),
        ("ovaries",          "ovarian structures (anatomical schematics)"),
        ("ovary",            "ovarian structure (anatomical schematic)"),
        ("endometrium",      "endometrial tissue layer (labeled anatomical diagram)"),
        ("endometrial",      "endometrial tissue (anatomical diagram)"),
        ("cervix",           "cervical structure (anatomical cross-section)"),
        ("peritoneum",       "peritoneal cavity lining (anatomical diagram)"),
        ("pelvis",           "lower abdominal region (anatomical diagram)"),
        ("pelvic",           "lower abdominal"),
        ("vagina",           "lower reproductive tract (anatomical schematic)"),
        ("vaginal",          "lower reproductive tract (anatomical schematic)"),

        # Pathologie — visualisation scientifique précise et éducative
        ("endometriosis",    "endometriotic disease (color-coded anatomical map showing tissue distribution)"),
        ("lesions",          "pathological tissue zones (highlighted in anatomical diagram)"),
        ("lesion",           "pathological tissue zone (highlighted in anatomical diagram)"),
        ("implants",         "ectopic tissue deposits (marked on anatomical diagram)"),
        ("implant",          "ectopic tissue deposit (marked on anatomical diagram)"),
        ("adhesions",        "fibrotic tissue bridges (shown in anatomical cross-section)"),
        ("adhesion",         "fibrotic tissue bridge (shown in anatomical cross-section)"),
        ("infiltrating",     "deep-tissue (anatomical diagram)"),
        ("infiltration",     "tissue infiltration depth (anatomical diagram)"),

        # Processus biologiques — style infographique scientifique
        ("hemorrhage",       "fluid accumulation zone (anatomical diagram)"),
        ("bleeding",         "menstrual fluid flow (directional diagram)"),
        ("inflammation",     "inflammatory response zone (color-coded scientific diagram)"),
        ("inflammatory",     "inflammatory (color-coded scientific diagram)"),
        ("blood",            "biological fluid (scientific diagram)"),
        ("painful",          "pain-associated (anatomical pain pathway diagram)"),
        ("pain",             "pain signal pathway (neural diagram)"),
    ]

    sanitized = prompt
    for term, replacement in replacements:
        sanitized = _re.sub(
            r'\b' + _re.escape(term) + r'\b',
            replacement,
            sanitized,
            flags=_re.IGNORECASE
        )

    # Si le prompt décrit une comparaison avant/après (fréquent dans les articles
    # de traitement), ajouter le contexte explicite de diagramme comparatif
    if _re.search(
        r'\b(before|after|comparison|versus|vs\.?|reduction|decrease|increase|improvement)\b',
        sanitized, _re.IGNORECASE
    ):
        sanitized += " — scientific before-after comparison diagram, labeled panels, educational infographic"

    return sanitized


def generate_dalle_illustration(prompt: str, landscape: bool = True) -> Optional[Image.Image]:
    """
    Génère une illustration médicale via DALL-E 3.
    Retourne un objet PIL Image ou None si échec.
    """
    if not prompt or not prompt.strip():
        return None

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    # Sanitiser le prompt pour éviter les violations de la politique DALL-E
    safe_prompt = _sanitize_dalle_prompt(prompt)

    # Style VERROUILLÉ Endo Debrief — identité visuelle cohérente sur toutes les vidéos.
    # NE PAS modifier ce style sans mettre à jour la charte graphique complète.
    ENDO_DEBRIEF_STYLE = (
        "Flat design scientific illustration, minimalist and clean. "
        "Color palette STRICTLY: deep purple (#6B2D8B), rose pink (#E8A0BF), "
        "lavender (#C084FC), white (#F5F5F5) on dark navy background (#0F0F1A). "
        "Style: modern scientific infographic, paper-cut aesthetic, "
        "geometric shapes, smooth gradients. "
        "NO photorealism, NO stock photo style, NO text overlays, NO watermarks. "
        "Think: Vox or Kurzgesagt visual style applied to science communication. "
        "Consistent character design if people are shown: simple, diverse, gender-neutral silhouettes. "
        "High contrast, professional health communication visual."
    )
    styled_prompt = f"{safe_prompt}. {ENDO_DEBRIEF_STYLE}"

    size = "1792x1024" if landscape else "1024x1792"

    try:
        logger.info(f"Generating DALL-E illustration: {prompt[:50]}...")
        response = client.images.generate(
            model=config.IMAGE_MODEL,
            prompt=styled_prompt,
            size=size,
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url

        # Télécharger et convertir en PIL
        img_response = requests.get(image_url, timeout=30)
        img_response.raise_for_status()
        img = Image.open(io.BytesIO(img_response.content)).convert("RGB")

        logger.info("✓ DALL-E illustration generated")
        return img

    except Exception as e:
        logger.warning(f"DALL-E illustration failed (using slide without illustration): {e}")
        return None


def generate_slides_for_script(
    script: VideoScript,
    output_dir: Path,
    generate_short: bool = True,
) -> dict:
    """
    Génère toutes les slides pour un script vidéo.

    Retourne un dict avec les chemins des images sauvegardées :
    {
        "long": [path1, path2, ...],   # slides 16:9
        "short": [path1, path2, ...],  # slides 9:16
    }
    """
    output_dir = Path(output_dir)
    long_dir = output_dir / "slides_long"
    short_dir = output_dir / "slides_short"
    long_dir.mkdir(parents=True, exist_ok=True)
    short_dir.mkdir(parents=True, exist_ok=True)

    long_paths = []
    short_paths = []

    # Sections qui génèrent une illustration DALL-E
    DALLE_SECTIONS = {"HOOK", "BACKGROUND", "RESULTS"}

    total = len(script.sections)

    for i, section in enumerate(script.sections):
        logger.info(f"Creating slides for section {section.name} ({i+1}/{total})...")

        # Générer une illustration si nécessaire
        illustration_landscape = None
        illustration_portrait = None

        if section.name in DALLE_SECTIONS and section.visual_prompt:
            illustration_landscape = generate_dalle_illustration(
                section.visual_prompt, landscape=True
            )
            if generate_short and illustration_landscape:
                # Adapter le ratio pour le format court
                illustration_portrait = illustration_landscape.resize(
                    (1080, 810), Image.LANCZOS
                )

        # Slide format long
        slide_long = create_slide_long(section, i, total, illustration_landscape)
        long_path = long_dir / f"slide_{i:02d}_{section.name}.png"
        slide_long.save(long_path, "PNG", quality=95)
        long_paths.append(str(long_path))

        # Slide format court
        if generate_short:
            slide_short = create_slide_short(section, i, total, illustration_portrait)
            short_path = short_dir / f"slide_{i:02d}_{section.name}.png"
            slide_short.save(short_path, "PNG", quality=95)
            short_paths.append(str(short_path))

    logger.info(
        f"✓ Generated {len(long_paths)} long slides and {len(short_paths)} short slides"
    )

    return {"long": long_paths, "short": short_paths}
