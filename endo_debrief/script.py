"""
script.py — Génération des scripts vidéo par GPT-4o

Chaque script est structuré en sections narratives avec timecodes estimés.
Le script est conçu pour être lu avec la voix clonée du Dr Dabi.

Structure narrative :
  [HOOK]         ~15s  — Accroche choc pour retenir l'attention dès les 3 premières secondes
  [PAPER]        ~20s  — Présentation de la publication
  [BACKGROUND]   ~40s  — Contexte : pourquoi ce sujet est crucial pour les patientes
  [METHODS]      ~35s  — Ce qu'ils ont fait, en langage simple
  [RESULTS]      ~70s  — Résultats clés avec données chiffrées
  [CRITICAL]     ~45s  — Revue critique : limites, biais, ce que ça signifie vraiment
  [TAKE_HOME]    ~25s  — Message clé patient + message clé scientifique
  [OUTRO]        ~10s  — Call to action + branding

Total : ~4 minutes (format long YouTube)
Version courte (Reels/TikTok) : extrait automatique de 75 secondes
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional
from openai import OpenAI

from . import config
from .scorer import ScoredArticle
from .fulltext import FullTextResult, FullTextSource

logger = logging.getLogger(__name__)


@dataclass
class VideoSection:
    """Une section du script vidéo."""
    name: str
    narration: str       # Texte à lire (voix off)
    slide_title: str     # Titre affiché sur la slide
    slide_bullets: list[str]  # Points clés affichés
    visual_prompt: str   # Prompt DALL-E pour l'illustration (si besoin)
    duration_s: int      # Durée estimée en secondes


@dataclass
class VideoScript:
    """Script complet d'une vidéo."""
    article_pmid: str
    article_title: str
    video_title: str         # Titre optimisé pour YouTube/TikTok
    video_description: str   # Description pour YouTube
    hashtags: list[str]      # Hashtags pour toutes plateformes
    sections: list[VideoSection]
    short_script: str        # Version condensée 75s pour Reels/TikTok
    short_title: str         # Titre court pour TikTok

    @property
    def full_narration(self) -> str:
        """Texte complet à synthétiser en voix off."""
        return "\n\n".join(s.narration for s in self.sections)

    @property
    def short_narration(self) -> str:
        return self.short_script

    @property
    def total_duration(self) -> int:
        return sum(s.duration_s for s in self.sections)


def generate_video_script(
    scored_article: ScoredArticle,
    full_text_result: Optional[FullTextResult] = None,
) -> VideoScript:
    """
    Génère le script complet d'une vidéo à partir d'un article scoré.

    Si full_text_result est fourni et contient le texte intégral, GPT-4o
    peut accéder aux sections Methods, Results et Discussion complètes,
    ce qui améliore significativement la qualité de la revue critique.
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    article = scored_article.article

    has_full_text = full_text_result is not None and full_text_result.has_full_text
    source_label = full_text_result.source.value if full_text_result else "abstract only"

    logger.info(
        f"Generating script for: {article.title[:60]}... "
        f"[{source_label}]"
    )

    system_prompt = """You are Dr. Yohann Dabi, a gynecologist and endometriosis researcher.
You create educational science videos called "Endo Debrief" that explain recent endometriosis research
to patients and the scientific community.

Your style is:
- Clear and accessible but scientifically rigorous
- Empathetic towards patients living with endometriosis
- Honest about study limitations (you never oversell results)
- Engaging and dynamic — you hook the audience immediately
- Evidence-based, data-driven

Voice tone: warm, authoritative, concerned, a bit passionate about endo research."""

    # Construire le contexte documentaire selon disponibilité du texte intégral
    fulltext_context = ""
    critical_note = ""

    if has_full_text and full_text_result:
        ft = full_text_result

        # Extraire les sections clés pour le prompt (limiter pour économiser des tokens)
        methods = ft.methods_text[:1500] if ft.methods_text else ""
        results = ft.results_text[:2000] if ft.results_text else ""
        discussion = ft.discussion_text[:1500] if ft.discussion_text else ""

        # Si pas de sections structurées, utiliser le texte brut
        if not methods and not results and ft.text:
            fulltext_context = f"\nFULL TEXT EXCERPT (first 4000 chars):\n{ft.text[:4000]}"
        else:
            if methods:
                fulltext_context += f"\nMETHODS (full):\n{methods}"
            if results:
                fulltext_context += f"\nRESULTS (full):\n{results}"
            if discussion:
                fulltext_context += f"\nDISCUSSION (full):\n{discussion}"

        critical_note = (
            "You have access to the FULL TEXT of this article. "
            "Use the Methods section for precise study design critique, "
            "the Results for exact figures and statistics, "
            "and the Discussion for the authors' own assessment of limitations."
        )
    else:
        critical_note = (
            "⚠️ IMPORTANT: You only have access to the ABSTRACT of this article. "
            "The full text is behind a paywall. "
            "Be transparent about this limitation in the Critical Review section: "
            "explicitly mention which limitations you can identify from the abstract alone "
            "and note that a full methodological critique would require access to the complete paper. "
            "Do NOT speculate about methodological details not mentioned in the abstract."
        )

    user_prompt = f"""Generate a complete video script for the following PubMed article:

TITLE: {article.title}
JOURNAL: {article.journal} ({article.pub_date})
AUTHORS: {", ".join(article.authors[:3])}
DOI: {article.doi}
PUBMED URL: {article.url}
PUBLICATION TYPES: {", ".join(article.publication_types[:3])}
KEYWORDS: {", ".join(article.keywords[:8])}
FULL TEXT AVAILABLE: {"YES — " + full_text_result.source.value if has_full_text else "NO — abstract only"}

ABSTRACT:
{article.abstract}
{fulltext_context}

ONE-LINE PATIENT SUMMARY (use this as inspiration for the hook):
{scored_article.summary}

CRITICAL REVIEW INSTRUCTIONS:
{critical_note}

Generate a JSON response with this exact structure:

{{
  "video_title": "Engaging YouTube title (max 70 chars, includes key finding, uses 'New Study:', 'Researchers Discover:', etc.)",
  "short_title": "TikTok/Reels title (max 40 chars, punchy)",
  "video_description": "YouTube description (300-400 words): includes what the video covers, key findings, paper reference, disclaimer, and call to action)",
  "hashtags": ["endometriosis", "endo", "endoresearch", "science", "womenshealth", "endodebrief", "pubmed", ...],

  "sections": [
    {{
      "name": "HOOK",
      "narration": "The spoken text (15-20 seconds). Start with a shocking statistic or provocative question. Make the viewer stop scrolling immediately.",
      "slide_title": "Bold hook statement shown on screen (max 8 words)",
      "slide_bullets": [],
      "visual_prompt": "DALL-E prompt for a powerful opening visual (medical, symbolic, emotional)",
      "duration_s": 17
    }},
    {{
      "name": "PAPER",
      "narration": "Introduce the paper: journal, authors, country, year. What kind of study is this?",
      "slide_title": "Published in [Journal]",
      "slide_bullets": ["[Journal name] — [Year]", "[Number] of [patients/samples]", "[Country/institution]"],
      "visual_prompt": "",
      "duration_s": 18
    }},
    {{
      "name": "BACKGROUND",
      "narration": "Why does this research topic matter? What do we already know? What gap does this study fill? Make patients feel seen.",
      "slide_title": "Why this matters",
      "slide_bullets": ["Key fact 1 about endo", "Key fact 2", "The unanswered question this study addresses"],
      "visual_prompt": "DALL-E prompt for a medical illustration showing the biological mechanism being studied",
      "duration_s": 40
    }},
    {{
      "name": "METHODS",
      "narration": "Explain the study design in plain English. Who were the participants? What did the researchers actually do? Keep it simple but accurate.",
      "slide_title": "What they did",
      "slide_bullets": ["Study design (e.g., 'Randomized controlled trial')", "N = X patients", "Key measurement / intervention"],
      "visual_prompt": "",
      "duration_s": 35
    }},
    {{
      "name": "RESULTS",
      "narration": "Present the key findings with specific numbers. Use comparisons patients can understand. What was statistically significant? What was the effect size?",
      "slide_title": "Key Findings",
      "slide_bullets": ["Finding 1 with specific number/percentage", "Finding 2", "Finding 3 (if relevant)"],
      "visual_prompt": "DALL-E prompt for a clear visual representation of the main result (graph concept, comparison visual)",
      "duration_s": 70
    }},
    {{
      "name": "CRITICAL",
      "narration": "Now the critical review. What are the study limitations? What biases exist? Is the sample size adequate? Can we generalize the findings? What should patients NOT conclude from this? Be honest and measured.",
      "slide_title": "⚠️ Critical Review",
      "slide_bullets": ["Limitation 1: (specific)", "Limitation 2: (specific)", "What this means / doesn't mean"],
      "visual_prompt": "",
      "duration_s": 45
    }},
    {{
      "name": "TAKE_HOME",
      "narration": "Two take-home messages: one for patients, one for clinicians/researchers. Clear, actionable, honest.",
      "slide_title": "Take-Home Message",
      "slide_bullets": ["👩 For patients: [one sentence]", "🔬 For researchers: [one sentence]"],
      "visual_prompt": "",
      "duration_s": 25
    }},
    {{
      "name": "OUTRO",
      "narration": "This was Endo Debrief. If this video helped you understand endometriosis research better, share it with someone who needs it. New debrief every week. Subscribe and turn on notifications.",
      "slide_title": "Endo Debrief",
      "slide_bullets": ["New episode every week", "Subscribe for more science"],
      "visual_prompt": "",
      "duration_s": 10
    }}
  ],

  "short_script": "A 70-80 second condensed version for TikTok/Instagram Reels. Hook (10s) → Key finding (25s) → Critical note (15s) → Take-home + CTA (15s). Written as continuous narration."
}}

IMPORTANT:
- Write all narration in English only
- Be specific with numbers from the abstract
- Never make up data not in the abstract
- The critical review must be genuinely critical, not just 'more research is needed'
- The hook must make someone STOP scrolling — use a striking stat or question"""

    try:
        response = client.chat.completions.create(
            model=config.GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
            max_tokens=4000,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        # Construire les sections
        sections = []
        for s in data.get("sections", []):
            sections.append(VideoSection(
                name=s.get("name", ""),
                narration=s.get("narration", ""),
                slide_title=s.get("slide_title", ""),
                slide_bullets=s.get("slide_bullets", []),
                visual_prompt=s.get("visual_prompt", ""),
                duration_s=int(s.get("duration_s", 20)),
            ))

        return VideoScript(
            article_pmid=article.pmid,
            article_title=article.title,
            video_title=data.get("video_title", article.title[:70]),
            video_description=data.get("video_description", ""),
            hashtags=data.get("hashtags", config.YOUTUBE_DEFAULT_TAGS),
            sections=sections,
            short_script=data.get("short_script", ""),
            short_title=data.get("short_title", article.title[:40]),
        )

    except Exception as e:
        logger.error(f"Script generation failed for {article.pmid}: {e}")
        raise


# ── Scripts pour les Guidelines ───────────────────────────────────────────────

def generate_guideline_script(scored_item) -> VideoScript:
    """
    Génère un script adapté aux recommandations cliniques.
    Structure narrative différente : focus sur les changements de pratique.
    """
    from .content_types import ContentType
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    item = scored_item.item
    extra = item.extra_data

    logger.info(f"Generating GUIDELINE script for: {item.title[:60]}...")

    system_prompt = """You are Dr. Yohann Dabi, a gynecologist specializing in endometriosis.
You create educational videos explaining new clinical guidelines to endometriosis patients.

Your role with guidelines:
- Explain WHAT changed from previous recommendations
- Explain WHY it changed (new evidence, expert consensus)
- Explain WHAT THIS MEANS FOR PATIENTS concretely (ask your doctor about X, treatment Y is now recommended, etc.)
- Be honest about what's still debated or uncertain
- Never oversimplify complex clinical nuances"""

    user_prompt = f"""Generate a complete video script for this clinical guideline/recommendation:

TITLE: {item.title}
SOURCE / ORGANIZATION: {item.source_name or extra.get('organization', 'Unknown')}
TYPE: {extra.get('guideline_type', 'Guideline')}
DATE: {item.pub_date}
URL: {item.url}

CONTENT:
{item.abstract}

ONE-LINE PATIENT SUMMARY:
{scored_item.summary}

Generate a JSON response with the same structure as research article scripts but with
these section names adapted for a guideline video:

SECTIONS (in order):
- HOOK (15s): Why do these recommendations matter? What's at stake for endo patients?
- CONTEXT (22s): What organization issued this? What authority do they have? What was the old guideline?
- BACKGROUND (35s): Why was an update needed? What new evidence triggered the change?
- CHANGES (80s): The key new recommendations — explained clearly one by one
- IMPACT (50s): What does this CONCRETELY change for patients? What should they ask their doctor?
- CRITICAL (40s): What's still debated? What the guideline doesn't cover? Limitations?
- TAKE_HOME (25s): The 2-3 things every endo patient should know from this guideline
- OUTRO (10s): Subscribe, share

Same JSON output format as before (video_title, short_title, video_description, hashtags, sections, short_script).

IMPORTANT:
- Be very concrete about what patients should DO differently as a result
- Include specific recommendation grades (Grade A, B, C or GRADE, OXFORD) if mentioned
- The CHANGES section is the heart of the video — be thorough but accessible
- Hashtags should include: endometriosis, endoguidelines, endotreatment, eshre (if applicable)"""

    try:
        response = client.chat.completions.create(
            model=config.GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            response_format={"type": "json_object"},
            max_tokens=4000,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        sections = [
            VideoSection(
                name=s.get("name", ""),
                narration=s.get("narration", ""),
                slide_title=s.get("slide_title", ""),
                slide_bullets=s.get("slide_bullets", []),
                visual_prompt=s.get("visual_prompt", ""),
                duration_s=int(s.get("duration_s", 20)),
            )
            for s in data.get("sections", [])
        ]

        guideline_hashtags = list(set(
            config.YOUTUBE_DEFAULT_TAGS
            + ["endoguidelines", "endotreatment", "medicalresearch",
               extra.get("organization", "").lower().replace(" ", "")]
        ))

        return VideoScript(
            article_pmid=item.uid,
            article_title=item.title,
            video_title=data.get("video_title", item.title[:70]),
            video_description=data.get("video_description", ""),
            hashtags=data.get("hashtags", guideline_hashtags),
            sections=sections,
            short_script=data.get("short_script", ""),
            short_title=data.get("short_title", item.title[:40]),
        )

    except Exception as e:
        logger.error(f"Guideline script generation failed for {item.uid}: {e}")
        raise


# ── Scripts pour les Essais Cliniques ─────────────────────────────────────────

def generate_trial_script(scored_item) -> VideoScript:
    """
    Génère un script adapté aux essais cliniques ClinicalTrials.gov.
    Angles différents selon le statut : recruiting / completed / new.
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    item = scored_item.item
    extra = item.extra_data

    logger.info(f"Generating TRIAL script for: {item.title[:60]}...")

    status = extra.get("status", "UNKNOWN")
    has_results = extra.get("results_available", False)

    if has_results:
        angle = "RESULTS AVAILABLE"
        angle_instruction = (
            "Focus on the trial RESULTS: What did they find? "
            "Was the primary endpoint met? What does it mean for endo patients? "
            "Is this treatment likely to become standard of care?"
        )
    elif status in ("RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"):
        angle = "RECRUITING — PATIENTS CAN PARTICIPATE"
        angle_instruction = (
            "Focus on PARTICIPATION: Who can join? What's involved? "
            "What's the potential benefit? How to apply? "
            "Be very practical — this video helps patients decide if they want to participate."
        )
    else:
        angle = "NEW TRIAL — RESEARCH SIGNAL"
        angle_instruction = (
            "Focus on WHY this trial matters: What hypothesis are researchers testing? "
            "Why now? What's the innovation? What does it signal about where research is going?"
        )

    system_prompt = f"""You are Dr. Yohann Dabi, a gynecologist explaining clinical trials to endo patients.

This video is about a clinical trial ({angle}).
{angle_instruction}

Your approach with clinical trials:
- Explain the study design simply (what is randomized, what are the arms, what is blinded)
- Be very clear about eligibility criteria (key inclusion/exclusion criteria)
- Be honest about uncertainty (phase I/II = safety, not efficacy yet)
- Never create unrealistic hope — explain what phase the trial is in
- For recruiting trials: provide practical info (locations, contact)"""

    user_prompt = f"""Generate a video script for this clinical trial:

NCT ID: {item.uid}
TITLE: {item.title}
STATUS: {status}
PHASE: {extra.get('phase', 'N/A')}
ENROLLMENT TARGET: {extra.get('enrollment', 'N/A')} participants
LEAD SPONSOR: {extra.get('lead_sponsor', item.source_name)} ({extra.get('sponsor_class', '')})
LOCATIONS (sample): {', '.join(extra.get('locations', [])[:3]) or 'Multiple locations'}
HAS RESULTS: {has_results}
PRIMARY OUTCOME: {extra.get('primary_outcome', 'N/A')}

DESCRIPTION:
{item.abstract}

ONE-LINE PATIENT SUMMARY:
{scored_item.summary}

VIDEO ANGLE: {angle}

SECTIONS (in order):
- HOOK (15s): Attention-grabbing opening about this trial
- TRIAL_INFO (22s): NCT number, phase, sponsor type (academic vs industry), locations
- HYPOTHESIS (38s): What are they testing and why? What gap does this fill?
- DESIGN (45s): How is the trial structured? Arms, randomization, blinding
- WHAT_TESTED (48s): The intervention — drug, device, surgery, etc. in simple terms
- TIMELINE (32s): Start date, completion date, how to find out more / apply
- CRITICAL (40s): Potential bias (sponsor), early phase = safety not efficacy, etc.
- TAKE_HOME (25s): {'Can I participate? How? What should I do next?' if status in ['RECRUITING', 'ENROLLING_BY_INVITATION'] else 'What do these results mean for future treatment?'}
- OUTRO (10s): Subscribe

Same JSON format (video_title, short_title, video_description, hashtags, sections, short_script).

Hashtags should include: endometriosis, clinicaltrial, endoresearch, endowarrior, nctid"""

    try:
        response = client.chat.completions.create(
            model=config.GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
            max_tokens=4000,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        sections = [
            VideoSection(
                name=s.get("name", ""),
                narration=s.get("narration", ""),
                slide_title=s.get("slide_title", ""),
                slide_bullets=s.get("slide_bullets", []),
                visual_prompt=s.get("visual_prompt", ""),
                duration_s=int(s.get("duration_s", 20)),
            )
            for s in data.get("sections", [])
        ]

        trial_hashtags = config.YOUTUBE_DEFAULT_TAGS + [
            "clinicaltrial", "endoresearch", f"#{item.uid.lower()}"
        ]

        return VideoScript(
            article_pmid=item.uid,
            article_title=item.title,
            video_title=data.get("video_title", item.title[:70]),
            video_description=data.get("video_description", ""),
            hashtags=data.get("hashtags", trial_hashtags),
            sections=sections,
            short_script=data.get("short_script", ""),
            short_title=data.get("short_title", item.title[:40]),
        )

    except Exception as e:
        logger.error(f"Trial script generation failed for {item.uid}: {e}")
        raise


# ── Dispatcher unifié ─────────────────────────────────────────────────────────


def generate_script_for_item(
    scored_item,  # ScoredContentItem
    full_text_results: Optional[dict] = None,
) -> VideoScript:
    """
    Dispatcher : génère le script adapté selon le type de contenu.
    Redirige vers generate_video_script, generate_guideline_script,
    ou generate_trial_script selon item.content_type.
    """
    from .content_types import ContentType

    ct = scored_item.item.content_type

    if ct == ContentType.RESEARCH_ARTICLE:
        # Compatibilité avec l'ancien système (ScoredArticle wrappé)
        # On crée un ScoredArticle minimal depuis le ScoredContentItem
        from .pubmed import PubMedArticle
        item = scored_item.item
        extra = item.extra_data

        # Reconstruire un PubMedArticle depuis ContentItem
        pubmed_article = PubMedArticle({
            "pmid": item.uid,
            "title": item.title,
            "abstract": item.abstract,
            "authors": item.authors,
            "journal": item.source_name,
            "pub_date": item.pub_date,
            "doi": extra.get("doi", ""),
            "keywords": extra.get("keywords", []),
            "publication_types": extra.get("publication_types", []),
        })

        # Wrapper en ScoredArticle pour compatibilité
        class _FakeScoredArticle:
            def __init__(self, a, s):
                self.article = a
                self.scores = s.scores
                self.total_score = s.total_score
                self.summary = s.summary
                self.topic_tag = s.topic_tag

        fake = _FakeScoredArticle(pubmed_article, scored_item)

        full_text_results = full_text_results or {}
        ft_result = full_text_results.get(item.uid)
        return generate_video_script(fake, full_text_result=ft_result)

    elif ct == ContentType.GUIDELINE:
        return generate_guideline_script(scored_item)

    elif ct == ContentType.CLINICAL_TRIAL:
        return generate_trial_script(scored_item)

    else:
        raise ValueError(f"Unknown content type: {ct}")


def generate_all_scripts(
    scored_items: list,   # list[ScoredContentItem] (tous types)
    full_text_results: Optional[dict] = None,   # {pmid: FullTextResult}
) -> list[VideoScript]:
    """
    Génère les scripts pour tous les items sélectionnés (tous types confondus).

    Arguments:
        scored_items       : liste des ScoredContentItem sélectionnés
        full_text_results  : dict optionnel {pmid: FullTextResult} depuis fulltext.py
    """
    from .content_types import ContentType
    full_text_results = full_text_results or {}
    scripts = []

    for item in scored_items:
        uid = item.item.uid
        ct = item.item.content_type

        try:
            script = generate_script_for_item(item, full_text_results=full_text_results)
            scripts.append(script)

            ft_status = ""
            if ct == ContentType.RESEARCH_ARTICLE:
                ft = full_text_results.get(uid)
                ft_status = (
                    f" [full text: {ft.source.value}]" if ft and ft.has_full_text
                    else " [abstract only]"
                )

            logger.info(
                f"✓ Script [{item.item.content_type_label}]: "
                f"{script.video_title[:60]}{ft_status}"
            )
        except Exception as e:
            logger.error(f"✗ Failed to generate script for {uid} ({ct.value}): {e}")

    return scripts
