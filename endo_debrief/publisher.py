"""
publisher.py — Publication multi-plateformes

Publie les vidéos générées sur :
- YouTube      : vidéo longue (16:9), thumbnail, titre + description optimisés
- Instagram    : vidéo courte Reels (9:16), légende avec hashtags
- TikTok       : vidéo courte (9:16), légende avec hashtags
- Facebook     : vidéo longue (16:9) sur la Page Endo Debrief

Nécessite les credentials dans .env (voir .env.example).
"""

import json
import logging
import os
import time
from pathlib import Path

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from . import config

logger = logging.getLogger(__name__)


# ── YouTube ───────────────────────────────────────────────────────────────────

def _get_youtube_service():
    """Crée le client YouTube Data API v3 avec OAuth2."""
    creds = Credentials(
        token=None,
        refresh_token=config.YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds)


def publish_youtube(
    video_path: str,
    thumbnail_path: str,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "public",
) -> dict:
    """
    Upload une vidéo sur YouTube.

    Returns:
        {"video_id": "...", "url": "https://youtu.be/..."}
    """
    logger.info(f"Uploading to YouTube: {title[:60]}...")

    youtube = _get_youtube_service()

    body = {
        "snippet": {
            "title": title[:100],          # Max 100 chars YouTube
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": config.YOUTUBE_CATEGORY_ID,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    # Upload avec retry
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"  YouTube upload: {int(status.progress() * 100)}%")

    video_id = response["id"]
    logger.info(f"✓ YouTube video uploaded: https://youtu.be/{video_id}")

    # Upload de la miniature
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            logger.info("✓ YouTube thumbnail uploaded")
        except Exception as e:
            logger.warning(f"Could not upload thumbnail: {e}")

    return {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
    }


# ── Instagram ─────────────────────────────────────────────────────────────────

def publish_instagram_reel(
    video_path: str,
    caption: str,
) -> dict:
    """
    Publie un Reel sur Instagram Business.

    Utilise l'API Meta Graph (2 étapes : upload → publish).
    Le fichier vidéo doit être accessible via une URL publique.
    Pour GitHub Actions, on uploade d'abord sur un hébergement temporaire.

    Returns:
        {"media_id": "...", "permalink": "..."}
    """
    logger.info("Publishing to Instagram Reels...")

    base_url = "https://graph.facebook.com/v19.0"
    ig_user_id = config.META_INSTAGRAM_USER_ID
    token = config.META_PAGE_ACCESS_TOKEN

    if not ig_user_id or not token:
        raise ValueError("META_INSTAGRAM_USER_ID or META_PAGE_ACCESS_TOKEN not configured")

    # Étape 1 : Créer un media container avec upload du fichier vidéo
    # Note: Meta requiert que la vidéo soit accessible via une URL publique
    # Pour GitHub Actions, on utilise un lien temporaire (ex: via transfer.sh ou Cloudinary)
    video_url = _upload_to_temporary_host(video_path)
    if not video_url:
        raise ValueError("Could not upload video to temporary host for Instagram")

    create_params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200],
        "share_to_feed": True,
        "access_token": token,
    }

    create_resp = requests.post(
        f"{base_url}/{ig_user_id}/media",
        data=create_params,
        timeout=60,
    )
    create_resp.raise_for_status()
    container_id = create_resp.json()["id"]

    # Étape 2 : Attendre que le container soit prêt
    logger.info(f"  Instagram media container created: {container_id}, waiting for processing...")
    _wait_for_instagram_media(container_id, token)

    # Étape 3 : Publier
    publish_params = {
        "creation_id": container_id,
        "access_token": token,
    }
    publish_resp = requests.post(
        f"{base_url}/{ig_user_id}/media_publish",
        data=publish_params,
        timeout=30,
    )
    publish_resp.raise_for_status()
    media_id = publish_resp.json()["id"]

    logger.info(f"✓ Instagram Reel published: {media_id}")
    return {"media_id": media_id}


def _wait_for_instagram_media(
    container_id: str,
    token: str,
    max_wait: int = 300,
) -> None:
    """Attend que le container Instagram soit prêt (status = FINISHED)."""
    base_url = "https://graph.facebook.com/v19.0"
    elapsed = 0
    interval = 10

    while elapsed < max_wait:
        resp = requests.get(
            f"{base_url}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status_code", data.get("status", ""))

        logger.info(f"  Instagram media status: {status} ({elapsed}s elapsed)")

        if status == "FINISHED":
            return
        elif status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram media processing failed: {status}")

        time.sleep(interval)
        elapsed += interval

    raise TimeoutError(f"Instagram media processing timed out after {max_wait}s")


# ── TikTok ────────────────────────────────────────────────────────────────────

def publish_tiktok(
    video_path: str,
    caption: str,
) -> dict:
    """
    Publie une vidéo sur TikTok via le Content Posting API v2.

    Returns:
        {"publish_id": "...", "url": "..."}
    """
    logger.info("Publishing to TikTok...")

    token = config.TIKTOK_ACCESS_TOKEN
    if not token:
        raise ValueError("TIKTOK_ACCESS_TOKEN not configured")

    video_path = Path(video_path)
    file_size = video_path.stat().st_size

    # Étape 1 : Init upload
    init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    init_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    init_body = {
        "post_info": {
            "title": caption[:150],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        },
    }

    init_resp = requests.post(init_url, headers=init_headers, json=init_body, timeout=30)
    init_resp.raise_for_status()
    init_data = init_resp.json()["data"]
    publish_id = init_data["publish_id"]
    upload_url = init_data["upload_url"]

    # Étape 2 : Upload du fichier
    logger.info(f"  TikTok upload URL received, uploading {file_size / 1024 / 1024:.1f} MB...")
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_headers = {
        "Content-Type": "video/mp4",
        "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
        "Content-Length": str(file_size),
    }
    upload_resp = requests.put(upload_url, headers=upload_headers, data=video_bytes, timeout=120)
    upload_resp.raise_for_status()

    logger.info(f"✓ TikTok video uploaded (publish_id: {publish_id})")

    return {
        "publish_id": publish_id,
        "status": "processing",
    }


# ── Facebook ──────────────────────────────────────────────────────────────────

def publish_facebook(
    video_path: str,
    title: str,
    description: str,
) -> dict:
    """
    Publie une vidéo sur la Page Facebook Endo Debrief.

    Returns:
        {"video_id": "...", "url": "..."}
    """
    logger.info("Publishing to Facebook Page...")

    page_id = config.META_FACEBOOK_PAGE_ID
    token = config.META_PAGE_ACCESS_TOKEN

    if not page_id or not token:
        raise ValueError("META_FACEBOOK_PAGE_ID or META_PAGE_ACCESS_TOKEN not configured")

    upload_url = f"https://graph-video.facebook.com/v19.0/{page_id}/videos"

    with open(video_path, "rb") as video_file:
        response = requests.post(
            upload_url,
            data={
                "title": title[:255],
                "description": description[:10000],
                "access_token": token,
            },
            files={"source": ("video.mp4", video_file, "video/mp4")},
            timeout=300,  # Upload peut prendre du temps
        )

    response.raise_for_status()
    video_id = response.json().get("id", "")

    logger.info(f"✓ Facebook video published: {video_id}")
    return {
        "video_id": video_id,
        "url": f"https://www.facebook.com/{page_id}/videos/{video_id}",
    }


# ── Publication multi-plateformes ─────────────────────────────────────────────

def publish_all_platforms(video_manifest: dict) -> dict:
    """
    Publie une vidéo sur toutes les plateformes configurées.

    Arguments:
        video_manifest : entrée du review_manifest.json pour une vidéo

    Retourne les résultats de publication pour chaque plateforme.
    """
    results = {}
    errors = {}

    files = video_manifest.get("files", {})
    youtube_meta = video_manifest.get("youtube", {})
    instagram_meta = video_manifest.get("instagram", {})
    tiktok_meta = video_manifest.get("tiktok", {})
    facebook_meta = video_manifest.get("facebook", {})

    # YouTube
    if files.get("video_long") and config.YOUTUBE_REFRESH_TOKEN:
        try:
            results["youtube"] = publish_youtube(
                video_path=files["video_long"],
                thumbnail_path=files.get("thumbnail", ""),
                title=youtube_meta.get("title", ""),
                description=youtube_meta.get("description", ""),
                tags=youtube_meta.get("tags", []),
                privacy=youtube_meta.get("privacy", "public"),
            )
        except Exception as e:
            logger.error(f"YouTube publish failed: {e}")
            errors["youtube"] = str(e)

    # Instagram Reels
    if files.get("video_short") and config.META_INSTAGRAM_USER_ID:
        try:
            results["instagram"] = publish_instagram_reel(
                video_path=files["video_short"],
                caption=instagram_meta.get("caption", ""),
            )
        except Exception as e:
            logger.error(f"Instagram publish failed: {e}")
            errors["instagram"] = str(e)

    # TikTok
    if files.get("video_short") and config.TIKTOK_ACCESS_TOKEN:
        try:
            results["tiktok"] = publish_tiktok(
                video_path=files["video_short"],
                caption=tiktok_meta.get("caption", ""),
            )
        except Exception as e:
            logger.error(f"TikTok publish failed: {e}")
            errors["tiktok"] = str(e)

    # Facebook
    if files.get("video_long") and config.META_FACEBOOK_PAGE_ID:
        try:
            results["facebook"] = publish_facebook(
                video_path=files["video_long"],
                title=facebook_meta.get("title", ""),
                description=facebook_meta.get("description", ""),
            )
        except Exception as e:
            logger.error(f"Facebook publish failed: {e}")
            errors["facebook"] = str(e)

    if errors:
        results["errors"] = errors

    return results


def _upload_to_temporary_host(file_path: str, timeout: int = 120) -> str:
    """
    Upload un fichier vidéo sur un hébergement temporaire public.
    Retourne l'URL publique temporaire.

    Utilise transfer.sh (gratuit, pas de compte requis, lien valable 14 jours).
    Alternative : Cloudinary, AWS S3 pre-signed URLs.
    """
    file_path = Path(file_path)
    logger.info(f"Uploading {file_path.name} to temporary host...")

    try:
        with open(file_path, "rb") as f:
            response = requests.put(
                f"https://transfer.sh/{file_path.name}",
                data=f,
                headers={"Max-Downloads": "5", "Max-Days": "7"},
                timeout=timeout,
            )
        response.raise_for_status()
        url = response.text.strip()
        logger.info(f"✓ Uploaded to: {url}")
        return url
    except Exception as e:
        logger.error(f"Temporary upload failed: {e}")
        return ""
