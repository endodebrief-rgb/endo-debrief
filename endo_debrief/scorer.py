"""
scorer.py — Sélection des meilleurs articles par GPT-4o
Évalue chaque article selon plusieurs critères et sélectionne les 3 meilleurs
pour la semaine.

Critères de scoring :
- Impact scientifique (design d'étude, journal, taille d'échantillon)
- Pertinence pour les patientes
- Potentiel pédagogique (clarté, nouveauté)
- Potentiel viral (surprenant, important, accessible)
- Diversité thématique (éviter 3 articles sur le même sujet)
"""

import json
import logging
from openai import OpenAI

from . import config
from .pubmed import PubMedArticle

logger = logging.getLogger(__name__)


class ScoredArticle:
    """Article PubMed avec son score et sa justification."""

    def __init__(self, article: PubMedArticle, scores: dict, summary: str):
        self.article = article
        self.scores = scores          # {scientific, patient_relevance, pedagogical, viral}
        self.total_score = sum(scores.values())
        self.summary = summary        # Résumé en 1 phrase de l'article
        self.topic_tag = scores.get("topic_tag", "general")

    def __repr__(self):
        return (
            f"ScoredArticle(score={self.total_score:.1f}, "
            f"title={self.article.title[:50]}...)"
        )


def score_articles(articles: list[PubMedArticle]) -> list[ScoredArticle]:
    """
    Utilise GPT-4o pour scorer chaque article.
    Traite par batch de 10 pour optimiser les coûts API.
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    scored = []

    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch = articles[i : i + batch_size]
        logger.info(f"Scoring batch {i//batch_size + 1} ({len(batch)} articles)...")

        batch_data = [
            {
                "index": j,
                "pmid": a.pmid,
                "title": a.title,
                "abstract": a.abstract[:800],  # Limiter pour économiser des tokens
                "journal": a.journal,
                "publication_types": a.publication_types[:3],
                "authors_count": len(a.authors),
            }
            for j, a in enumerate(batch)
        ]

        prompt = f"""You are a medical scientist and science communicator specialized in endometriosis.

Evaluate each of the following PubMed articles for a weekly science video series called "Endo Debrief".
The audience is primarily endometriosis patients (who want to understand research in plain language)
and secondarily scientists/clinicians (who want rigorous critical analysis).

Score each article on 4 criteria (0-10 each):
1. scientific_impact: Study design quality (RCT=10, meta-analysis=9, cohort=7, case-control=6, case series=4, review=5), sample size, journal prestige
2. patient_relevance: How much this finding matters for daily life / treatment of endo patients
3. pedagogical_value: How well this can be explained visually, clarity of findings, novelty
4. viral_potential: Surprising results, emotional resonance, broad appeal, shareability

Also provide:
- topic_tag: one of [surgery, pain, fertility, biomarkers, imaging, genetics, microbiome, endocannabinoids, quality_of_life, treatment, epidemiology, other]
- one_line_summary: One engaging sentence summarizing the key finding in plain English for patients

Articles to evaluate:
{json.dumps(batch_data, ensure_ascii=False)}

Return a JSON array with one object per article:
[
  {{
    "index": 0,
    "pmid": "...",
    "scientific_impact": 7,
    "patient_relevance": 8,
    "pedagogical_value": 6,
    "viral_potential": 7,
    "topic_tag": "surgery",
    "one_line_summary": "..."
  }},
  ...
]

Return ONLY the JSON array, no other text."""

        try:
            response = client.chat.completions.create(
                model=config.GPT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            # Parser la réponse
            raw = response.choices[0].message.content
            result = json.loads(raw)

            # GPT peut retourner un objet ou un array
            if isinstance(result, dict):
                result = result.get("articles", result.get("results", list(result.values())[0]))

            for item in result:
                idx = item.get("index", 0)
                if idx < len(batch):
                    article = batch[idx]
                    scores = {
                        "scientific_impact": float(item.get("scientific_impact", 5)),
                        "patient_relevance": float(item.get("patient_relevance", 5)),
                        "pedagogical_value": float(item.get("pedagogical_value", 5)),
                        "viral_potential": float(item.get("viral_potential", 5)),
                        "topic_tag": item.get("topic_tag", "other"),
                    }
                    summary = item.get("one_line_summary", article.title)
                    scored.append(ScoredArticle(article, scores, summary))

        except Exception as e:
            logger.error(f"Scoring batch failed: {e}")
            # Fallback : score neutre pour tous les articles du batch
            for article in batch:
                default_scores = {
                    "scientific_impact": 5.0,
                    "patient_relevance": 5.0,
                    "pedagogical_value": 5.0,
                    "viral_potential": 5.0,
                    "topic_tag": "other",
                }
                scored.append(ScoredArticle(article, default_scores, article.title))

    return scored


def select_top_articles(
    scored_articles: list[ScoredArticle],
    n: int = config.ARTICLES_PER_WEEK,
) -> list[ScoredArticle]:
    """
    Sélectionne les N meilleurs articles en assurant la diversité thématique.
    Évite de sélectionner 3 articles sur le même sujet.
    """
    # Trier par score total décroissant
    sorted_articles = sorted(scored_articles, key=lambda x: x.total_score, reverse=True)

    selected = []
    used_topics = []

    # Premier passage : prendre les meilleurs avec diversité de sujets
    for article in sorted_articles:
        if len(selected) >= n:
            break
        topic = article.topic_tag

        # Accepter l'article si le sujet n'est pas encore surreprésenté
        topic_count = used_topics.count(topic)
        if topic_count < 2:  # Max 1 article par sujet dans la sélection de 3
            selected.append(article)
            used_topics.append(topic)

    # Si pas assez d'articles, compléter sans contrainte de diversité
    if len(selected) < n:
        for article in sorted_articles:
            if article not in selected:
                selected.append(article)
            if len(selected) >= n:
                break

    logger.info(
        f"Selected {len(selected)} articles: "
        + ", ".join(f"{a.article.pmid} ({a.topic_tag})" for a in selected)
    )
    return selected[:n]


def run_scoring(articles: list[PubMedArticle]) -> list[ScoredArticle]:
    """
    Point d'entrée principal du module de scoring.
    """
    if not articles:
        raise ValueError("No articles to score")

    logger.info(f"Scoring {len(articles)} articles with GPT-4o...")
    scored = score_articles(articles)

    logger.info(f"Selecting top {config.ARTICLES_PER_WEEK} articles...")
    top = select_top_articles(scored)

    # Log des sélections
    for i, article in enumerate(top, 1):
        logger.info(
            f"#{i} (score={article.total_score:.1f}) [{article.topic_tag}] "
            f"{article.article.title[:70]}..."
        )

    return top
