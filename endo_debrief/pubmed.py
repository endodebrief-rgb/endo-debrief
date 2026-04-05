"""
pubmed.py — Recherche et récupération d'articles PubMed
Utilise l'API NCBI E-utilities (gratuite).

Workflow :
1. esearch → récupère les PMIDs des articles récents
2. efetch → récupère les métadonnées complètes (titre, abstract, journal, auteurs...)
"""

import time
import logging
import requests
import xmltodict
from datetime import datetime, timedelta
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedArticle:
    """Représente un article PubMed avec toutes ses métadonnées."""

    def __init__(self, data: dict):
        self.pmid: str = data.get("pmid", "")
        self.title: str = data.get("title", "")
        self.abstract: str = data.get("abstract", "")
        self.authors: list[str] = data.get("authors", [])
        self.journal: str = data.get("journal", "")
        self.pub_date: str = data.get("pub_date", "")
        self.doi: str = data.get("doi", "")
        self.keywords: list[str] = data.get("keywords", [])
        self.publication_types: list[str] = data.get("publication_types", [])
        self.url: str = f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    def to_dict(self) -> dict:
        return {
            "pmid": self.pmid,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "journal": self.journal,
            "pub_date": self.pub_date,
            "doi": self.doi,
            "keywords": self.keywords,
            "publication_types": self.publication_types,
            "url": self.url,
        }

    def __repr__(self):
        return f"PubMedArticle(pmid={self.pmid}, title={self.title[:60]}...)"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get(url: str, params: dict) -> dict:
    """Requête GET avec retry automatique."""
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    params["retmode"] = "xml"
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return xmltodict.parse(response.text)


def search_recent_articles(
    days_back: int = config.PUBMED_DAYS_BACK,
    max_results: int = config.PUBMED_MAX_RESULTS,
    extra_terms: Optional[list[str]] = None,
) -> list[str]:
    """
    Recherche les articles PubMed récents sur l'endométriose.
    Retourne une liste de PMIDs.
    """
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    date_to = datetime.now().strftime("%Y/%m/%d")

    # Construire la requête de recherche
    base_terms = config.PUBMED_SEARCH_TERMS.copy()
    if extra_terms:
        base_terms.extend(extra_terms)

    query = " OR ".join(f'"{term}"[Title/Abstract]' for term in base_terms)
    query += f' AND ("{date_from}"[Date - Publication] : "{date_to}"[Date - Publication])'
    query += " AND hasabstract[text]"  # Uniquement articles avec abstract

    logger.info(f"PubMed query: {query}")

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "sort": "date",
        "usehistory": "y",
    }

    result = _get(f"{EUTILS_BASE}/esearch.fcgi", params)
    id_list = result.get("eSearchResult", {}).get("IdList", {}).get("Id", [])

    if isinstance(id_list, str):
        id_list = [id_list]

    logger.info(f"Found {len(id_list)} articles on PubMed for the last {days_back} days")
    return id_list


def fetch_article_details(pmids: list[str]) -> list[PubMedArticle]:
    """
    Récupère les détails complets pour une liste de PMIDs.
    Traite par batch de 20 pour respecter les limites d'API.
    """
    articles = []
    batch_size = 20

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i : i + batch_size]
        logger.info(f"Fetching batch {i//batch_size + 1} ({len(batch)} articles)...")

        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "abstract",
        }

        try:
            result = _get(f"{EUTILS_BASE}/efetch.fcgi", params)
            articles_data = result.get("PubmedArticleSet", {}).get("PubmedArticle", [])

            if isinstance(articles_data, dict):
                articles_data = [articles_data]

            for article_xml in articles_data:
                parsed = _parse_article(article_xml)
                if parsed and parsed.abstract:  # Ignorer les articles sans abstract
                    articles.append(parsed)

        except Exception as e:
            logger.error(f"Error fetching batch starting at {i}: {e}")

        # Respecter le rate limit NCBI (3 req/s sans clé, 10 req/s avec clé)
        time.sleep(0.4 if config.NCBI_API_KEY else 1.0)

    logger.info(f"Successfully fetched {len(articles)} articles with abstracts")
    return articles


def _parse_article(article_xml: dict) -> Optional[PubMedArticle]:
    """Parse le XML d'un article PubMed en objet PubMedArticle."""
    try:
        medline = article_xml.get("MedlineCitation", {})
        article = medline.get("Article", {})
        pub_data = article_xml.get("PubmedData", {})

        # PMID
        pmid = str(medline.get("PMID", {}).get("#text", medline.get("PMID", "")))

        # Titre
        title_data = article.get("ArticleTitle", "")
        title = title_data if isinstance(title_data, str) else str(title_data)
        title = title.strip()

        # Abstract
        abstract_raw = article.get("Abstract", {}).get("AbstractText", "")
        if isinstance(abstract_raw, list):
            # Abstract structuré (Background, Methods, Results, Conclusions)
            parts = []
            for part in abstract_raw:
                if isinstance(part, dict):
                    label = part.get("@Label", "")
                    text = part.get("#text", "")
                    if label and text:
                        parts.append(f"{label}: {text}")
                    elif text:
                        parts.append(text)
                elif isinstance(part, str):
                    parts.append(part)
            abstract = " ".join(parts)
        elif isinstance(abstract_raw, dict):
            abstract = abstract_raw.get("#text", "")
        else:
            abstract = str(abstract_raw)

        # Auteurs
        authors_raw = article.get("AuthorList", {}).get("Author", [])
        if isinstance(authors_raw, dict):
            authors_raw = [authors_raw]
        authors = []
        for author in authors_raw[:5]:  # Limite à 5 auteurs
            last = author.get("LastName", "")
            initials = author.get("Initials", "")
            if last:
                authors.append(f"{last} {initials}".strip())

        # Journal
        journal_info = article.get("Journal", {})
        journal = journal_info.get("Title", "")
        if not journal:
            journal = journal_info.get("ISOAbbreviation", "")

        # Date de publication
        pub_date_raw = journal_info.get("JournalIssue", {}).get("PubDate", {})
        year = pub_date_raw.get("Year", "")
        month = pub_date_raw.get("Month", "")
        pub_date = f"{year} {month}".strip() if year else ""

        # DOI
        doi = ""
        article_ids = pub_data.get("ArticleIdList", {}).get("ArticleId", [])
        if isinstance(article_ids, dict):
            article_ids = [article_ids]
        for aid in article_ids:
            if isinstance(aid, dict) and aid.get("@IdType") == "doi":
                doi = aid.get("#text", "")
                break

        # Keywords
        keyword_list = medline.get("KeywordList", {}).get("Keyword", [])
        if isinstance(keyword_list, str):
            keyword_list = [keyword_list]
        keywords = [
            kw.get("#text", kw) if isinstance(kw, dict) else str(kw)
            for kw in keyword_list
        ][:10]

        # Types de publication
        pub_types_raw = article.get("PublicationTypeList", {}).get("PublicationType", [])
        if isinstance(pub_types_raw, dict):
            pub_types_raw = [pub_types_raw]
        pub_types = [
            pt.get("#text", pt) if isinstance(pt, dict) else str(pt)
            for pt in pub_types_raw
        ]

        return PubMedArticle({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "pub_date": pub_date,
            "doi": doi,
            "keywords": keywords,
            "publication_types": pub_types,
        })

    except Exception as e:
        logger.warning(f"Failed to parse article: {e}")
        return None


def get_recent_endometriosis_articles(
    days_back: int = config.PUBMED_DAYS_BACK,
    max_results: int = config.PUBMED_MAX_RESULTS,
) -> list[PubMedArticle]:
    """
    Point d'entrée principal : récupère et parse les articles récents.
    Fallback automatique si pas assez d'articles trouvés.
    """
    logger.info(f"Searching PubMed for endometriosis articles (last {days_back} days)...")
    pmids = search_recent_articles(days_back=days_back, max_results=max_results)

    if not pmids:
        logger.warning("No articles found — extending search window to 30 days")
        pmids = search_recent_articles(days_back=30, max_results=max_results)

    articles = fetch_article_details(pmids)
    return articles


def search_guidelines_pubmed(
    days_back: int = 180,
    max_results: int = 20,
) -> list[PubMedArticle]:
    """
    Recherche spécifique aux recommandations et guidelines cliniques
    sur l'endométriose publiées récemment sur PubMed.

    Filtre sur les types de publication : Practice Guideline, Guideline,
    Consensus Development Conference, Systematic Review.
    """
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    date_to = datetime.now().strftime("%Y/%m/%d")

    query = (
        '"endometriosis"[Title/Abstract] AND '
        '("Practice Guideline"[Publication Type] OR '
        '"Guideline"[Publication Type] OR '
        '"Consensus Development Conference"[Publication Type] OR '
        '"Consensus Development Conference, NIH"[Publication Type] OR '
        '"Meta-Analysis"[Publication Type]) AND '
        f'("{date_from}"[Date - Publication] : "{date_to}"[Date - Publication]) AND '
        "hasabstract[text]"
    )

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "sort": "date",
    }
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    params["retmode"] = "xml"

    try:
        import xmltodict
        resp = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=15)
        resp.raise_for_status()
        data = xmltodict.parse(resp.text)
        id_list = data.get("eSearchResult", {}).get("IdList", {}).get("Id", [])
        if isinstance(id_list, str):
            id_list = [id_list]
        if id_list:
            return fetch_article_details(id_list)
    except Exception as e:
        logger.warning(f"Guideline search failed: {e}")

    return []


def get_articles_with_fulltext_priority(
    days_back_initial: int = config.PUBMED_DAYS_BACK,
    days_back_extended: int = 60,
    min_fulltext_target: int = 2,
    max_results: int = config.PUBMED_MAX_RESULTS,
) -> tuple[list[PubMedArticle], bool]:
    """
    Récupère les articles récents en priorisant ceux avec texte intégral disponible.

    Stratégie :
    1. Cherche sur la période initiale (14 jours par défaut)
    2. Vérifie rapidement la disponibilité PMC via NCBI elink
    3. Si moins de min_fulltext_target articles avec PMC ID,
       étend la recherche à days_back_extended (60 jours)
    4. Fusionne, déduplique, retourne la liste enrichie

    Retourne (articles, extended) où extended=True si la période a été élargie.
    """
    logger.info(
        f"Fetching articles with full-text priority "
        f"(initial: {days_back_initial}d, extended: {days_back_extended}d if needed)..."
    )

    # Période initiale
    pmids_initial = search_recent_articles(
        days_back=days_back_initial, max_results=max_results
    )
    articles_initial = fetch_article_details(pmids_initial) if pmids_initial else []

    # Vérification rapide de la disponibilité PMC (via elink batch)
    pmc_count = _count_pmc_available(pmids_initial) if pmids_initial else 0
    logger.info(
        f"Initial search: {len(articles_initial)} articles, "
        f"~{pmc_count} with PMC full text"
    )

    extended = False
    all_articles = list(articles_initial)

    if pmc_count < min_fulltext_target:
        logger.info(
            f"Only {pmc_count} articles with PMC full text (target: {min_fulltext_target}). "
            f"Extending search to {days_back_extended} days..."
        )
        pmids_extended = search_recent_articles(
            days_back=days_back_extended, max_results=max_results * 2
        )

        # Exclure les PMIDs déjà récupérés
        new_pmids = [p for p in pmids_extended if p not in pmids_initial]
        if new_pmids:
            new_articles = fetch_article_details(new_pmids[:max_results])
            all_articles.extend(new_articles)
            extended = True
            logger.info(
                f"Extended search added {len(new_articles)} articles "
                f"(total: {len(all_articles)})"
            )

    return all_articles, extended


def _count_pmc_available(pmids: list[str]) -> int:
    """
    Compte rapidement combien de PMIDs ont un article dans PMC.
    Utilise elink en batch — plus efficace que des appels individuels.
    """
    if not pmids:
        return 0

    params = {
        "dbfrom": "pubmed",
        "db": "pmc",
        "id": ",".join(pmids[:30]),  # Max 30 pour éviter les requêtes trop lourdes
        "retmode": "json",
    }
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY

    try:
        resp = requests.get(f"{EUTILS_BASE}/elink.fcgi", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        linksets = data.get("linksets", [])
        count = 0
        for ls in linksets:
            for db in ls.get("linksetdbs", []):
                if db.get("dbto") == "pmc":
                    count += len(db.get("links", []))
        return count
    except Exception:
        return 0
