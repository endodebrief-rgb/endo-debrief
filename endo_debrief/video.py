"""
video.py — Assemblage vidéo avec MoviePy

Assemble les slides (PNG) et l'audio (MP3) en vidéos MP4 finales.

Produit 2 vidéos par article :
- video_long.mp4  : 1920x1080 (YouTube + Facebook), ~4-6 min
- video_short.mp4 : 1080x1920 (TikTok + Instagram Reels), ~70-90s

Chaque slide est affichée pendant la durée de sa section audio.
Des transitions smooth sont ajoutées entre les slides.
"""

import os
import logging
from pathlib import Path

import numpy as np
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
    VideoFileClip,
    ColorClip,
)
from moviepy.audio.AudioClip import AudioArrayClip
from moviepy.video.fx.fadein import fadein
from moviepy.video.fx.fadeout import fadeout

from . import config
from .script import VideoScript

logger = logging.getLogger(__name__)

TRANSITION_DURATION = 0.4   # secondes de fondu entre slides
MIN_SLIDE_DURATION  = 3.0   # durée minimale d'une slide en secondes


def _get_audio_duration(audio_path: str) -> float:
    """Retourne la durée d'un fichier audio en secondes."""
    try:
        clip = AudioFileClip(audio_path)
        duration = clip.duration
        clip.close()
        return duration
    except Exception as e:
        logger.warning(f"Could not get audio duration for {audio_path}: {e}")
        return 0.0


def _create_silence(duration: float, fps: int = 44100) -> AudioArrayClip:
    """Crée un clip audio silencieux de la durée donnée."""
    n_samples = int(duration * fps)
    silence = np.zeros((n_samples, 2), dtype=np.float32)
    return AudioArrayClip(silence, fps=fps)


def assemble_long_video(
    script: VideoScript,
    slide_paths: list[str],       # Chemins des slides 16:9
    audio_section_paths: dict,    # {section_name: audio_path}
    output_path: Path,
) -> Path:
    """
    Assemble la vidéo longue (YouTube / Facebook) 1920x1080.

    Chaque slide dure exactement le temps de sa section audio.
    Transitions en fondu entre les slides.
    """
    logger.info("Assembling long video (16:9)...")

    clips = []

    for i, section in enumerate(script.sections):
        # Chemin de la slide correspondante
        if i >= len(slide_paths):
            logger.warning(f"No slide found for section {section.name}")
            continue

        slide_path = slide_paths[i]
        audio_path = audio_section_paths.get(section.name)

        # Durée basée sur l'audio réel
        if audio_path and Path(audio_path).exists():
            duration = _get_audio_duration(audio_path)
        else:
            duration = float(section.duration_s)

        duration = max(duration, MIN_SLIDE_DURATION)

        # Créer le clip image
        img_clip = (
            ImageClip(slide_path)
            .set_duration(duration)
            .set_fps(config.VIDEO_FPS)
            .resize((config.VIDEO_WIDTH_LONG, config.VIDEO_HEIGHT_LONG))
        )

        # Ajouter l'audio
        if audio_path and Path(audio_path).exists():
            audio_clip = AudioFileClip(audio_path).set_duration(duration)
            img_clip = img_clip.set_audio(audio_clip)

        # Transitions en fondu
        if i > 0:
            img_clip = img_clip.fx(fadein, TRANSITION_DURATION)
        if i < len(script.sections) - 1:
            img_clip = img_clip.fx(fadeout, TRANSITION_DURATION)

        clips.append(img_clip)
        logger.info(
            f"  Section {section.name}: {duration:.1f}s "
            f"({'audio' if audio_path else 'silent'})"
        )

    if not clips:
        raise ValueError("No clips to assemble")

    # Concaténer toutes les clips
    final = concatenate_videoclips(clips, method="compose")

    # Export
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Rendering long video to {output_path} ({final.duration:.0f}s)...")

    final.write_videofile(
        str(output_path),
        fps=config.VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate="4000k",
        audio_bitrate="192k",
        preset="fast",
        threads=4,
        logger=None,          # Désactiver les logs verbose de MoviePy
    )

    # Libérer la mémoire
    final.close()
    for clip in clips:
        clip.close()

    logger.info(f"✓ Long video saved: {output_path}")
    return output_path


def assemble_short_video(
    script: VideoScript,
    slide_paths: list[str],       # Chemins des slides 9:16
    full_short_audio: str,        # Chemin du fichier audio court (~75s)
    output_path: Path,
) -> Path:
    """
    Assemble la vidéo courte (TikTok / Instagram Reels) 1080x1920.

    La vidéo courte utilise un audio unique (~75s) et distribue
    les slides sur sa durée (environ 8-10s par slide).
    """
    logger.info("Assembling short video (9:16)...")

    # Durée totale de l'audio court
    if full_short_audio and Path(full_short_audio).exists():
        total_duration = _get_audio_duration(full_short_audio)
        audio_clip = AudioFileClip(full_short_audio)
    else:
        total_duration = 75.0
        audio_clip = None

    # Sélectionner les slides les plus importantes pour la version courte
    # (HOOK, RESULTS, CRITICAL, TAKE_HOME, OUTRO)
    priority_sections = ["HOOK", "RESULTS", "CRITICAL", "TAKE_HOME", "OUTRO"]
    selected_slides = []

    for section in script.sections:
        if section.name in priority_sections and len(selected_slides) < len(slide_paths):
            # Trouver le slide correspondant par index
            for i, s in enumerate(script.sections):
                if s.name == section.name and i < len(slide_paths):
                    selected_slides.append(slide_paths[i])
                    break

    # Si pas assez de slides prioritaires, compléter avec le reste
    if len(selected_slides) < 3:
        selected_slides = slide_paths[:6]

    # Durée par slide
    n_slides = max(len(selected_slides), 1)
    slide_duration = total_duration / n_slides

    clips = []
    for i, slide_path in enumerate(selected_slides):
        img_clip = (
            ImageClip(slide_path)
            .set_duration(slide_duration)
            .set_fps(config.VIDEO_FPS)
            .resize((config.VIDEO_WIDTH_SHORT, config.VIDEO_HEIGHT_SHORT))
        )

        if i > 0:
            img_clip = img_clip.fx(fadein, TRANSITION_DURATION)
        if i < len(selected_slides) - 1:
            img_clip = img_clip.fx(fadeout, TRANSITION_DURATION)

        clips.append(img_clip)

    final_video = concatenate_videoclips(clips, method="compose")

    if audio_clip:
        final_video = final_video.set_audio(audio_clip.set_duration(final_video.duration))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Rendering short video to {output_path} ({final_video.duration:.0f}s)...")

    final_video.write_videofile(
        str(output_path),
        fps=config.VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate="3000k",
        audio_bitrate="192k",
        preset="fast",
        threads=4,
        logger=None,
    )

    final_video.close()
    for clip in clips:
        clip.close()
    if audio_clip:
        audio_clip.close()

    logger.info(f"✓ Short video saved: {output_path}")
    return output_path


def generate_thumbnail(
    title: str,
    illustration_path: str,
    output_path: Path,
) -> Path:
    """
    Génère une miniature YouTube 1280x720 depuis la première illustration.
    """
    from PIL import Image, ImageDraw
    from .visuals import _get_font, _draw_logo_text, BG_COLOR, PRIMARY_COLOR, TEXT_COLOR, ACCENT_COLOR

    THUMB_W, THUMB_H = 1280, 720
    img = Image.new("RGB", (THUMB_W, THUMB_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Fond dégradé
    for y in range(THUMB_H):
        ratio = y / THUMB_H
        r = int(BG_COLOR[0] + (PRIMARY_COLOR[0] - BG_COLOR[0]) * ratio * 0.4)
        g = int(BG_COLOR[1] + (PRIMARY_COLOR[1] - BG_COLOR[1]) * ratio * 0.4)
        b = int(BG_COLOR[2] + (PRIMARY_COLOR[2] - BG_COLOR[2]) * ratio * 0.4)
        draw.line([(0, y), (THUMB_W, y)], fill=(r, g, b))

    # Illustration en fond (si disponible)
    if illustration_path and Path(illustration_path).exists():
        ill = Image.open(illustration_path).convert("RGB")
        ill = ill.resize((700, THUMB_H), Image.LANCZOS)
        img.paste(ill, (THUMB_W - 700, 0))

        # Overlay gradient de gauche à droite pour lisibilité
        for x in range(200):
            alpha = int(200 * (1 - x / 200))
            draw.line([(THUMB_W - 700 + x, 0), (THUMB_W - 700 + x, THUMB_H)],
                     fill=(*BG_COLOR, alpha))

    # Bande violette à gauche
    draw.rectangle([0, 0, 12, THUMB_H], fill=PRIMARY_COLOR)

    # Label "NEW STUDY" en haut
    label_font = _get_font(28, bold=True)
    draw.rectangle([40, 40, 200, 78], fill=PRIMARY_COLOR)
    draw.text((52, 46), "NEW STUDY", font=label_font, fill=TEXT_COLOR)

    # Titre
    title_font = _get_font(58, bold=True)
    from textwrap import wrap
    title_lines = wrap(title, width=22)
    y = 110
    for line in title_lines[:3]:
        draw.text((40, y), line, font=title_font, fill=TEXT_COLOR)
        bbox = draw.textbbox((40, y), line, font=title_font)
        y += bbox[3] - bbox[1] + 8

    # Logo en bas à gauche
    _draw_logo_text(draw, 40, THUMB_H - 70, size=32)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=95)
    logger.info(f"✓ Thumbnail saved: {output_path}")

    return output_path


def produce_all_videos(
    script: VideoScript,
    slides: dict,
    audio: dict,
    output_dir: Path,
) -> dict:
    """
    Produit toutes les vidéos finales pour un article.

    Arguments:
        script  : VideoScript (scripts + metadata)
        slides  : {"long": [...], "short": [...]}
        audio   : {"sections": {...}, "full_long": "...", "full_short": "..."}
        output_dir : répertoire de sortie

    Retourne:
        {
            "long": "path/to/video_long.mp4",
            "short": "path/to/video_short.mp4",
            "thumbnail": "path/to/thumbnail.jpg",
        }
    """
    output_dir = Path(output_dir)
    results = {}

    # Vidéo longue (YouTube / Facebook)
    long_path = output_dir / "video_long.mp4"
    assemble_long_video(
        script=script,
        slide_paths=slides.get("long", []),
        audio_section_paths=audio.get("sections", {}),
        output_path=long_path,
    )
    results["long"] = str(long_path)

    # Vidéo courte (TikTok / Reels)
    short_path = output_dir / "video_short.mp4"
    assemble_short_video(
        script=script,
        slide_paths=slides.get("short", []),
        full_short_audio=audio.get("full_short", ""),
        output_path=short_path,
    )
    results["short"] = str(short_path)

    # Miniature YouTube
    # Utiliser la première illustration disponible
    first_illustration = None
    for slide_path in slides.get("long", []):
        if "HOOK" in slide_path or "BACKGROUND" in slide_path:
            first_illustration = slide_path
            break

    thumb_path = output_dir / "thumbnail.jpg"
    generate_thumbnail(
        title=script.video_title,
        illustration_path=first_illustration or "",
        output_path=thumb_path,
    )
    results["thumbnail"] = str(thumb_path)

    return results
