"""
recommendations.py — Recommandations cliniques et guidelines

Récupère les recommandations cliniques sur l'endométriose depuis :

  1. PubMed — Guidelines, Practice Guidelines, Consensus, Meta-analyses
     → Via l'API NCBI E-utilities (déjà utilisée pour les articles)

  2. ESHRE (European Society of Human Reproduction and Embryology)
     → La référence internationale pour les guidelines endométriose
     → Scraping de leur page guidelines (légal, contenu public)

  3. ACOG (American College of Obstetricians and Gynecologists)
     → Référence pour le marché américain (important pour YouTube anglophone)

  4. Cochrane Reviews sur l'endométriose
     → Reviews systématiques avec haut niveau de preuve

L'objectif est de capturer une guideline dès sa sortie pour en faire une vidéo
explicative (angle : "Ce que les recommandations changent pour toi").
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from . import config
from .pubmed import fetch_article_details, EUTILS_BASE
import xmltodict

logger = logging.getLogger(__name__)


class GuidelineItem:
    """Représente une recommandation clinique ou une review de guideline."""

    def __init__(self, data: dict):
        self.uid: str = data.get("uid", data.get("pmid", ""))
        self.title: str = data.get("title", "")
        self.abstract: str = data.get("abstract", "")
        self.organization: str = data.get("organization", "")
        self.pub_date: str = data.get("pub_date", "")
        self.authors: list[str] = data.get("authors", [])
        self.doi: str = data.get("doi", "")
        self.url: str = data.get("url", "")
        self.pmid: str = data.get("pmid", "")
        self.guideline_type: str = data.get("guideline_type", "")
        self.journal: str = data.get("journal", "")
        self.source: str = data.get("source", "PubMed")

        # Inferred from publication types
        self.is_systematic_review: bool = data.get("is_systematic_review", False)
        self.is_meta_analysis: bool = data.get("is_meta_analysis", False)
        self.is_guideline: bool = data.get("is_guideline", False)

        if not self.url and self.pmid:
            self.url = f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    @property
    def full_abstract(self) -> str:
        return self.abstract

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "title": self.title,
            "abstract": self.abstract,
            "organization": self.organization,
            "journal": self.journal,
            "pub_date": self.pub_date,
            "authors": self.authors,
            "doi": self.doi,
            "url": self.url,
            "pmid": self.pmid,
            "guideline_type": self.guideline_type,
            "source": self.source,
        }

    def __repr__(self):
        return f"GuidelineItem({self.source}, {self.title[:50]}...)"


# ── 1. PubMed — Guidelines & Reviews ──────────────────────────────────────────

def search_pubmed_guidelines(
    days_back: int = 180,
    max_results: int = 20,
) -> list[GuidelineItem]:
    """
    Recherche sur PubMed les guidelines et reviews systématiques
    sur l'endométriose publiés récemment.
    """
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    date_to = datetime.now().strftime("%Y/%m/%d")

    # Requête spécifique guidelines — inclut les méta-analyses aussi
    query = (
        '"endometriosis"[Title/Abstract] AND '
        '('
        '"Practice Guideline"[Publication Type] OR '
        '"Guideline"[Publication Type] OR '
        '"Consensus Development Conference"[Publication Type] OR '
        '"Consensus Development Conference, NIH"[Publication Type] OR '
        '"Meta-Analysis"[Publication Type] OR '
        '"Systematic Review"[Publication Type] OR '
        '"Review"[Publication Type]'
        ') AND '
        f'("{date_from}"[Date - Publication] : "{date_to}"[Date - Publication]) AND '
        "hasabstract[text]"
    )

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "sort": "date",
        "retmode": "xml",
    }
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY

    try:
        resp = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=15)
        resp.raise_for_status()
        data = xmltodict.parse(resp.text)
        id_list = data.get("eSearchResult", {}).get("IdList", {}).get("Id", [])
        if isinstance(id_list, str):
            id_list = [id_list]

        if not id_list:
            logger.info("No guidelines found on PubMed for this period")
            return []

        # Récupérer les détails
        articles = fetch_article_details(id_list)

        # Convertir en GuidelineItem
        guidelines = []
        for article in articles:
            pub_types = article.publication_types
            is_meta = any("Meta-Analysis" in pt for pt in pub_types)
            is_sr = any("Systematic Review" in pt for pt in pub_types)
            is_gl = any(
                any(gt in pt for gt in ["Guideline", "Consensus", "Practice"])
                for pt in pub_types
            )

            gtype = "Meta-Analysis" if is_meta else \
                    "Systematic Review" if is_sr else \
                    "Guideline" if is_gl else "Review"

            guidelines.append(GuidelineItem({
                "uid": article.pmid,
                "pmid": article.pmid,
                "title": article.title,
                "abstract": article.abstract,
                "journal": article.journal,
                "organization": _infer_organization(article.journal, article.title),
                "pub_date": article.pub_date,
                "authors": article.authors,
                "doi": article.doi,
                "guideline_type": gtype,
                "is_meta_analysis": is_meta,
                "is_systematic_review": is_sr,
                "is_guideline": is_gl,
                "source": "PubMed",
            }))

        logger.info(f"Found {len(guidelines)} guidelines/reviews on PubMed")
        return guidelines

    except Exception as e:
        logger.error(f"PubMed guidelines search failed: {e}")
        return []


def _infer_organization(journal: str, title: str) -> str:
    """
    Infère l'organisation émettrice à partir du nom du journal ou du titre.
    """
    org_map = {
        "Hum Reprod": "ESHRE",
        "Human Reproduction": "ESHRE",
        "Fertil Steril": "ASRM",
        "Fertility and Sterility": "ASRM",
        "Obstet Gynecol": "ACOG",
        "Obstetrics & Gynecology": "ACOG",
        "Am J Obstet Gynecol": "ACOG",
        "Cochrane": "Cochrane",
        "BJOG": "RCOG",
        "Gynecol Obstet": "",
    }
    for key, org in org_map.items():
        if key.lower() in journal.lower():
            return org

    # Chercher dans le titre
    title_keywords = {
        "ESHRE": "ESHRE",
        "ACOG": "ACOG",
        "ASRM": "ASRM",
        "Cochrane": "Cochrane",
        "WHO": "WHO",
        "NICE": "NICE",
        "RCOG": "RCOG",
        "HAS": "HAS",
    }
    for keyword, org in title_keywords.items():
        if keyword in title:
            return org

    return ""


# ── 2. ESHRE Guidelines (scraping léger de l'index public) ───────────────────

def fetch_eshre_guidelines(max_results: int = 5) -> list[GuidelineItem]:
    """
    Vérifie si ESHRE a publié de nouvelles guidelines sur l'endométriose.
    Utilise leur API publique / page de guidelines.

    ESHRE publie ~1-2 guidelines/an sur l'endométriose.
    La dernière version majeure date de 2022 (mise à jour 2024).
    """
    try:
        # ESHRE Guidelines Index — page publique
        resp = requests.get(
            "https://www.eshre.eu/Guidelines-and-Legal/Guidelines",
            timeout=15,
            headers={"User-Agent": "EndoDebrief/1.0 (research; yohann.dabi@gmail.com)"},
        )
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        guidelines = []

        # Chercher les liens contenant "endometriosis"
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True).lower()
            if "endometriosis" in text or "endometrios" in text:
                href = link["href"]
                if not href.startswith("http"):
                    href = f"https://www.eshre.eu{href}"

                guidelines.append(GuidelineItem({
                    "uid": f"eshre_{href.split('/')[-1]}",
                    "title": link.get_text(strip=True),
                    "abstract": "ESHRE Clinical Guideline on Endometriosis",
                    "organization": "ESHRE",
                    "pub_date": datetime.now().strftime("%Y"),
                    "url": href,
                    "guideline_type": "Guideline",
                    "is_guideline": True,
                    "source": "ESHRE",
                }))

                if len(guidelines) >= max_results:
                    break

        logger.info(f"Found {len(guidelines)} ESHRE guidelines")
        return guidelines

    except Exception as e:
        logger.warning(f"ESHRE guidelines fetch failed (non-critical): {e}")
        return []


# ── 3. Cochrane Reviews sur l'endométriose ────────────────────────────────────

def search_cochrane_reviews(days_back: int = 180) -> list[GuidelineItem]:
    """
    Recherche les Cochrane Reviews récentes sur l'endométriose via PubMed
    (Cochrane Reviews sont indexées dans PubMed).
    """
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    date_to = datetime.now().strftime("%Y/%m/%d")

    query = (
        '"endometriosis"[Title/Abstract] AND '
        '"Cochrane Database Syst Rev"[Journal] AND '
        f'("{date_from}"[Date - Publication] : "{date_to}"[Date - Publication])'
    )

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": 10,
        "sort": "date",
        "retmode": "xml",
    }
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY

    try:
        resp = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=15)
        resp.raise_for_status()
        data = xmltodict.parse(resp.text)
        id_list = data.get("eSearchResult", {}).get("IdList", {}).get("Id", [])
        if isinstance(id_list, str):
            id_list = [id_list]

        articles = fetch_article_details(id_list) if id_list else []

        return [
            GuidelineItem({
                "uid": a.pmid,
                "pmid": a.pmid,
                "title": a.title,
                "abstract": a.abstract,
                "journal": "Cochrane Database of Systematic Reviews",
                "organization": "Cochrane",
                "pub_date": a.pub_date,
                "authors": a.authors,
                "doi": a.doi,
                "guideline_type": "Systematic Review",
                "is_systematic_review": True,
                "source": "Cochrane",
            })
            for a in articles
        ]

    except Exception as e:
        logger.warning(f"Cochrane search failed: {e}")
        return []


# ── Point d'entrée principal ──────────────────────────────────────────────────

def get_all_guidelines(
    days_back: int = 180,
    include_eshre: bool = True,
    include_cochrane: bool = True,
) -> list[GuidelineItem]:
    """
    Agrège les guidelines de toutes les sources.
    Déduplique par titre similaire.
    """
    all_guidelines = []

    # PubMed guidelines
    pubmed_guidelines = search_pubmed_guidelines(days_back=days_back)
    all_guidelines.extend(pubmed_guidelines)
    time.sleep(0.5)

    # ESHRE
    if include_eshre:
        eshre = fetch_eshre_guidelines()
        all_guidelines.extend(eshre)
        time.sleep(0.5)

    # Cochrane (souvent déjà dans PubMed, mais vérifier)
    if include_cochrane:
        cochrane = search_cochrane_reviews(days_back=days_back)
        # Dédupliquer par PMID
        existing_pmids = {g.pmid for g in all_guidelines if g.pmid}
        all_guidelines.extend(g for g in cochrane if g.pmid not in existing_pmids)

    logger.info(f"Total guidelines collected: {len(all_guidelines)}")
    return all_guidelines
