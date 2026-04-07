"""
scorer_v2.py — Scoring unifié pour les 4 types de contenu

Gère Research Articles, Guidelines, Clinical Trials et Flashbacks dans un
scoring commun permettant de sélectionner la meilleure vidéo de la semaine
(1 par semaine), tous types confondus.

Politique de sélection :
  - 1 vidéo par semaine — le meilleur item toutes catégories confondues
  - Max 1 par type (ne peut de toute façon sélectionner qu'1 item)
  - Articles manuels proposés par Dr Dabi : score forcé à 99, sélection garantie
"""

import json
import logging
from typing import Optional
from openai import OpenAI

from . import config
from .content_types import ContentItem, ContentType, ScoredContentItem

logger = logging.getLogger(__name__)

# Quotas par type de contenu dans une sélection de 1
# (1 vidéo/semaine — le meilleur item toutes catégories)
CONTENT_TYPE_QUOTAS = {
    ContentType.RESEARCH_ARTICLE: {"min": 0, "max": 1},
    ContentType.GUIDELINE:        {"min": 0, "max": 1},
    ContentType.CLINICAL_TRIAL:   {"min": 0, "max": 1},
    ContentType.FLASHBACK:        {"min": 0, "max": 1},
}


def score_content_items(items: list[ContentItem]) -> list[ScoredContentItem]:
    """
    Score une liste de ContentItem (tous types mélangés) via GPT-4o.
    Traite par batch de 8 pour optimiser les coûts.
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    scored = []
    batch_size = 8

    for i in range(0, len(items), batch_size):
        batch = items[i: i + batch_size]
        logger.info(f"Scoring batch {i // batch_size + 1} ({len(batch)} items)...")

        batch_data = [
            {
                "index": j,
                "content_type": item.content_type.value,
                "uid": item.uid,
                "title": item.title,
                "abstract": item.abstract[:700],
                "source": item.source_name,
                "pub_date": item.pub_date,
                "extra": _extract_relevant_extra(item),
            }
            for j, item in enumerate(batch)
        ]

        prompt = f"""You are Dr. Yohann Dabi, a gynecologist and endometriosis researcher running
the "Endo Debrief" science communication channel (YouTube, Instagram, TikTok, Facebook).

Your weekly goal: select the 3 best pieces of content from a mixed pool of:
- Research articles (new studies)
- Clinical guidelines (new recommendations from ESHRE, ACOG, Cochrane, etc.)
- Clinical trials (recruiting, completed with results, or newly registered)

Score each item on 4 criteria (0-10):
1. scientific_impact: Methodological rigor, evidence level, source credibility
2. patient_relevance: Concrete impact on endo patients' daily life or treatment choices
3. pedagogical_value: How well this can be explained to a lay audience, novelty for viewers
4. viral_potential: Shareability, emotional resonance, hook strength, broad appeal

Scoring bonuses to apply internally:
- Guidelines from ESHRE/ACOG/Cochrane: +1 scientific_impact (authoritative source)
- Recruiting trials a patient can join: +2 patient_relevance
- Completed trial WITH results: +2 scientific_impact (primary data before publication)
- New trial from industry/NIH: +1 viral_potential (signals research direction)
- Articles with full-text available: mentioned in abstract field if applicable
- RCT (randomized controlled trial): +1 scientific_impact (highest evidence level)
- Flashback articles (highly cited, >5 years old): +1 pedagogical_value

CRITICAL REVIEW CRITERIA — also assess and return these for each item:
- funding_source: "industry", "public", "mixed", or "unknown" (look for pharma, NIH, grants)
- is_rct: true/false (randomized controlled trial or not)
- sample_size_adequate: true/false (>100 for clinical, >50 for mechanistic usually adequate)
- population_diverse: true/false (includes varied ethnicities, ages, severity grades)
- stats_reported: true/false (p-values or confidence intervals explicitly reported)
These will be used to auto-generate a specific, honest critical review in the video.

Also provide:
- topic_tag: one of [surgery, pain, fertility, biomarkers, imaging, genetics,
  microbiome, quality_of_life, treatment, epidemiology, trial_design,
  guideline_update, flashback, other]
- one_line_summary: One punchy sentence a patient would share (not academic)

Items to score:
{json.dumps(batch_data, ensure_ascii=False)}

Return a JSON array — one object per item:
[
  {{
    "index": 0,
    "uid": "...",
    "content_type": "research_article",
    "scientific_impact": 7,
    "patient_relevance": 8,
    "pedagogical_value": 7,
    "viral_potential": 6,
    "topic_tag": "surgery",
    "one_line_summary": "...",
    "funding_source": "public",
    "is_rct": false,
    "sample_size_adequate": true,
    "population_diverse": false,
    "stats_reported": true
  }},
  ...
]

Return ONLY the JSON array, no other text."""

        try:
            response = client.chat.completions.create(
                model=config.GPT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                # Pas de json_object ici : on veut un tableau JSON, pas un objet
            )

            raw = response.choices[0].message.content or ""

            # Extraire le tableau JSON même s'il est entouré de texte ou enveloppé
            import re as _re
            json_match = _re.search(r'\[.*\]', raw, _re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                # Essayer de parser directement (objet enveloppant)
                obj = json.loads(raw)
                if isinstance(obj, list):
                    result = obj
                elif isinstance(obj, dict):
                    result = next(
                        (v for v in obj.values() if isinstance(v, list)), []
                    )
                else:
                    raise ValueError(f"Unexpected GPT response format: {type(obj)}")

            for item_data in result:
                idx = item_data.get("index", 0)
                if idx < len(batch):
                    item = batch[idx]
                    scores = {
                        "scientific_impact": float(item_data.get("scientific_impact", 5)),
                        "patient_relevance": float(item_data.get("patient_relevance", 5)),
                        "pedagogical_value": float(item_data.get("pedagogical_value", 5)),
                        "viral_potential": float(item_data.get("viral_potential", 5)),
                    }
                    total = sum(scores.values())
                    critique_flags = {
                        "funding_source": item_data.get("funding_source", "unknown"),
                        "is_rct": item_data.get("is_rct", False),
                        "sample_size_adequate": item_data.get("sample_size_adequate", None),
                        "population_diverse": item_data.get("population_diverse", None),
                        "stats_reported": item_data.get("stats_reported", None),
                    }
                    scored.append(ScoredContentItem(
                        item=item,
                        scores=scores,
                        total_score=total,
                        summary=item_data.get("one_line_summary", item.title),
                        topic_tag=item_data.get("topic_tag", "other"),
                        critique_flags=critique_flags,
                    ))

        except Exception as e:
            logger.error(f"Scoring batch failed: {e}")
            for item in batch:
                scored.append(ScoredContentItem(
                    item=item,
                    scores={"scientific_impact": 5, "patient_relevance": 5,
                            "pedagogical_value": 5, "viral_potential": 5},
                    total_score=20.0,
                    summary=item.title,
                    topic_tag="other",
                ))

    return scored


def select_top_content(
    scored_items: list[ScoredContentItem],
    n: int = config.ARTICLES_PER_WEEK,
) -> list[ScoredContentItem]:
    """
    Sélectionne les N meilleurs items en respectant :
    1. Les quotas par type de contenu
    2. La diversité thématique (max 1 item par topic_tag)
    3. Le score total
    """
    sorted_items = sorted(scored_items, key=lambda x: x.total_score, reverse=True)

    selected: list[ScoredContentItem] = []
    type_counts: dict[ContentType, int] = {ct: 0 for ct in ContentType}
    used_topics: list[str] = []

    # Pass 1 : sélection avec respect des quotas et diversité des sujets
    for item in sorted_items:
        if len(selected) >= n:
            break

        ct = item.item.content_type
        max_allowed = CONTENT_TYPE_QUOTAS[ct]["max"]
        if type_counts[ct] >= max_allowed:
            continue

        # Limiter les doublons thématiques
        topic = item.topic_tag
        if used_topics.count(topic) >= 1:
            continue

        selected.append(item)
        type_counts[ct] += 1
        used_topics.append(topic)

    # Pass 2 : compléter si pas assez (assoupir les contraintes de topic)
    if len(selected) < n:
        for item in sorted_items:
            if item in selected:
                continue
            ct = item.item.content_type
            if type_counts[ct] >= CONTENT_TYPE_QUOTAS[ct]["max"]:
                continue
            selected.append(item)
            type_counts[ct] += 1
            if len(selected) >= n:
                break

    # Pass 3 : si toujours pas assez (uniquement articles de recherche)
    if len(selected) < n:
        for item in sorted_items:
            if item not in selected:
                selected.append(item)
            if len(selected) >= n:
                break

    # Vérifier le quota minimum d'articles de recherche
    research_count = sum(
        1 for s in selected if s.item.content_type == ContentType.RESEARCH_ARTICLE
    )
    if research_count < CONTENT_TYPE_QUOTAS[ContentType.RESEARCH_ARTICLE]["min"]:
        logger.warning(
            f"Less than minimum research articles selected ({research_count}). "
            "Consider extending the search window."
        )

    logger.info(
        f"Selected {len(selected)} items: "
        + ", ".join(
            f"{s.item.content_type.value}({s.item.uid})"
            for s in selected
        )
    )
    return selected[:n]


def run_unified_scoring(
    items: list[ContentItem],
    forced_items: list[ContentItem] | None = None,
) -> list[ScoredContentItem]:
    """
    Point d'entrée principal.

    forced_items : articles manuels proposés par Dr Dabi — leur score est forcé
                   à 99/40 pour garantir leur sélection en tête de liste.
    """
    if not items:
        raise ValueError("No content items to score")

    forced_uids = {i.uid for i in (forced_items or [])}

    logger.info(
        f"Scoring {len(items)} items "
        f"({sum(1 for i in items if i.content_type == ContentType.RESEARCH_ARTICLE)} articles, "
        f"{sum(1 for i in items if i.content_type == ContentType.GUIDELINE)} guidelines, "
        f"{sum(1 for i in items if i.content_type == ContentType.CLINICAL_TRIAL)} trials)"
    )
    if forced_uids:
        logger.info(f"Force-selected UIDs (manual): {forced_uids}")

    scored = score_content_items(items)

    # Forcer le score des articles manuels à 99 pour garantir leur sélection
    for s in scored:
        if s.item.uid in forced_uids:
            s.total_score = 99.0
            logger.info(f"  ↑ Manual override: {s.item.uid} score set to 99")

    top = select_top_content(scored)

    for i, item in enumerate(top, 1):
        manual_tag = " [MANUAL]" if item.item.uid in forced_uids else ""
        logger.info(
            f"#{i} [{item.item.content_type_label}]{manual_tag} "
            f"score={item.total_score:.0f}/40 "
            f"topic={item.topic_tag} — {item.item.title[:60]}..."
        )

    return top


def _extract_relevant_extra(item: ContentItem) -> dict:
    """Extrait les champs extra pertinents pour le scoring selon le type."""
    if item.content_type == ContentType.CLINICAL_TRIAL:
        return {
            "status": item.extra_data.get("status", ""),
            "phase": item.extra_data.get("phase", ""),
            "enrollment": item.extra_data.get("enrollment", 0),
            "has_results": item.extra_data.get("results_available", False),
            "sponsor_class": "",  # NIH vs industry
        }
    elif item.content_type == ContentType.GUIDELINE:
        return {
            "organization": item.extra_data.get("organization", ""),
            "guideline_type": item.extra_data.get("guideline_type", ""),
        }
    else:
        return {
            "publication_types": item.extra_data.get("publication_types", [])[:3],
            "journal": item.source_name,
        }
