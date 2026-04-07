"""
visuals.py — Génération des slides — refonte v2

Approche : slides entièrement programmatiques (Pillow + matplotlib).
Plus de DALL-E pour le contenu principal — chaque slide transmet des données réelles
comme dans une présentation de congrès scientifique.

Structure des slides par section :
  INTRO      → Slide de couverture : titre, auteurs, journal, badges (type étude, N=, année)
  HOOK       → Grande stat choc sur fond sombre
  PAPER      → Réservé à INTRO (absorbé)
  BACKGROUND → Slide texte avec contexte
  METHODS    → Infographie étude : design, N, centres, durée, critère principal
  RESULTS    → Stat cards ou tableau de résultats clés avec les vrais nombres
  CRITICAL   → Tableau comparatif "cette étude vs littérature"
  TAKE_HOME  → Grand message final
  OUTRO      → Branding Endo Debrief

Format long  (YouTube) : 1920×1080
Format court (TikTok)  : 1080×1920
"""

import io
import logging
import os
import textwrap
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # pas de display server sur CI/GitHub Actions
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import matplotlib.font_manager as fm
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from . import config
from .script import VideoScript, VideoSection

logger = logging.getLogger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
# Fond principal : blanc / lavande très clair — style académique propre
C_WHITE       = (255, 255, 255)
C_BG_LIGHT    = (248, 245, 255)    # lavande ultra-clair
C_BG_DARK     = (15,  15,  26)     # quasi-noir pour certains effets
C_HEADER      = (72,  18, 110)     # violet foncé — en-tête de slide
C_PURPLE      = (107, 45, 139)     # violet principal
C_PURPLE_MID  = (150, 90, 180)     # violet moyen
C_LILAC       = (192, 132, 252)    # violet clair
C_PINK        = (232, 160, 191)    # rose
C_YELLOW      = (252, 211, 77)     # jaune accent
C_GREEN       = (74,  222, 128)    # vert résultats positifs
C_RED         = (248, 113, 113)    # rouge avertissement
C_TEXT_DARK   = (20,  10,  30)     # texte principal sur fond clair
C_TEXT_LIGHT  = (245, 245, 245)    # texte sur fond sombre
C_TEXT_MUTED  = (120, 100, 140)    # texte secondaire
C_BORDER      = (220, 210, 235)    # bords de panels

# Hex pour matplotlib
HEX_PURPLE    = "#6B2D8B"
HEX_HEADER    = "#48126E"
HEX_PINK      = "#E8A0BF"
HEX_LILAC     = "#C084FC"
HEX_YELLOW    = "#FCD34D"
HEX_GREEN     = "#4ADE80"
HEX_RED       = "#F87171"
HEX_BG        = "#F8F5FF"
HEX_TEXT      = "#140A1E"

# Tailles des images
LONG_W, LONG_H   = 1920, 1080
SHORT_W, SHORT_H = 1080, 1920

# Hauteur de l'en-tête violet (haut de chaque slide)
HEADER_H = 88


# ── Utilitaires typographie ───────────────────────────────────────────────────

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Charge une police système (DejaVu ou Liberation)."""
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _wrap(text: str, max_chars: int) -> list[str]:
    return textwrap.wrap(text, width=max_chars) or [""]


def _draw_text_block(
    draw: ImageDraw.Draw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    color: tuple,
    max_chars: int,
    line_spacing: int = 8,
) -> int:
    """Dessine un bloc de texte wrappé, retourne le y final."""
    for line in _wrap(text, max_chars):
        draw.text((x, y), line, font=font, fill=color)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing
    return y


def _pill_badge(
    draw: ImageDraw.Draw,
    text: str,
    x: int,
    y: int,
    bg: tuple,
    fg: tuple,
    font: ImageFont.FreeTypeFont,
    padding: int = 14,
) -> int:
    """Dessine un badge rectangulaire arrondi. Retourne la largeur totale."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    w = tw + padding * 2
    h = th + padding
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    draw.text((x + padding, y + padding // 2), text, font=font, fill=fg)
    return w


# ── En-tête commun ────────────────────────────────────────────────────────────

def _draw_header(
    draw: ImageDraw.Draw,
    width: int,
    section_label: str,
    section_emoji: str,
    slide_num: int,
    total: int,
):
    """Bande d'en-tête violette + label de section + numéro de slide."""
    draw.rectangle([0, 0, width, HEADER_H], fill=C_HEADER)

    # Logo Endo Debrief (gauche)
    logo_f = _font(28, bold=True)
    draw.text((32, 28), "ENDO", font=logo_f, fill=C_PINK)
    bbox = draw.textbbox((32, 28), "ENDO", font=logo_f)
    draw.text((bbox[2] + 8, 28), "DEBRIEF", font=logo_f, fill=C_LILAC)

    # Label de section (centre)
    sec_f = _font(26, bold=True)
    sec_text = f"{section_emoji}  {section_label.upper()}"
    sec_bbox = draw.textbbox((0, 0), sec_text, font=sec_f)
    sec_x = (width - (sec_bbox[2] - sec_bbox[0])) // 2
    draw.text((sec_x, 30), sec_text, font=sec_f, fill=C_TEXT_LIGHT)

    # Numéro de slide (droite)
    num_f = _font(22)
    num_text = f"{slide_num} / {total}"
    num_bbox = draw.textbbox((0, 0), num_text, font=num_f)
    draw.text((width - num_bbox[2] - 32, 32), num_text, font=num_f, fill=C_LILAC)

    # Ligne de séparation
    draw.rectangle([0, HEADER_H, width, HEADER_H + 3], fill=C_PURPLE)


def _draw_footer(draw: ImageDraw.Draw, width: int, height: int, meta: dict):
    """Barre de bas de slide avec source (journal, DOI)."""
    footer_h = 40
    draw.rectangle([0, height - footer_h, width, height], fill=C_BG_DARK)
    source_parts = []
    if meta.get("journal_short"):
        source_parts.append(meta["journal_short"])
    if meta.get("year"):
        source_parts.append(meta["year"])
    if meta.get("doi"):
        source_parts.append(f"DOI: {meta['doi']}")
    source_text = "  ·  ".join(source_parts) if source_parts else ""
    if source_text:
        f_small = _font(18)
        draw.text((32, height - footer_h + 10), source_text, font=f_small, fill=C_TEXT_MUTED)
    # Disclaimer à droite
    disc_f = _font(16)
    disc = "For educational purposes only — not medical advice"
    disc_bbox = draw.textbbox((0, 0), disc, font=disc_f)
    draw.text(
        (width - disc_bbox[2] - 32, height - footer_h + 11),
        disc, font=disc_f, fill=C_TEXT_MUTED,
    )


# ── SLIDE INTRO (remplace la slide PAPER) ────────────────────────────────────

def create_intro_slide(script: VideoScript, width: int, height: int) -> Image.Image:
    """
    Slide de présentation de l'article — style affiche de congrès :
    - Titre complet de l'article (en haut, grand)
    - Auteurs + journal
    - Badges : type d'étude, N=, année, pays
    """
    meta = script.article_metadata or {}

    img = Image.new("RGB", (width, height), C_BG_LIGHT)
    draw = ImageDraw.Draw(img)

    # En-tête
    _draw_header(draw, width, "THE STUDY", "📄", 1, 1)

    content_y = HEADER_H + 50
    margin = 80

    # ── Titre de l'article ──────────────────────────────────────────────────
    title_text = meta.get("full_title", script.article_title)
    title_font = _font(56, bold=True)

    # Découpe le titre sur max 3 lignes
    title_lines = _wrap(title_text, 55)[:4]
    for line in title_lines:
        draw.text((margin, content_y), line, font=title_font, fill=C_HEADER)
        bbox = draw.textbbox((margin, content_y), line, font=title_font)
        content_y += (bbox[3] - bbox[1]) + 14
    content_y += 20

    # Séparateur violet
    draw.rectangle([margin, content_y, margin + 120, content_y + 5], fill=C_PURPLE)
    content_y += 30

    # ── Auteurs + Journal ───────────────────────────────────────────────────
    authors = meta.get("authors", [])
    if isinstance(authors, list):
        author_str = ", ".join(str(a) for a in authors[:4])
        if len(authors) > 4:
            author_str += " et al."
    else:
        author_str = str(authors)

    auth_f = _font(34)
    if author_str:
        draw.text((margin, content_y), author_str, font=auth_f, fill=C_PURPLE)
        bbox = draw.textbbox((margin, content_y), author_str, font=auth_f)
        content_y += (bbox[3] - bbox[1]) + 12

    journal_str = meta.get("journal_full", meta.get("journal_short", ""))
    if journal_str:
        year = meta.get("year", "")
        jtext = f"{journal_str}  —  {year}" if year else journal_str
        draw.text((margin, content_y), jtext, font=auth_f, fill=C_TEXT_MUTED)
        bbox = draw.textbbox((margin, content_y), jtext, font=auth_f)
        content_y += (bbox[3] - bbox[1]) + 36

    # ── Badges ──────────────────────────────────────────────────────────────
    badge_f = _font(26, bold=True)
    badge_x = margin

    def badge(text: str, bg: tuple, fg: tuple = C_TEXT_LIGHT) -> int:
        nonlocal badge_x
        w = _pill_badge(draw, text, badge_x, content_y, bg, fg, badge_f, padding=16)
        badge_x += w + 16
        return w

    study_type = meta.get("study_type", "")
    if study_type:
        badge(study_type, C_HEADER)

    n_patients = meta.get("n_patients", 0)
    if n_patients and int(n_patients) > 0:
        badge(f"N = {int(n_patients):,} {meta.get('n_label','patients')}", C_PURPLE)

    country = meta.get("country", "")
    if country:
        badge(country, C_PURPLE_MID)

    year = meta.get("year", "")
    if year:
        badge(year, (100, 60, 130))

    content_y += 70

    # ── DOI ─────────────────────────────────────────────────────────────────
    doi = meta.get("doi", "")
    if doi:
        doi_f = _font(22)
        draw.text((margin, content_y), f"DOI: {doi}", font=doi_f, fill=C_TEXT_MUTED)

    # ── Pied de page ────────────────────────────────────────────────────────
    _draw_footer(draw, width, height, meta)

    return img


# ── SLIDE STANDARD (texte + bullets) ─────────────────────────────────────────

def create_text_slide(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    meta: dict,
    width: int,
    height: int,
) -> Image.Image:
    """
    Slide standard avec titre + bullets — fond blanc, en-tête violet.
    Utilisée pour : HOOK, BACKGROUND, TAKE_HOME, OUTRO.
    """
    SECTION_META = {
        "HOOK":       ("⚡", "HOOK"),
        "BACKGROUND": ("🔬", "BACKGROUND"),
        "CRITICAL":   ("⚠️", "CRITICAL REVIEW"),
        "TAKE_HOME":  ("✅", "TAKE-HOME"),
        "OUTRO":      ("🎬", "ENDO DEBRIEF"),
    }
    emoji, label = SECTION_META.get(section.name, ("•", section.name))

    img = Image.new("RGB", (width, height), C_BG_LIGHT)
    draw = ImageDraw.Draw(img)

    _draw_header(draw, width, label, emoji, slide_index + 1, total_slides)
    _draw_footer(draw, width, height, meta)

    margin = 80
    content_y = HEADER_H + 50

    # Titre de la slide
    title_font = _font(64 if width == LONG_W else 50, bold=True)
    content_y = _draw_text_block(
        draw, section.slide_title,
        margin, content_y, title_font, C_HEADER,
        max_chars=40 if width == LONG_W else 22,
        line_spacing=14,
    )
    content_y += 20

    # Trait de séparation
    draw.rectangle([margin, content_y, margin + 80, content_y + 5], fill=C_PURPLE)
    content_y += 30

    # Bullets
    bullet_font = _font(38 if width == LONG_W else 30)
    for bullet in section.slide_bullets[:5]:
        # Puce colorée
        draw.ellipse([margin, content_y + 14, margin + 14, content_y + 28], fill=C_PURPLE)
        remaining_y = content_y
        for line in _wrap(bullet, 70 if width == LONG_W else 30)[:3]:
            draw.text((margin + 28, remaining_y), line, font=bullet_font, fill=C_TEXT_DARK)
            bbox = draw.textbbox((margin + 28, remaining_y), line, font=bullet_font)
            remaining_y += (bbox[3] - bbox[1]) + 6
        content_y = remaining_y + 16

    return img


# ── SLIDE MÉTHODES — Infographie ──────────────────────────────────────────────

def create_methods_slide(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    meta: dict,
    width: int,
    height: int,
) -> Image.Image:
    """
    Infographie de design de l'étude :
    boîtes colorées avec les caractéristiques clés.
    """
    chart_data = section.chart_data or {}

    # Données à afficher (depuis chart_data ou article_metadata)
    sd = chart_data.get("study_type", meta.get("study_type", "Observational study"))
    n  = chart_data.get("n", meta.get("n_patients", 0))
    n_label = chart_data.get("n_label", meta.get("n_label", "patients"))
    centers = chart_data.get("centers", 0)
    period  = chart_data.get("period", "")
    followup = chart_data.get("followup", "")
    primary_outcome = chart_data.get("primary_outcome", meta.get("primary_outcome", ""))

    # Construire les tuiles
    tiles = [
        {"title": "STUDY DESIGN", "value": sd, "color": HEX_HEADER},
        {"title": "PARTICIPANTS", "value": f"{int(n):,}" if n else "—", "sub": n_label, "color": HEX_PURPLE},
    ]
    if centers:
        tiles.append({"title": "CENTERS", "value": str(centers), "sub": "centers", "color": "#7B3FAB"})
    if period:
        tiles.append({"title": "PERIOD", "value": period, "color": "#9A5CC0"})
    if followup:
        tiles.append({"title": "FOLLOW-UP", "value": followup, "color": "#B47DD4"})
    if primary_outcome:
        tiles.append({"title": "PRIMARY ENDPOINT", "value": primary_outcome, "color": "#C084FC", "full_width": True})

    # Figure matplotlib
    dpi = 150
    fig_w = width / dpi
    fig_h = (height - HEADER_H - 40) / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(HEX_BG)
    ax.set_facecolor(HEX_BG)
    ax.axis("off")

    cols = min(len(tiles), 3)
    rows = (len(tiles) + cols - 1) // cols

    tile_w = 0.9 / cols
    tile_h = 0.82 / rows
    padding = 0.03

    for idx, tile in enumerate(tiles):
        row = idx // cols
        col = idx % cols

        if tile.get("full_width"):
            x0 = 0.05
            tile_width_used = 0.90
        else:
            x0 = 0.05 + col * (tile_w + padding)
            tile_width_used = tile_w

        y0 = 0.93 - (row + 1) * tile_h - row * padding

        # Fond de la tuile
        fancy = FancyBboxPatch(
            (x0, y0), tile_width_used, tile_h - 0.02,
            boxstyle="round,pad=0.01",
            facecolor=tile["color"],
            edgecolor="white",
            linewidth=2,
            transform=ax.transAxes,
        )
        ax.add_patch(fancy)

        # Titre de tuile (petite police)
        ax.text(
            x0 + tile_width_used / 2,
            y0 + tile_h - 0.05,
            tile["title"],
            ha="center", va="top",
            fontsize=8, color="white", alpha=0.85,
            fontweight="bold",
            transform=ax.transAxes,
        )

        # Valeur principale
        value_text = str(tile["value"])
        fontsize = 22 if len(value_text) <= 6 else (16 if len(value_text) <= 20 else 11)
        ax.text(
            x0 + tile_width_used / 2,
            y0 + (tile_h - 0.02) / 2,
            value_text,
            ha="center", va="center",
            fontsize=fontsize, color="white",
            fontweight="bold",
            transform=ax.transAxes,
            wrap=True,
        )

        # Sous-titre
        if tile.get("sub"):
            ax.text(
                x0 + tile_width_used / 2,
                y0 + 0.03,
                tile["sub"],
                ha="center", va="bottom",
                fontsize=8, color="white", alpha=0.8,
                transform=ax.transAxes,
            )

    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor=HEX_BG)
    plt.close(fig)
    buf.seek(0)
    chart_img = Image.open(buf).convert("RGB")

    # Assembler avec l'en-tête Pillow
    img = Image.new("RGB", (width, height), C_BG_LIGHT)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, width, "METHODS", "⚙️", slide_index + 1, total_slides)
    _draw_footer(draw, width, height, meta)

    chart_resized = chart_img.resize(
        (width, height - HEADER_H - 43),
        Image.LANCZOS,
    )
    img.paste(chart_resized, (0, HEADER_H + 3))

    return img


# ── SLIDE RÉSULTATS — Stat cards ──────────────────────────────────────────────

def create_results_slide(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    meta: dict,
    width: int,
    height: int,
) -> Image.Image:
    """
    Stat cards avec les résultats clés de l'étude.
    Si aucun chart_data, utilise les slide_bullets comme fallback.
    """
    chart_data = section.chart_data or {}
    cards = chart_data.get("cards", [])

    # Fallback : créer des cards à partir des bullets
    if not cards and section.slide_bullets:
        color_cycle = [HEX_PURPLE, HEX_HEADER, "#9A5CC0"]
        cards = [
            {"label": "", "value": b, "context": "", "color": color_cycle[i % 3]}
            for i, b in enumerate(section.slide_bullets[:4])
        ]

    dpi = 150
    fig_w = width / dpi
    fig_h = (height - HEADER_H - 40) / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(HEX_BG)
    ax.set_facecolor(HEX_BG)
    ax.axis("off")

    n_cards = len(cards)
    cols = min(n_cards, 3)
    card_w = (0.92 / cols) - 0.02
    card_h = 0.70

    color_map = {
        "primary": HEX_HEADER,
        "accent":  HEX_PURPLE,
        "warning": HEX_YELLOW,
        "green":   HEX_GREEN,
    }

    for idx, card in enumerate(cards[:3]):
        x0 = 0.04 + idx * (card_w + 0.02)
        y0 = 0.12

        hex_color = color_map.get(card.get("color", ""), card.get("color", HEX_PURPLE))
        if not str(hex_color).startswith("#"):
            hex_color = HEX_PURPLE

        fancy = FancyBboxPatch(
            (x0, y0), card_w, card_h,
            boxstyle="round,pad=0.015",
            facecolor=hex_color,
            edgecolor="white",
            linewidth=2,
            transform=ax.transAxes,
        )
        ax.add_patch(fancy)

        # Label en haut
        if card.get("label"):
            ax.text(
                x0 + card_w / 2, y0 + card_h - 0.06,
                card["label"].upper(),
                ha="center", va="top",
                fontsize=9, color="white", alpha=0.85,
                fontweight="bold",
                transform=ax.transAxes,
            )

        # Valeur principale (grande)
        value_str = str(card.get("value", ""))
        v_fontsize = 36 if len(value_str) <= 5 else (22 if len(value_str) <= 12 else 14)
        ax.text(
            x0 + card_w / 2,
            y0 + card_h * 0.52,
            value_str,
            ha="center", va="center",
            fontsize=v_fontsize, color="white",
            fontweight="bold",
            transform=ax.transAxes,
        )

        # N= sous la valeur
        if card.get("n"):
            ax.text(
                x0 + card_w / 2,
                y0 + card_h * 0.30,
                f"(n={card['n']})",
                ha="center", va="center",
                fontsize=10, color="white", alpha=0.8,
                transform=ax.transAxes,
            )

        # Contexte en bas
        if card.get("context"):
            ax.text(
                x0 + card_w / 2,
                y0 + 0.06,
                card["context"],
                ha="center", va="bottom",
                fontsize=8, color="white", alpha=0.85,
                transform=ax.transAxes,
                wrap=True,
            )

    # Source quote en bas
    source = chart_data.get("source_quote", "")
    if source:
        ax.text(
            0.5, 0.04,
            f"« {source[:120]}... »" if len(source) > 120 else f"« {source} »",
            ha="center", va="bottom",
            fontsize=7.5, color=HEX_TEXT, alpha=0.55,
            style="italic",
            transform=ax.transAxes,
        )

    plt.tight_layout(pad=0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor=HEX_BG)
    plt.close(fig)
    buf.seek(0)
    chart_img = Image.open(buf).convert("RGB")

    # Assemblage
    img = Image.new("RGB", (width, height), C_BG_LIGHT)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, width, "KEY RESULTS", "📊", slide_index + 1, total_slides)
    _draw_footer(draw, width, height, meta)

    chart_resized = chart_img.resize(
        (width, height - HEADER_H - 43),
        Image.LANCZOS,
    )
    img.paste(chart_resized, (0, HEADER_H + 3))

    return img


# ── SLIDE CRITICAL — Tableau comparatif ───────────────────────────────────────

def create_critical_slide(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    meta: dict,
    width: int,
    height: int,
) -> Image.Image:
    """
    Tableau comparatif : cette étude vs littérature existante.
    Si chart_data absent ou incomplet, utilise les slide_bullets comme fallback.
    """
    chart_data = section.chart_data or {}
    rows = chart_data.get("rows", [])
    label_this  = chart_data.get("label_this", "This study")
    label_prior = chart_data.get("label_prior", "Prior evidence")

    if rows:
        return _create_comparison_table(
            section, slide_index, total_slides, meta,
            rows, label_this, label_prior, width, height,
        )
    else:
        # Fallback : slide texte avec bullets critiques
        return create_text_slide(section, slide_index, total_slides, meta, width, height)


def _create_comparison_table(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    meta: dict,
    rows: list,
    label_this: str,
    label_prior: str,
    width: int,
    height: int,
) -> Image.Image:
    """Tableau à 3 colonnes : Aspect | This study | Prior evidence."""
    dpi = 150
    fig_w = width / dpi
    fig_h = (height - HEADER_H - 40) / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(HEX_BG)
    ax.set_facecolor(HEX_BG)
    ax.axis("off")

    col_labels = ["ASPECT", label_this.upper(), label_prior.upper()]
    col_data = [[r.get("aspect", ""), r.get("this", ""), r.get("prior", "")] for r in rows[:8]]

    n_rows = len(col_data)
    n_cols = 3

    col_widths = [0.26, 0.37, 0.37]
    row_h = min(0.72 / n_rows, 0.14)
    table_top = 0.93
    x_starts = [0.04, 0.04 + col_widths[0], 0.04 + col_widths[0] + col_widths[1]]

    # En-têtes du tableau
    header_colors = [HEX_HEADER, HEX_HEADER, HEX_PURPLE]
    for ci, (label, hc) in enumerate(zip(col_labels, header_colors)):
        rect = FancyBboxPatch(
            (x_starts[ci] + 0.005, table_top - 0.09),
            col_widths[ci] - 0.01, 0.085,
            boxstyle="round,pad=0.005",
            facecolor=hc,
            edgecolor="white",
            linewidth=1,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(
            x_starts[ci] + col_widths[ci] / 2,
            table_top - 0.047,
            label,
            ha="center", va="center",
            fontsize=9, color="white", fontweight="bold",
            transform=ax.transAxes,
        )

    # Lignes de données
    row_colors = ["#F0EBF8", "#E8E0F0"]
    for ri, row_data in enumerate(col_data):
        row_y_top = table_top - 0.09 - (ri + 1) * row_h - ri * 0.005
        for ci, cell in enumerate(row_data):
            rc = row_colors[ri % 2]
            if ci == 0:
                rc = "#DDD0ED"
            rect = FancyBboxPatch(
                (x_starts[ci] + 0.005, row_y_top),
                col_widths[ci] - 0.01, row_h - 0.005,
                boxstyle="round,pad=0.003",
                facecolor=rc,
                edgecolor="white",
                linewidth=1,
                transform=ax.transAxes,
            )
            ax.add_patch(rect)
            cell_fontsize = 8.5 if len(str(cell)) < 30 else 7
            ax.text(
                x_starts[ci] + col_widths[ci] / 2,
                row_y_top + row_h / 2 - 0.002,
                str(cell),
                ha="center", va="center",
                fontsize=cell_fontsize,
                color=HEX_TEXT,
                fontweight="bold" if ci == 0 else "normal",
                transform=ax.transAxes,
            )

    plt.tight_layout(pad=0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor=HEX_BG)
    plt.close(fig)
    buf.seek(0)
    chart_img = Image.open(buf).convert("RGB")

    img = Image.new("RGB", (width, height), C_BG_LIGHT)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, width, "CRITICAL REVIEW", "⚠️", slide_index + 1, total_slides)
    _draw_footer(draw, width, height, meta)

    chart_resized = chart_img.resize(
        (width, height - HEADER_H - 43),
        Image.LANCZOS,
    )
    img.paste(chart_resized, (0, HEADER_H + 3))

    return img


# ── Dispatcher principal ──────────────────────────────────────────────────────

def _section_to_slide(
    section: VideoSection,
    slide_index: int,
    total_slides: int,
    meta: dict,
    is_first: bool,
    script: VideoScript,
    width: int,
    height: int,
) -> Image.Image:
    """Choisit la bonne fonction de création selon le type de section."""
    name = section.name

    if is_first or name == "PAPER":
        return create_intro_slide(script, width, height)
    elif name == "METHODS":
        return create_methods_slide(section, slide_index, total_slides, meta, width, height)
    elif name == "RESULTS":
        return create_results_slide(section, slide_index, total_slides, meta, width, height)
    elif name == "CRITICAL":
        return create_critical_slide(section, slide_index, total_slides, meta, width, height)
    else:
        return create_text_slide(section, slide_index, total_slides, meta, width, height)


# ── Point d'entrée principal ──────────────────────────────────────────────────

def generate_slides_for_script(
    script: VideoScript,
    output_dir: Path,
    generate_short: bool = True,
) -> dict:
    """
    Génère toutes les slides pour un script vidéo.

    Retourne :
    {
        "long":  [path1, path2, ...],   # slides 16:9  (1920×1080)
        "short": [path1, path2, ...],   # slides 9:16  (1080×1920)
    }
    """
    output_dir = Path(output_dir)
    long_dir  = output_dir / "slides_long"
    short_dir = output_dir / "slides_short"
    long_dir.mkdir(parents=True, exist_ok=True)
    short_dir.mkdir(parents=True, exist_ok=True)

    meta = script.article_metadata or {}
    total = len(script.sections)
    long_paths  = []
    short_paths = []

    for i, section in enumerate(script.sections):
        logger.info(f"Slide {i+1}/{total}: {section.name}")
        is_first = (i == 0)

        try:
            slide_long = _section_to_slide(
                section, i, total, meta, is_first, script,
                LONG_W, LONG_H,
            )
        except Exception as e:
            logger.warning(f"Slide {section.name} failed ({e}), using fallback text slide")
            slide_long = create_text_slide(section, i, total, meta, LONG_W, LONG_H)

        long_path = long_dir / f"slide_{i:02d}_{section.name}.png"
        slide_long.save(long_path, "PNG")
        long_paths.append(str(long_path))

        if generate_short:
            try:
                slide_short = _section_to_slide(
                    section, i, total, meta, is_first, script,
                    SHORT_W, SHORT_H,
                )
            except Exception as e:
                logger.warning(f"Short slide {section.name} failed ({e}), using fallback")
                slide_short = create_text_slide(section, i, total, meta, SHORT_W, SHORT_H)

            short_path = short_dir / f"slide_{i:02d}_{section.name}.png"
            slide_short.save(short_path, "PNG")
            short_paths.append(str(short_path))

    logger.info(f"✓ Generated {len(long_paths)} long slides + {len(short_paths)} short slides")
    return {"long": long_paths, "short": short_paths}
