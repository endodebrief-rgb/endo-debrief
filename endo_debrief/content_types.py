"""
content_types.py — Classes unifiées pour tous les types de contenu Endo Debrief

Le pipeline peut traiter 3 types de contenus distincts,
chacun avec sa propre structure narrative et ses sources :

  1. RESEARCH_ARTICLE  — Articles PubMed (études originales, reviews, méta-analyses)
  2. GUIDELINE         — Recommandations cliniques (ESHRE, ACOG, HAS, Cochrane...)
  3. CLINICAL_TRIAL    — Essais cliniques (ClinicalTrials.gov)

Tous partagent une interface commune `ContentItem` utilisée par le scorer,
le générateur de scripts, et le pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ContentType(Enum):
    RESEARCH_ARTICLE = "research_article"
    GUIDELINE        = "guideline"
    CLINICAL_TRIAL   = "clinical_trial"


class TrialStatus(Enum):
    RECRUITING        = "RECRUITING"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    COMPLETED         = "COMPLETED"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    TERMINATED        = "TERMINATED"
    WITHDRAWN         = "WITHDRAWN"
    UNKNOWN           = "UNKNOWN"


@dataclass
class ContentItem:
    """
    Classe de base unifiée pour tous les types de contenu.
    Utilisée par le scorer et le générateur de scripts.
    """
    # Identifiants
    content_type: ContentType
    uid: str                        # PMID, NCT number, ou identifiant guideline
    title: str
    url: str

    # Texte source
    abstract: str = ""             # Résumé / description / objectif principal
    full_text: str = ""            # Texte intégral si disponible

    # Métadonnées communes
    source_name: str = ""          # Nom de la source (journal, organisme, registre)
    pub_date: str = ""             # Date de publication ou de mise à jour
    authors: list[str] = field(default_factory=list)

    # Métadonnées spécifiques (stockées dans extra_data)
    extra_data: dict = field(default_factory=dict)

    # Statut d'accès
    has_full_text: bool = False
    is_paywalled: bool = False
    full_text_source: str = ""

    @property
    def content_type_label(self) -> str:
        labels = {
            ContentType.RESEARCH_ARTICLE: "Research Article",
            ContentType.GUIDELINE:        "Clinical Guideline",
            ContentType.CLINICAL_TRIAL:   "Clinical Trial",
        }
        return labels.get(self.content_type, "Unknown")

    @property
    def type_emoji(self) -> str:
        emojis = {
            ContentType.RESEARCH_ARTICLE: "🔬",
            ContentType.GUIDELINE:        "📋",
            ContentType.CLINICAL_TRIAL:   "🧪",
        }
        return emojis.get(self.content_type, "📄")

    def to_dict(self) -> dict:
        return {
            "content_type": self.content_type.value,
            "uid": self.uid,
            "title": self.title,
            "url": self.url,
            "abstract": self.abstract,
            "source_name": self.source_name,
            "pub_date": self.pub_date,
            "authors": self.authors,
            "has_full_text": self.has_full_text,
            "is_paywalled": self.is_paywalled,
            "extra_data": self.extra_data,
        }


@dataclass
class ScoredContentItem:
    """ContentItem scoré, avec justification éditoriale."""
    item: ContentItem
    scores: dict                   # {scientific, patient_relevance, pedagogical, viral}
    total_score: float
    summary: str                   # Résumé en 1 phrase pour les patientes
    topic_tag: str = "general"

    def __repr__(self):
        return (
            f"ScoredContentItem(type={self.item.content_type.value}, "
            f"score={self.total_score:.1f}, title={self.item.title[:50]}...)"
        )


# ── Helpers pour créer des ContentItem depuis les sources ─────────────────────

def from_pubmed_article(article) -> ContentItem:
    """Convertit un PubMedArticle en ContentItem."""
    from .pubmed import PubMedArticle
    return ContentItem(
        content_type=ContentType.RESEARCH_ARTICLE,
        uid=article.pmid,
        title=article.title,
        url=article.url,
        abstract=article.abstract,
        source_name=article.journal,
        pub_date=article.pub_date,
        authors=article.authors,
        extra_data={
            "doi": article.doi,
            "keywords": article.keywords,
            "publication_types": article.publication_types,
        },
    )


def from_clinical_trial(trial: dict) -> ContentItem:
    """Convertit un trial ClinicalTrials.gov en ContentItem."""
    nct_id = trial.get("nctId", "")
    return ContentItem(
        content_type=ContentType.CLINICAL_TRIAL,
        uid=nct_id,
        title=trial.get("briefTitle", ""),
        url=f"https://clinicaltrials.gov/study/{nct_id}",
        abstract=trial.get("briefSummary", ""),
        source_name="ClinicalTrials.gov",
        pub_date=trial.get("startDate", trial.get("lastUpdateDate", "")),
        authors=[trial.get("leadSponsor", "")],
        extra_data={
            "status": trial.get("overallStatus", ""),
            "phase": trial.get("phase", ""),
            "enrollment": trial.get("enrollmentCount", 0),
            "conditions": trial.get("conditions", []),
            "interventions": trial.get("interventions", []),
            "locations": trial.get("locations", []),
            "primary_outcome": trial.get("primaryOutcome", ""),
            "eligibility": trial.get("eligibilityCriteria", ""),
            "start_date": trial.get("startDate", ""),
            "completion_date": trial.get("completionDate", ""),
            "results_available": trial.get("hasResults", False),
        },
    )


def from_guideline(guideline: dict) -> ContentItem:
    """Convertit une recommandation/guideline en ContentItem."""
    return ContentItem(
        content_type=ContentType.GUIDELINE,
        uid=guideline.get("pmid", guideline.get("uid", "")),
        title=guideline.get("title", ""),
        url=guideline.get("url", ""),
        abstract=guideline.get("abstract", ""),
        source_name=guideline.get("organization", guideline.get("journal", "")),
        pub_date=guideline.get("pub_date", ""),
        authors=guideline.get("authors", []),
        extra_data={
            "doi": guideline.get("doi", ""),
            "organization": guideline.get("organization", ""),
            "guideline_type": guideline.get("guideline_type", ""),  # consensus, systematic review, etc.
            "previous_version": guideline.get("previous_version", ""),
            "key_changes": guideline.get("key_changes", []),
        },
    )


# ── Structures de script adaptées par type ────────────────────────────────────

SCRIPT_STRUCTURES = {
    ContentType.RESEARCH_ARTICLE: [
        ("HOOK",       17, "Accroche choc — stat ou question provocante"),
        ("PAPER",      18, "Présentation de la publication"),
        ("BACKGROUND", 40, "Contexte et enjeux pour les patientes"),
        ("METHODS",    35, "Design de l'étude en langage simple"),
        ("RESULTS",    70, "Résultats clés avec données chiffrées"),
        ("CRITICAL",   45, "Revue critique : limites, biais, nuances"),
        ("TAKE_HOME",  25, "Message patient + message scientifique"),
        ("OUTRO",      10, "Call to action"),
    ],
    ContentType.GUIDELINE: [
        ("HOOK",       17, "Pourquoi ces recommandations changent la donne"),
        ("CONTEXT",    25, "Quel organisme, quelle autorité, quelle portée"),
        ("BACKGROUND", 35, "Ce que disaient les anciennes recommandations"),
        ("CHANGES",    80, "Les nouvelles recommandations clé par clé"),
        ("IMPACT",     50, "Ce que ça change concrètement pour les patientes"),
        ("CRITICAL",   40, "Points de débat, ce qui reste incertain"),
        ("TAKE_HOME",  25, "Ce que tu dois retenir / demander à ton médecin"),
        ("OUTRO",      10, "Call to action"),
    ],
    ContentType.CLINICAL_TRIAL: [
        ("HOOK",       17, "L'essai qui pourrait changer le traitement de l'endo"),
        ("TRIAL_INFO", 25, "Phase, sponsor, localisation"),
        ("HYPOTHESIS", 40, "Quelle hypothèse teste-t-on ? Pourquoi ?"),
        ("DESIGN",     45, "Comment l'essai est conçu, critères d'inclusion"),
        ("WHAT_TESTED",50, "L'intervention à l'étude (médicament, chirurgie, autre)"),
        ("TIMELINE",   35, "Dates, nombre de patients, où s'inscrire"),
        ("CRITICAL",   40, "Biais potentiels, conflits d'intérêt, limites"),
        ("TAKE_HOME",  25, "Puis-je participer ? Que peut-on attendre ?"),
        ("OUTRO",      10, "Call to action"),
    ],
}
