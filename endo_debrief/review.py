"""
review.py — Système de validation par email avant publication

Après génération des 3 vidéos de la semaine, ce module :
1. Envoie un email récapitulatif au Dr Dabi avec :
   - Les 3 scripts complets (texte) + scripts spécifiques par plateforme
   - Les liens de téléchargement des vidéos (via GitHub Actions Artifacts)
   - Un récapitulatif de chaque article (titre, journal, score, flags critique)
   - Les metadata YouTube/TikTok/Instagram/Facebook générées
2. Génère un fichier JSON de review_manifest.json que le Dr Dabi peut éditer
   avant de déclencher la publication.

Workflow de validation :
  1. Pipeline génère les vidéos → email envoyé
  2. Dr Dabi télécharge et regarde les vidéos
  3. Dr Dabi déclenche le workflow "publish" sur GitHub Actions
     (avec option de modifier les titres/descriptions dans review_manifest.json)
"""

import json
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from . import config
from .script import VideoScript
from .content_types import ScoredContentItem

logger = logging.getLogger(__name__)


def generate_review_manifest(
    scripts: list[VideoScript],
    scored_articles: list[ScoredContentItem],
    video_paths: list[dict],
    output_dir: Path,
    week_date: str = "",
    paywalled_info: list[dict] = None,
) -> Path:
    """
    Génère le fichier review_manifest.json que le Dr Dabi peut éditer
    avant de déclencher la publication.

    Ce fichier contient toutes les métadonnées éditables :
    titres, descriptions, hashtags, scripts par plateforme, etc.
    """
    week_date = week_date or datetime.now().strftime("%Y-W%U")
    manifest = {
        "week": week_date,
        "generated_at": datetime.now().isoformat(),
        "approved": False,  # À passer à True pour déclencher la publication
        "paywalled_articles": paywalled_info or [],
        "videos": [],
    }

    for i, (script, scored, paths) in enumerate(
        zip(scripts, scored_articles, video_paths)
    ):
        item = scored.item

        # Extraire les scripts plateforme si disponibles (dict de PlatformContent ou dicts)
        ps = {}
        if script.platform_scripts:
            for platform, pc in script.platform_scripts.items():
                if hasattr(pc, "caption"):
                    # PlatformContent object
                    ps[platform] = {
                        "title": pc.title,
                        "narration": pc.narration,
                        "caption": pc.caption,
                        "hashtags": pc.hashtags,
                        "duration_s": pc.duration_s,
                        "tone_notes": pc.tone_notes,
                    }
                else:
                    # Already a dict
                    ps[platform] = pc

        # Construire les captions/descriptions plateforme (prefer platform_scripts, fallback to generic)
        ig_caption = (
            ps["instagram"]["caption"] if "instagram" in ps
            else _build_instagram_caption(script)
        )
        if "instagram" in ps and ps["instagram"].get("hashtags"):
            ig_caption = (
                ig_caption
                + "\n\n"
                + " ".join(f"#{h.lstrip('#')}" for h in ps["instagram"]["hashtags"])
            )[:2200]

        tt_caption = (
            ps["tiktok"]["caption"] if "tiktok" in ps
            else _build_tiktok_caption(script)
        )
        if "tiktok" in ps and ps["tiktok"].get("hashtags"):
            tt_caption = (
                tt_caption
                + " "
                + " ".join(f"#{h.lstrip('#')}" for h in ps["tiktok"]["hashtags"])
            )[:2200]

        fb_title = ps.get("facebook", {}).get("title") or script.video_title
        fb_description = (
            ps["facebook"]["caption"] if "facebook" in ps
            else _build_facebook_description(script, item)
        )

        yt_title = ps.get("youtube", {}).get("title") or script.video_title
        yt_description = ps.get("youtube", {}).get("caption") or script.video_description
        yt_tags = ps.get("youtube", {}).get("hashtags") or script.hashtags

        video_entry = {
            "index": i + 1,
            "uid": item.uid,
            "content_type": item.content_type.value,
            "content_type_label": item.content_type_label,
            "pubmed_url": item.url,
            "original_title": item.title,
            "source_name": item.source_name,
            "pub_date": item.pub_date,
            "authors": item.authors[:3],
            "score": {
                "total": round(scored.total_score, 1),
                "scientific_impact": scored.scores.get("scientific_impact"),
                "patient_relevance": scored.scores.get("patient_relevance"),
                "pedagogical_value": scored.scores.get("pedagogical_value"),
                "viral_potential": scored.scores.get("viral_potential"),
            },

            # Flags de critique méthodologique (auto-générés par GPT-4o lors du scoring)
            "critique_flags": scored.critique_flags if hasattr(scored, "critique_flags") else {},

            # Métadonnées éditables par le Dr Dabi — plateforme par plateforme
            "youtube": {
                "title": yt_title,
                "description": yt_description,
                "tags": yt_tags,
                "privacy": "public",
            },
            "instagram": {
                "caption": ig_caption,
            },
            "tiktok": {
                "title": script.short_title,
                "caption": tt_caption,
            },
            "facebook": {
                "title": fb_title,
                "description": fb_description,
            },

            # Scripts spécifiques par plateforme (texte complet)
            "platform_scripts": ps,

            # Chemins des fichiers
            "files": {
                "video_long": paths.get("long", ""),
                "video_short": paths.get("short", ""),
                "thumbnail": paths.get("thumbnail", ""),
            },

            # Script YouTube complet pour révision
            "script": {
                "full_narration": script.full_narration,
                "short_narration": script.short_narration,
                "sections": [
                    {
                        "name": s.name,
                        "narration": s.narration,
                        "duration_s": s.duration_s,
                    }
                    for s in script.sections
                ],
            },

            # Notes de révision (à remplir par le Dr Dabi)
            "review_notes": "",
            "approved": True,
        }
        manifest["videos"].append(video_entry)

    # Sauvegarder le manifeste
    manifest_path = output_dir / "review_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(f"✓ Review manifest saved: {manifest_path}")
    return manifest_path


def _build_instagram_caption(script: VideoScript) -> str:
    """Construit la légende Instagram générique (max 2200 chars)."""
    hashtags = " ".join(f"#{h.lstrip('#')}" for h in script.hashtags[:20])
    caption = (
        f"🔬 {script.video_title}\n\n"
        f"New episode of Endo Debrief — I break down this week's "
        f"endometriosis research so you don't have to read 10 pages of science.\n\n"
        f"Full video on YouTube (link in bio) 🎥\n\n"
        f"{config.DISCLAIMER}\n\n"
        f"{hashtags}"
    )
    return caption[:2200]


def _build_tiktok_caption(script: VideoScript) -> str:
    """Construit le titre/caption TikTok générique (max 2200 chars)."""
    return (
        f"{script.short_title} 🔬 "
        f"{config.TIKTOK_DEFAULT_HASHTAGS}"
    )[:2200]


def _build_facebook_description(script: VideoScript, item) -> str:
    """Construit la description pour la page Facebook (générique)."""
    source = getattr(item, "source_name", "")
    url = getattr(item, "url", "")
    return (
        f"📊 NEW ENDO DEBRIEF: {script.video_title}\n\n"
        f"This week I break down a new publication from {source}.\n\n"
        f"{script.video_description[:500]}...\n\n"
        f"📖 Read the original: {url}\n\n"
        f"{config.DISCLAIMER}"
    )


def send_review_email(
    manifest_path: Path,
    week_date: str = "",
    github_repo: str = "your-username/endo-debrief",
    paywalled_info: list[dict] = None,
) -> bool:
    """
    Envoie l'email de validation au Dr Dabi.

    Contient :
    - Résumé des 3 vidéos générées
    - Scripts complets + scripts par plateforme
    - Instructions pour valider/publier
    - Lien vers les artifacts GitHub Actions
    """
    if not config.SMTP_EMAIL or not config.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — skipping email")
        return False

    week_date = week_date or datetime.now().strftime("Week %U, %Y")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    paywalled_info = paywalled_info or manifest.get("paywalled_articles", [])
    html_body = _build_email_html(manifest, week_date, github_repo, paywalled_info)
    text_body = _build_email_text(manifest, week_date)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔬 Endo Debrief — {week_date} — 3 vidéos à valider"
    msg["From"] = config.SMTP_EMAIL
    msg["To"] = config.REVIEW_EMAIL

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.SMTP_EMAIL, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_EMAIL, config.REVIEW_EMAIL, msg.as_string())

        logger.info(f"✓ Review email sent to {config.REVIEW_EMAIL}")
        return True

    except Exception as e:
        logger.error(f"Failed to send review email: {e}")
        return False


def _build_critique_flags_html(flags: dict) -> str:
    """Génère un bloc HTML récapitulatif des flags de critique méthodologique."""
    if not flags:
        return ""

    funding = flags.get("funding_source", "unknown")
    funding_color = {
        "public": "#22c55e", "mixed": "#f59e0b",
        "industry": "#ef4444", "unknown": "#9ca3af",
    }.get(funding, "#9ca3af")

    is_rct = flags.get("is_rct", False)
    sample_ok = flags.get("sample_size_adequate")
    diverse = flags.get("population_diverse")
    stats = flags.get("stats_reported")

    def _badge(label: str, value, good_value=True) -> str:
        if value is None:
            return f'<span style="background:#e5e7eb;color:#374151;padding:2px 6px;border-radius:4px;font-size:11px;margin:2px;">❓ {label}: unknown</span>'
        color = "#dcfce7" if value == good_value else "#fee2e2"
        text_color = "#166534" if value == good_value else "#991b1b"
        icon = "✓" if value == good_value else "⚠"
        return f'<span style="background:{color};color:{text_color};padding:2px 6px;border-radius:4px;font-size:11px;margin:2px;">{icon} {label}</span>'

    return f"""
    <div style="margin:8px 0;padding:8px;background:#f9fafb;border-radius:6px;border-left:3px solid #6B2D8B;">
        <strong style="font-size:12px;color:#6B2D8B;">⚠️ Critique flags :</strong><br>
        <span style="background:{funding_color}20;color:{funding_color};padding:2px 6px;border-radius:4px;font-size:11px;margin:2px;">
            💰 Funding: {funding}
        </span>
        {_badge("RCT", is_rct, True)}
        {_badge("Sample size", sample_ok, True)}
        {_badge("Diverse population", diverse, True)}
        {_badge("Stats reported", stats, True)}
    </div>"""


def _build_platform_scripts_html(platform_scripts: dict) -> str:
    """Génère un bloc HTML affichant les scripts spécifiques par plateforme."""
    if not platform_scripts:
        return ""

    platform_icons = {
        "tiktok": "🎵", "instagram": "📸",
        "facebook": "👥", "youtube": "🎬",
    }
    platform_labels = {
        "tiktok": "TikTok (60–75s — excitant, punchy)",
        "instagram": "Instagram Reels (75–90s — chaleureux, empathique)",
        "facebook": "Facebook (2–3 min — profond, nuancé)",
        "youtube": "YouTube (court — accroche)",
    }

    blocks = ""
    for platform in ["tiktok", "instagram", "facebook"]:
        ps = platform_scripts.get(platform)
        if not ps:
            continue
        icon = platform_icons.get(platform, "📱")
        label = platform_labels.get(platform, platform)
        caption_preview = ps.get("caption", "")[:300]
        hashtags = " ".join(f"#{h.lstrip('#')}" for h in ps.get("hashtags", [])[:10])

        blocks += f"""
        <div style="margin:8px 0;padding:10px;background:#f5f0ff;border-radius:6px;">
            <strong style="color:#6B2D8B;">{icon} {label}</strong><br>
            <span style="font-size:12px;color:#374151;font-style:italic;">
                ⏱ {ps.get("duration_s", "?")}s · Ton: {ps.get("tone_notes", "")[:60]}
            </span><br>
            <p style="font-size:13px;margin:6px 0;">{caption_preview}{'...' if len(ps.get("caption","")) > 300 else ''}</p>
            <span style="font-size:11px;color:#7c3aed;">{hashtags}</span>
        </div>"""

    if not blocks:
        return ""

    return f"""
    <details style="margin-top:12px;">
        <summary style="cursor:pointer;color:#6B2D8B;font-weight:bold;">
            📱 Voir les scripts par plateforme (TikTok / Instagram / Facebook)
        </summary>
        <div style="margin-top:8px;">{blocks}</div>
    </details>"""


def _build_email_html(manifest: dict, week_date: str, github_repo: str, paywalled_info: list = None) -> str:
    """Construit le corps HTML de l'email de validation."""
    publish_url = f"https://github.com/{github_repo}/actions/workflows/publish.yml"

    videos_html = ""
    for v in manifest.get("videos", []):
        score_bar = "█" * int(v["score"]["total"] / 4) + "░" * (10 - int(v["score"]["total"] / 4))

        sections_html = ""
        for sec in v["script"]["sections"]:
            sections_html += f"""
            <tr>
                <td style="padding:4px 8px;font-weight:bold;color:#6B2D8B;
                           background:#f5f0ff;border-radius:4px;font-size:12px;white-space:nowrap;">
                    {sec['name']}
                </td>
                <td style="padding:4px 8px;color:#333;font-size:13px;line-height:1.5;">
                    {sec['narration'][:200]}{'...' if len(sec['narration']) > 200 else ''}
                </td>
            </tr>"""

        critique_html = _build_critique_flags_html(v.get("critique_flags", {}))
        platform_html = _build_platform_scripts_html(v.get("platform_scripts", {}))

        content_label = v.get("content_type_label", "Research Article")
        tiktok_title = v.get("tiktok", {}).get("title", "")

        videos_html += f"""
        <div style="margin:24px 0;padding:20px;border:2px solid #6B2D8B;border-radius:12px;
                    background:#fafafa;">
            <h3 style="color:#6B2D8B;margin:0 0 4px;">
                Vidéo #{v['index']} — {content_label}
            </h3>
            <p style="font-size:12px;color:#888;margin:0 0 8px;">
                {v.get('source_name', '')} · {v.get('pub_date', '')}
            </p>
            <p style="font-size:13px;color:#555;margin:0 0 12px;">
                <strong>Article original :</strong>
                <a href="{v['pubmed_url']}">{v['original_title'][:100]}...</a>
            </p>

            <div style="background:#0F0F1A;color:#E8A0BF;padding:8px 12px;
                        border-radius:6px;font-family:monospace;font-size:13px;margin-bottom:12px;">
                Score total : {v['score']['total']}/40 &nbsp;{score_bar}<br>
                🔬 Scientifique: {v['score']['scientific_impact']}/10 &nbsp;
                👩 Patient: {v['score']['patient_relevance']}/10 &nbsp;
                📚 Pédago: {v['score']['pedagogical_value']}/10 &nbsp;
                📱 Viral: {v['score']['viral_potential']}/10
            </div>

            {critique_html}

            <p><strong>🎬 Titre YouTube :</strong> {v['youtube']['title']}</p>
            <p><strong>🎵 Titre TikTok :</strong> {tiktok_title}</p>

            {platform_html}

            <details>
                <summary style="cursor:pointer;color:#6B2D8B;font-weight:bold;">
                    📜 Voir le script YouTube complet
                </summary>
                <table style="width:100%;margin-top:12px;border-collapse:collapse;">
                    {sections_html}
                </table>
            </details>
        </div>"""

    # Section articles payants
    paywalled_section = ""
    if paywalled_info:
        paywalled_rows = ""
        for p in paywalled_info:
            paywalled_rows += f"""
            <tr style="border-bottom:1px solid #f0e0f8;">
                <td style="padding:10px 8px;font-size:13px;">
                    <strong>{p.get('journal', '')}</strong><br>
                    <a href="{p.get('pubmed_url','')}" style="color:#6B2D8B;">
                        {p.get('title','')[:80]}...
                    </a>
                </td>
                <td style="padding:10px 8px;font-size:12px;color:#555;">
                    <strong>Fichier à déposer :</strong><br>
                    <code style="background:#f5f0ff;padding:2px 6px;border-radius:4px;">
                        pdf_uploads/{p.get('upload_filename', '')}
                    </code><br><br>
                    <a href="{p.get('doi_url','')}" style="color:#6B2D8B;">Accéder via DOI →</a>
                </td>
            </tr>"""

        paywalled_section = f"""
        <div style="margin:20px 0;padding:16px;border:2px solid #FCD34D;border-radius:12px;
                    background:#FFFBEB;">
            <h3 style="color:#92400E;margin:0 0 8px;">
                ⚠️ {len(paywalled_info)} article(s) sans accès texte intégral
            </h3>
            <p style="font-size:13px;color:#555;margin:0 0 12px;">
                Ces articles ont été traités à partir de l'abstract uniquement.
                Le script de critique méthodologique est donc moins complet.
                <strong>Si tu peux obtenir ces articles</strong> (via ton institution,
                ResearchGate, ou en écrivant aux auteurs), dépose le PDF dans le dossier
                <code>pdf_uploads/</code> du repo GitHub et relance la génération.
            </p>
            <table style="width:100%;border-collapse:collapse;">
                {paywalled_rows}
            </table>
        </div>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;">

        <div style="background:#0F0F1A;padding:20px;border-radius:12px;text-align:center;
                    margin-bottom:24px;">
            <h1 style="color:#E8A0BF;margin:0;font-size:28px;">🔬 ENDO DEBRIEF</h1>
            <p style="color:#C084FC;margin:4px 0 0;font-size:16px;">
                {week_date} — Vidéos générées, en attente de validation
            </p>
        </div>

        <p>Bonjour Yohann,</p>
        <p>Le pipeline <strong>Endo Debrief</strong> a généré <strong>3 vidéos</strong> cette semaine.
        Chaque vidéo inclut des scripts adaptés à chaque plateforme (TikTok, Instagram, Facebook).</p>

        {paywalled_section}

        <div style="background:#fff3cd;border:1px solid #ffc107;padding:12px;border-radius:8px;
                    margin-bottom:20px;">
            <strong>⚡ Pour publier :</strong><br>
            1. Télécharge les vidéos depuis les
               <a href="https://github.com/{github_repo}/actions">GitHub Actions Artifacts</a><br>
            2. Regarde et valide chaque vidéo<br>
            3. Si OK →
               <a href="{publish_url}">déclenche le workflow "Publish"</a> sur GitHub Actions<br>
            4. Les 3 vidéos seront publiées sur YouTube, Instagram, TikTok et Facebook
               avec leurs scripts et captions spécifiques.
        </div>

        {videos_html}

        <hr style="border:1px solid #e0d0f0;margin:24px 0;">
        <p style="font-size:12px;color:#999;">
            {config.DISCLAIMER}<br>
            Email généré automatiquement par le pipeline Endo Debrief.
        </p>
    </body>
    </html>"""


def _build_email_text(manifest: dict, week_date: str) -> str:
    """Corps texte brut de l'email (fallback)."""
    lines = [
        f"ENDO DEBRIEF — {week_date}",
        "=" * 50,
        "",
        "3 vidéos générées cette semaine. Récapitulatif :",
        "",
    ]
    for v in manifest.get("videos", []):
        lines += [
            f"VIDEO #{v['index']} [{v.get('content_type_label', '')}]",
            f"  Article : {v['original_title'][:80]}",
            f"  Source  : {v.get('source_name','')} ({v.get('pub_date','')})",
            f"  Score   : {v['score']['total']}/40",
            f"  YouTube : {v['youtube']['title']}",
            f"  TikTok  : {v['tiktok']['title']}",
            f"  URL     : {v['pubmed_url']}",
            "",
        ]
    lines += [
        "Pour publier : déclencher le workflow 'Publish' sur GitHub Actions.",
        "",
        config.DISCLAIMER,
    ]
    return "\n".join(lines)


def load_manifest(manifest_path: Path) -> dict:
    """Charge et retourne le manifeste de review."""
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)
