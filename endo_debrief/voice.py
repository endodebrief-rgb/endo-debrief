"""
voice.py — Synthèse vocale avec ElevenLabs (voix clonée du Dr Dabi)

Le Dr Dabi enregistre ~1-2 minutes de sa voix, uplode sur ElevenLabs
pour créer un "Instant Voice Clone". L'ID de la voix est stocké dans .env.

Ce module :
1. Segmente le script par section (pour synchroniser avec les slides)
2. Génère l'audio pour chaque section (MP3)
3. Génère un fichier audio complet pour le montage
"""

import os
import time
import logging
from pathlib import Path

import requests

from . import config
from .script import VideoScript, VideoSection

logger = logging.getLogger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


def _tts_request(text: str, voice_id: str, stability: float = 0.5, similarity: float = 0.8) -> bytes:
    """
    Appelle l'API ElevenLabs TTS et retourne les bytes audio MP3.
    """
    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}"

    headers = {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",  # Modèle le plus rapide et économique
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity,
            "style": 0.3,              # Légèrement expressif
            "use_speaker_boost": True,
        },
        "output_format": "mp3_44100_128",  # 44.1kHz, 128kbps — bonne qualité, poids raisonnable
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.content

    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            raise ValueError("ElevenLabs API key invalid or expired") from e
        elif response.status_code == 422:
            raise ValueError(f"ElevenLabs rejected the text (too long or invalid): {text[:100]}") from e
        raise


def generate_section_audio(
    section: VideoSection,
    output_path: Path,
    voice_id: str = "",
) -> Path:
    """
    Génère le fichier audio MP3 pour une section du script.
    Retourne le chemin du fichier généré.
    """
    voice_id = voice_id or config.ELEVENLABS_VOICE_ID
    if not voice_id:
        raise ValueError(
            "ELEVENLABS_VOICE_ID is not set. "
            "Please clone your voice on ElevenLabs and add the voice ID to .env"
        )

    text = section.narration.strip()
    if not text:
        raise ValueError(f"Empty narration for section {section.name}")

    # ElevenLabs limite à ~2500 caractères par requête
    # Segmenter si le texte est trop long
    MAX_CHARS = 2400

    if len(text) <= MAX_CHARS:
        logger.info(f"Generating audio for section {section.name} ({len(text)} chars)...")
        audio_bytes = _tts_request(text, voice_id)
    else:
        # Découper en segments et concaténer
        logger.info(
            f"Section {section.name} is long ({len(text)} chars), splitting into segments..."
        )
        sentences = text.replace(". ", ".|").replace("! ", "!|").replace("? ", "?|").split("|")
        segments = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= MAX_CHARS:
                current += sentence + " "
            else:
                if current:
                    segments.append(current.strip())
                current = sentence + " "
        if current:
            segments.append(current.strip())

        audio_parts = []
        for j, segment in enumerate(segments):
            logger.info(f"  Generating segment {j+1}/{len(segments)}...")
            part = _tts_request(segment, voice_id)
            audio_parts.append(part)
            time.sleep(0.5)  # Rate limiting

        audio_bytes = b"".join(audio_parts)

    # Sauvegarder
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)
    logger.info(f"✓ Audio saved: {output_path} ({len(audio_bytes) / 1024:.0f} KB)")

    return output_path


def generate_all_audio(
    script: VideoScript,
    output_dir: Path,
) -> dict:
    """
    Génère tous les fichiers audio pour un script vidéo.

    Retourne un dict :
    {
        "sections": {
            "HOOK": "/path/to/hook.mp3",
            "BACKGROUND": "/path/to/background.mp3",
            ...
        },
        "full_long": "/path/to/full_long.mp3",
        "full_short": "/path/to/full_short.mp3",
    }
    """
    output_dir = Path(output_dir)
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    section_paths = {}

    # Générer l'audio pour chaque section
    for section in script.sections:
        audio_path = audio_dir / f"{section.name.lower()}.mp3"
        try:
            generate_section_audio(section, audio_path)
            section_paths[section.name] = str(audio_path)
            time.sleep(0.3)  # Pause entre les requêtes
        except Exception as e:
            logger.error(f"✗ Failed to generate audio for {section.name}: {e}")
            raise

    # Générer l'audio complet (format long) — concaténation de toutes les sections
    full_long_path = audio_dir / "full_long.mp3"
    _concatenate_mp3_files(
        [section_paths[s.name] for s in script.sections if s.name in section_paths],
        full_long_path,
    )

    # Générer l'audio court (Reels/TikTok) depuis le short_script
    full_short_path = audio_dir / "full_short.mp3"
    if script.short_script:
        try:
            logger.info("Generating short version audio (Reels/TikTok)...")
            short_section = VideoSection(
                name="SHORT",
                narration=script.short_script,
                slide_title="",
                slide_bullets=[],
                visual_prompt="",
                duration_s=75,
            )
            generate_section_audio(short_section, full_short_path)
        except Exception as e:
            logger.warning(f"Could not generate short audio: {e}")
            full_short_path = full_long_path

    return {
        "sections": section_paths,
        "full_long": str(full_long_path),
        "full_short": str(full_short_path),
    }


def _concatenate_mp3_files(input_paths: list[str], output_path: Path):
    """
    Concatène plusieurs fichiers MP3 en un seul (simple binary concatenation).
    Pour un assemblage propre avec pauses, MoviePy gère ça dans video.py.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as outfile:
        for path in input_paths:
            if path and Path(path).exists():
                outfile.write(Path(path).read_bytes())
                # Petite pause silencieuse entre sections (~0.3s de silence MP3)
                # En pratique, MoviePy gère les transitions plus finement
    logger.info(f"✓ Full audio concatenated: {output_path}")


def get_voice_info(voice_id: str = "") -> dict:
    """Récupère les infos de la voix clonée depuis ElevenLabs."""
    voice_id = voice_id or config.ELEVENLABS_VOICE_ID
    headers = {"xi-api-key": config.ELEVENLABS_API_KEY}

    try:
        response = requests.get(
            f"{ELEVENLABS_API_BASE}/voices/{voice_id}",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Could not fetch voice info: {e}")
        return {}


def list_available_voices() -> list[dict]:
    """Liste toutes les voix disponibles sur le compte ElevenLabs."""
    headers = {"xi-api-key": config.ELEVENLABS_API_KEY}

    try:
        response = requests.get(
            f"{ELEVENLABS_API_BASE}/voices",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        voices = response.json().get("voices", [])
        return [{"voice_id": v["voice_id"], "name": v["name"]} for v in voices]
    except Exception as e:
        logger.error(f"Could not list voices: {e}")
        return []
