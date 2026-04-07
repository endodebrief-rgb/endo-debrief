"""
pipeline.py — Orchestration complète du workflow Endo Debrief

Ce fichier est le point d'entrée principal du programme.
Il orchestre toutes les étapes dans l'ordre :

MODE GENERATE (lancé chaque lundi automatiquement par GitHub Actions) :
  1. Recherche PubMed des articles récents
  2. Scoring et sélection des 3 meilleurs
  3. Génération des scripts vidéo
  4. Génération des slides visuelles
  5. Génération de l'audio (voix clonée ElevenLabs)
  6. Assemblage des vidéos (MoviePy)
  7. Génération du manifeste de review
  8. Envoi de l'email de validation au Dr Dabi

MODE PUBLISH (déclenché manuellement après validation) :
  1. Lecture du review_manifest.json
  2. Publication sur YouTube, Instagram, TikTok, Facebook

Usage CLI :
  python -m endo_debrief.pipeline generate
  python -m endo_debrief.pipeline publish --manifest output/week_2026-W14/review_manifest.json
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from . import config
from .pubmed import get_articles_with_fulltext_priority, search_guidelines_pubmed, search_flashback_articles
from .clinicaltrials import get_all_interesting_trials
from .recommendations import get_all_guidelines
from .content_types import ContentItem, ContentType, from_pubmed_article, from_clinical_trial, from_guideline
from .scorer_v2 import run_unified_scoring
from .script import generate_all_scripts
from .fulltext import fetch_full_texts_for_articles, get_paywalled_articles_info
from .visuals import generate_slides_for_script
from .voice import generate_all_audio
from .video import produce_all_videos
from .review import generate_review_manifest, send_review_email, load_manifest
from .publisher import publish_all_platforms

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
console = Console()


def run_generate(week_date: str = "", dry_run: bool = False) -> Path:
    """
    Mode GENERATE : génère les 3 vidéos de la semaine.

    Arguments:
        week_date : identifiant de la semaine (ex: "2026-W14"). Auto si vide.
        dry_run   : si True, saute l'assemblage vidéo et l'email (pour tests)

    Retourne le chemin du review_manifest.json généré.
    """
    week_date = week_date or datetime.now().strftime("%Y-W%U")
    output_dir = config.OUTPUT_DIR / week_date
    output_dir.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold purple]🔬 Endo Debrief — {week_date}[/]")

    # ─── Étape 1 : Collecte multi-sources ────────────────────────────────────
    console.print("\n[bold]Step 1/8:[/] Collecting content from all sources...")
    all_content_items: list[ContentItem] = []

    # Source A : Articles PubMed (avec période élargie si peu de full-text disponible)
    console.print("  🔬 PubMed articles (full-text priority search)...")
    pubmed_articles, search_extended = get_articles_with_fulltext_priority()
    if search_extended:
        console.print("  [yellow]ℹ Search window extended to 60 days[/]")
    for article in pubmed_articles:
        all_content_items.append(from_pubmed_article(article))
    console.print(f"  [green]✓[/] {len(pubmed_articles)} PubMed articles")

    # Source B : Recommandations et guidelines cliniques (limité à 8 pour le scoring)
    console.print("  📋 Clinical guidelines (ESHRE, ACOG, Cochrane, PubMed)...")
    try:
        guidelines = get_all_guidelines(days_back=180)[:8]
        for gl in guidelines:
            all_content_items.append(from_guideline(gl.to_dict()))
        console.print(f"  [green]✓[/] {len(guidelines)} guidelines found")
    except Exception as e:
        console.print(f"  [yellow]⚠ Guidelines fetch failed: {e}[/]")

    # Source C : Essais cliniques ClinicalTrials.gov
    console.print("  🧪 Clinical trials (ClinicalTrials.gov)...")
    try:
        trials = get_all_interesting_trials()
        for trial in trials:
            all_content_items.append(from_clinical_trial(trial.to_dict()))
        console.print(f"  [green]✓[/] {len(trials)} trials found")
    except Exception as e:
        console.print(f"  [yellow]⚠ Clinical trials fetch failed: {e}[/]")

    # Source D : Articles Flashback (études fondatrices très citées, >5 ans)
    console.print("  🕰️  Flashback articles (landmark studies, >5 years old)...")
    try:
        flashback_articles = search_flashback_articles(max_results=5)
        for article in flashback_articles:
            item = from_pubmed_article(article)
            item.content_type = ContentType.FLASHBACK
            all_content_items.append(item)
        console.print(f"  [green]✓[/] {len(flashback_articles)} flashback articles")
    except Exception as e:
        console.print(f"  [yellow]⚠ Flashback search failed: {e}[/]")

    # Source E : Articles manuels proposés par Dr Dabi
    # Dépose manual_articles.json à la racine du projet pour forcer l'inclusion.
    manual_items_forced: list[ContentItem] = []
    if config.MANUAL_ARTICLES_PATH.exists():
        console.print("  📌 Manual articles (Dr Dabi's picks)...")
        try:
            with open(config.MANUAL_ARTICLES_PATH) as _f:
                manual_list = json.load(_f)
            manual_pmids = [str(e["pmid"]) for e in manual_list if "pmid" in e]
            if manual_pmids:
                from .pubmed import fetch_article_details
                manual_articles_raw = fetch_article_details(manual_pmids)
                for _art in manual_articles_raw:
                    _item = from_pubmed_article(_art)
                    _item.extra_data["manual_override"] = True
                    manual_items_forced.append(_item)
                    all_content_items.insert(0, _item)
                console.print(
                    f"  [green]✓[/] {len(manual_articles_raw)} manual article(s) added "
                    f"(will be force-selected)"
                )
        except Exception as _e:
            console.print(f"  [yellow]⚠ Manual articles loading failed: {_e}[/]")

    n_articles  = sum(1 for i in all_content_items if i.content_type == ContentType.RESEARCH_ARTICLE)
    n_guidelines= sum(1 for i in all_content_items if i.content_type == ContentType.GUIDELINE)
    n_trials    = sum(1 for i in all_content_items if i.content_type == ContentType.CLINICAL_TRIAL)
    n_flashback = sum(1 for i in all_content_items if i.content_type == ContentType.FLASHBACK)

    console.print(
        f"\n[bold]Total content pool: {len(all_content_items)} items[/] "
        f"({n_articles} articles, {n_guidelines} guidelines, "
        f"{n_trials} trials, {n_flashback} flashbacks)"
    )

    if not all_content_items:
        console.print("[red]✗ No content found. Aborting.[/]")
        sys.exit(1)

    # Plafonner le pool total à 40 items pour limiter la consommation OpenAI
    # Priorité : articles récents > guidelines > trials > flashbacks
    if len(all_content_items) > 40:
        from .content_types import ContentType as _CT
        pool: list = []
        for ct in [_CT.RESEARCH_ARTICLE, _CT.GUIDELINE, _CT.CLINICAL_TRIAL, _CT.FLASHBACK]:
            items_of_type = [i for i in all_content_items if i.content_type == ct]
            caps = {_CT.RESEARCH_ARTICLE: 20, _CT.GUIDELINE: 8, _CT.CLINICAL_TRIAL: 8, _CT.FLASHBACK: 4}
            pool.extend(items_of_type[:caps[ct]])
        all_content_items = pool
        console.print(f"[dim]Pool capped at {len(all_content_items)} items for scoring efficiency.[/]")

    # ─── Étape 2 : Scoring unifié ────────────────────────────────────────────
    console.print("\n[bold]Step 2/8:[/] Scoring all content (GPT-4o unified scoring)...")
    top_items = run_unified_scoring(all_content_items, forced_items=manual_items_forced)

    n_selected = len(top_items)
    table = Table(title=f"Weekly Selection — {n_selected} Video(s)", show_header=True)
    table.add_column("Type", style="cyan")
    table.add_column("Source", style="green")
    table.add_column("Score", justify="center")
    table.add_column("Topic", style="yellow")
    table.add_column("Title", max_width=45)
    for item in top_items:
        is_manual = item.item.extra_data.get("manual_override", False)
        score_str = "[MANUAL]" if is_manual else f"{item.total_score:.0f}/40"
        table.add_row(
            item.item.type_emoji + " " + item.item.content_type_label,
            item.item.source_name[:25],
            score_str,
            item.topic_tag,
            item.item.title[:45] + "...",
        )
    console.print(table)

    # ─── Étape 3 : Full-text pour les articles de recherche ──────────────────
    console.print("\n[bold]Step 3/8:[/] Fetching full texts (research articles only)...")
    ft_cache_dir = output_dir / "fulltext_cache"
    from .pubmed import PubMedArticle as _PMA
    pubmed_for_ft = [
        _PMA({
            "pmid": it.item.uid, "title": it.item.title, "abstract": it.item.abstract,
            "authors": it.item.authors, "journal": it.item.source_name,
            "pub_date": it.item.pub_date, "doi": it.item.extra_data.get("doi", ""),
            "keywords": it.item.extra_data.get("keywords", []),
            "publication_types": it.item.extra_data.get("publication_types", []),
        })
        for it in top_items if it.item.content_type == ContentType.RESEARCH_ARTICLE
    ]

    full_text_results = {}
    paywalled_info = []

    if pubmed_for_ft:
        full_text_results = fetch_full_texts_for_articles(pubmed_for_ft, cache_dir=ft_cache_dir)
        paywalled_info = get_paywalled_articles_info(full_text_results, pubmed_for_ft)
        for pmid, ft in full_text_results.items():
            icon = "✓" if ft.has_full_text else "⚠"
            color = "green" if ft.has_full_text else "yellow"
            console.print(f"  [{color}]{icon}[/] {pmid}: {ft.source.value}")
        if paywalled_info:
            console.print(f"  [yellow]⚠ {len(paywalled_info)} paywalled — deposit PDF in pdf_uploads/[/]")

    # ─── Étape 4 : Génération des scripts ────────────────────────────────────
    console.print("\n[bold]Step 4/8:[/] Generating video scripts (GPT-4o)...")
    scripts = generate_all_scripts(top_items, full_text_results=full_text_results)
    console.print(f"[green]✓[/] {len(scripts)} scripts generated")

    # Initialiser les structures pour stocker les résultats
    all_slides = []
    all_audio = []
    all_video_paths = []

    for i, (scored, script) in enumerate(zip(top_items, scripts)):
        article_id = scored.item.uid
        article_dir = output_dir / f"video_{i+1}_{article_id}"
        article_dir.mkdir(parents=True, exist_ok=True)

        console.rule(f"[dim]Video {i+1}/{len(top_items)} — {article_id}[/]")

        # ─── Étape 5 : Génération des slides ──────────────────────────────
        console.print(f"  [bold]Step 5/8:[/] Generating slides...")
        slides = generate_slides_for_script(script, article_dir)
        all_slides.append(slides)
        console.print(f"  [green]✓[/] {len(slides['long'])} slides (16:9) + {len(slides['short'])} slides (9:16)")

        if dry_run:
            all_audio.append({"sections": {}, "full_long": "", "full_short": ""})
            all_video_paths.append({"long": "", "short": "", "thumbnail": ""})
            continue

        # ─── Étape 6 : Génération de l'audio ──────────────────────────────
        console.print(f"  [bold]Step 6/8:[/] Generating voice audio (ElevenLabs)...")
        try:
            audio = generate_all_audio(script, article_dir)
            all_audio.append(audio)
            console.print(f"  [green]✓[/] Audio generated ({len(audio['sections'])} sections)")
        except Exception as e:
            console.print(f"  [yellow]⚠ Audio generation failed: {e}[/]")
            all_audio.append({"sections": {}, "full_long": "", "full_short": ""})

        # ─── Étape 7 : Assemblage vidéo ────────────────────────────────────
        console.print(f"  [bold]Step 7/8:[/] Assembling video (MoviePy)...")
        try:
            video_paths = produce_all_videos(
                script=script,
                slides=slides,
                audio=all_audio[-1],
                output_dir=article_dir,
            )
            all_video_paths.append(video_paths)
            console.print(f"  [green]✓[/] Videos assembled")
            console.print(f"       Long : {video_paths.get('long', 'N/A')}")
            console.print(f"       Short: {video_paths.get('short', 'N/A')}")
        except Exception as e:
            console.print(f"  [red]✗ Video assembly failed: {e}[/]")
            logger.exception("Video assembly error")
            all_video_paths.append({"long": "", "short": "", "thumbnail": ""})

    # ─── Étape 8 : Manifeste de review + Email ────────────────────────────────
    console.print("\n[bold]Step 8/8:[/] Generating review manifest and sending email...")

    manifest_path = generate_review_manifest(
        scripts=scripts,
        scored_articles=top_items,
        video_paths=all_video_paths,
        output_dir=output_dir,
        week_date=week_date,
        paywalled_info=paywalled_info,
    )

    if not dry_run:
        email_sent = send_review_email(
            manifest_path=manifest_path,
            week_date=week_date,
            paywalled_info=paywalled_info,
        )
        if email_sent:
            console.print(f"[green]✓[/] Review email sent to {config.REVIEW_EMAIL}")
        else:
            console.print(f"[yellow]⚠ Email not sent (check SMTP config in .env)[/]")

    console.rule("[bold green]✅ Generation complete[/]")
    console.print(f"\nReview manifest: [cyan]{manifest_path}[/]")
    console.print(
        "\nNext steps:\n"
        "  1. Download videos from GitHub Actions Artifacts\n"
        "  2. Review the manifest file and scripts\n"
        "  3. Trigger the 'Publish' workflow on GitHub Actions when ready"
    )

    return manifest_path


def run_publish(manifest_path: str) -> dict:
    """
    Mode PUBLISH : publie les vidéos validées sur toutes les plateformes.

    Arguments:
        manifest_path : chemin vers le review_manifest.json

    Retourne un dict avec les résultats de publication.
    """
    console.rule("[bold purple]🚀 Endo Debrief — Publishing[/]")

    manifest = load_manifest(Path(manifest_path))
    week_date = manifest.get("week", "unknown")
    videos = manifest.get("videos", [])

    console.print(f"Publishing {len(videos)} videos for {week_date}...")

    all_results = {}

    for video in videos:
        if not video.get("approved", True):
            console.print(f"  ⏭ Video #{video['index']} skipped (not approved)")
            continue

        yt_title = video.get("youtube", {}).get("title", "")
        console.print(f"\n[bold]Publishing Video #{video['index']}:[/] {yt_title[:60]}...")

        try:
            results = publish_all_platforms(video)
            all_results[f"video_{video['index']}"] = results

            # Afficher les URLs publiées
            if "youtube" in results:
                console.print(f"  [green]✓ YouTube:[/] {results['youtube'].get('url', '')}")
            if "instagram" in results:
                console.print(f"  [green]✓ Instagram:[/] media_id={results['instagram'].get('media_id', '')}")
            if "tiktok" in results:
                console.print(f"  [green]✓ TikTok:[/] publish_id={results['tiktok'].get('publish_id', '')}")
            if "facebook" in results:
                console.print(f"  [green]✓ Facebook:[/] {results['facebook'].get('url', '')}")

            if "errors" in results:
                for platform, error in results["errors"].items():
                    console.print(f"  [red]✗ {platform}:[/] {error}")

        except Exception as e:
            logger.exception(f"Publishing failed for video #{video['index']}")
            console.print(f"  [red]✗ Publishing failed: {e}[/]")

    # Sauvegarder les résultats
    results_path = Path(manifest_path).parent / "publish_results.json"
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2)

    console.rule("[bold green]✅ Publishing complete[/]")
    console.print(f"Results saved to: [cyan]{results_path}[/]")

    return all_results


def main():
    """Point d'entrée CLI."""
    parser = argparse.ArgumentParser(
        description="Endo Debrief — Automated Endometriosis Science Video Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m endo_debrief.pipeline generate
  python -m endo_debrief.pipeline generate --dry-run
  python -m endo_debrief.pipeline publish --manifest output/2026-W14/review_manifest.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Commande generate
    gen_parser = subparsers.add_parser("generate", help="Generate this week's videos")
    gen_parser.add_argument("--week", default="", help="Week identifier (e.g. 2026-W14)")
    gen_parser.add_argument("--dry-run", action="store_true", help="Skip video assembly and email")

    # Commande publish
    pub_parser = subparsers.add_parser("publish", help="Publish approved videos")
    pub_parser.add_argument(
        "--manifest",
        required=True,
        help="Path to review_manifest.json",
    )

    # Commande list-voices (utilitaire)
    subparsers.add_parser("list-voices", help="List available ElevenLabs voices")

    args = parser.parse_args()

    if args.command == "generate":
        run_generate(week_date=args.week, dry_run=args.dry_run)

    elif args.command == "publish":
        run_publish(manifest_path=args.manifest)

    elif args.command == "list-voices":
        from .voice import list_available_voices
        voices = list_available_voices()
        if voices:
            console.print("\nAvailable ElevenLabs voices:")
            for v in voices:
                console.print(f"  [{v['voice_id']}] {v['name']}")
        else:
            console.print("[red]No voices found (check ELEVENLABS_API_KEY)[/]")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
