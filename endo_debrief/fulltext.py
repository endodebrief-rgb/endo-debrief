"""
fulltext.py — Récupération du texte intégral des articles

Stratégie en cascade (du plus simple au plus complexe) :

1. PubMed Central (PMC) — gratuit, texte complet structuré en XML
   → Pour tous les articles indexés dans PMC (env. 50% des articles endo)

2. Unpaywall API — trouve les versions légales en Open Access
   → Scans DOI dans les dépôts institutionnels, preprints, etc.

3. Europe PMC — archive européenne complémentaire à PMC
   → Couvre des articles non disponibles sur PMC US

4. PDF uploadé manuellement par le Dr Dabi
   → Pour les articles payants : l'utilisateur dépose le PDF dans
     `pdf_uploads/{PMID}.pdf` et le pipeline l'analyse automatiquement

Si aucun texte intégral n'est trouvé → fallback sur l'abstract (avec mention dans la critique).

IMPORTANT légal : ce module ne contourne pas les paywalls. Il n'accède qu'aux
versions légalement disponibles en Open Access.
"""

import io
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import requests

from . import config
from .pubmed import PubMedArticle

logger = logging.getLogger(__name__)

UNPAYWALL_EMAIL = "yohann.dabi@gmail.com"   # Requis par l'API Unpaywall (gratuite)
PMC_API_BASE    = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PDF_UPLOADS_DIR = config.BASE_DIR / "pdf_uploads"  # Dossier où le Dr Dabi dépose ses PDFs


class FullTextSource(Enum):
    PMC          = "PubMed Central"
    UNPAYWALL    = "Unpaywall (Open Access)"
    EUROPE_PMC   = "Europe PMC"
    PDF_UPLOAD   = "PDF uploadé manuellement"
    ABSTRACT_ONLY = "Abstract uniquement (article payant)"


@dataclass
class FullTextResult:
    """Résultat de la tentative de récupération du texte intégral."""
    pmid: str
    has_full_text: bool
    source: FullTextSource
    text: str = ""                      # Texte intégral (nettoyé)
    sections: dict = field(default_factory=dict)   # {Introduction, Methods, Results, Discussion, ...}
    pdf_path: Optional[str] = None      # Chemin local du PDF (si uploadé)
    oa_url: Optional[str] = None        # URL Open Access (si disponible)
    is_paywalled: bool = False          # Vrai si aucun accès gratuit trouvé
    pmc_id: Optional[str] = None

    @property
    def best_text(self) -> str:
        """Retourne le meilleur texte disponible (intégral ou abstract)."""
        if self.text:
            return self.text
        return ""

    @property
    def methods_text(self) -> str:
        """Texte de la section Methods (critique pour l'analyse méthodologique)."""
        return self.sections.get("Methods", self.sections.get("methods", ""))

    @property
    def results_text(self) -> str:
        return self.sections.get("Results", self.sections.get("results", ""))

    @property
    def discussion_text(self) -> str:
        return self.sections.get("Discussion", self.sections.get("discussion", ""))


# ── 1. PubMed Central ─────────────────────────────────────────────────────────

def _get_pmc_id(pmid: str) -> Optional[str]:
    """Cherche l'ID PMC correspondant à un PMID."""
    params = {
        "dbfrom": "pubmed",
        "db": "pmc",
        "id": pmid,
        "retmode": "json",
    }
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY

    try:
        resp = requests.get(f"{PMC_API_BASE}/elink.fcgi", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        linksets = data.get("linksets", [])
        if linksets:
            links = linksets[0].get("linksetdbs", [])
            for link in links:
                if link.get("dbto") == "pmc":
                    ids = link.get("links", [])
                    if ids:
                        return str(ids[0])
    except Exception as e:
        logger.debug(f"PMC ID lookup failed for {pmid}: {e}")
    return None


def _fetch_pmc_fulltext(pmc_id: str) -> Optional[dict]:
    """
    Récupère le texte intégral depuis PMC en XML et l'analyse.
    Retourne un dict {section_name: text} ou None si échec.
    """
    params = {
        "db": "pmc",
        "id": pmc_id,
        "rettype": "full",
        "retmode": "xml",
    }
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY

    try:
        resp = requests.get(f"{PMC_API_BASE}/efetch.fcgi", params=params, timeout=30)
        resp.raise_for_status()
        return _parse_pmc_xml(resp.text)
    except Exception as e:
        logger.debug(f"PMC fetch failed for PMC{pmc_id}: {e}")
        return None


def _parse_pmc_xml(xml_text: str) -> dict:
    """
    Parse le XML PMC et extrait les sections principales du texte.
    Retourne {section_title: text_content}.
    """
    import xml.etree.ElementTree as ET

    sections = {}

    try:
        root = ET.fromstring(xml_text)

        # Chercher les sections du body
        body = root.find(".//body")
        if body is None:
            return sections

        for sec in body.findall(".//sec"):
            # Titre de la section
            title_elem = sec.find("title")
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled"

            # Texte des paragraphes
            paragraphs = []
            for p in sec.findall(".//p"):
                # Concaténer tout le texte (y compris dans les balises enfants)
                text = "".join(p.itertext()).strip()
                if text:
                    paragraphs.append(text)

            if paragraphs:
                sections[title] = "\n\n".join(paragraphs)

    except ET.ParseError as e:
        logger.warning(f"XML parse error: {e}")

    return sections


# ── 2. Unpaywall ──────────────────────────────────────────────────────────────

def _check_unpaywall(doi: str) -> Optional[str]:
    """
    Cherche une version Open Access légale via Unpaywall.
    Retourne l'URL du PDF ou du HTML OA, ou None.
    API gratuite, requiert un email de contact.
    """
    if not doi:
        return None

    try:
        url = f"https://api.unpaywall.org/v2/{doi}"
        resp = requests.get(url, params={"email": UNPAYWALL_EMAIL}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("is_oa"):
            return None

        # Chercher le meilleur lien OA (préférer le PDF publisher > author manuscript)
        best = data.get("best_oa_location", {})
        if best:
            return best.get("url_for_pdf") or best.get("url_for_landing_page")

    except Exception as e:
        logger.debug(f"Unpaywall check failed for DOI {doi}: {e}")

    return None


def _download_oa_pdf(url: str, output_path: Path) -> bool:
    """Télécharge un PDF Open Access depuis une URL."""
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "EndoDebrief/1.0"})
        resp.raise_for_status()

        if "application/pdf" in resp.headers.get("content-type", "").lower():
            output_path.write_bytes(resp.content)
            return True

    except Exception as e:
        logger.debug(f"PDF download failed from {url}: {e}")

    return False


def _extract_text_from_pdf(pdf_path: Path) -> str:
    """Extrait le texte d'un PDF en utilisant pdfminer ou pypdf."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        text = "\n\n".join(
            page.extract_text() for page in reader.pages if page.extract_text()
        )
        return text.strip()
    except ImportError:
        pass

    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(pdf_path)).strip()
    except ImportError:
        logger.warning("No PDF extraction library available (install pypdf or pdfminer.six)")

    return ""


# ── 3. Europe PMC ─────────────────────────────────────────────────────────────

def _fetch_europe_pmc(pmid: str) -> Optional[str]:
    """Tente de récupérer le texte via Europe PMC."""
    try:
        resp = requests.get(
            f"{EUROPE_PMC_BASE}/search",
            params={
                "query": f"EXT_ID:{pmid} AND SRC:MED",
                "resultType": "core",
                "format": "json",
                "pageSize": 1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("resultList", {}).get("result", [])

        if not results:
            return None

        article = results[0]
        pmc_id = article.get("pmcid", "")

        if pmc_id and article.get("isOpenAccess") == "Y":
            # Récupérer le texte intégral via Europe PMC
            full_resp = requests.get(
                f"{EUROPE_PMC_BASE}/{pmc_id}/fullTextXML",
                timeout=30,
            )
            if full_resp.status_code == 200:
                sections = _parse_pmc_xml(full_resp.text)
                if sections:
                    return "\n\n".join(
                        f"## {title}\n{text}"
                        for title, text in sections.items()
                    )
    except Exception as e:
        logger.debug(f"Europe PMC failed for {pmid}: {e}")

    return None


# ── 4. PDF uploadé manuellement ────────────────────────────────────────────────

def _check_manual_pdf_upload(pmid: str) -> Optional[Path]:
    """
    Vérifie si le Dr Dabi a uploadé un PDF pour cet article.
    Cherche dans le dossier pdf_uploads/{PMID}.pdf
    """
    PDF_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = PDF_UPLOADS_DIR / f"{pmid}.pdf"
    if pdf_path.exists():
        logger.info(f"Found manually uploaded PDF for {pmid}: {pdf_path}")
        return pdf_path
    return None


# ── Point d'entrée principal ──────────────────────────────────────────────────

def get_full_text(article: PubMedArticle, cache_dir: Optional[Path] = None) -> FullTextResult:
    """
    Tente de récupérer le texte intégral d'un article par tous les moyens disponibles.
    Retourne un FullTextResult avec le meilleur texte disponible.

    Ordre de priorité :
    1. PDF uploadé manuellement (plus haute qualité)
    2. PubMed Central (texte structuré XML)
    3. Europe PMC
    4. Unpaywall (PDF OA téléchargé + extrait)
    5. Abstract uniquement (fallback)
    """
    pmid = article.pmid
    cache_dir = Path(cache_dir) if cache_dir else config.OUTPUT_DIR / "fulltext_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Fetching full text for PMID {pmid}...")

    # ── 1. PDF uploadé manuellement ───────────────────────────────────────────
    manual_pdf = _check_manual_pdf_upload(pmid)
    if manual_pdf:
        text = _extract_text_from_pdf(manual_pdf)
        if text:
            logger.info(f"✓ [{pmid}] Using manually uploaded PDF")
            return FullTextResult(
                pmid=pmid,
                has_full_text=True,
                source=FullTextSource.PDF_UPLOAD,
                text=text,
                pdf_path=str(manual_pdf),
                is_paywalled=False,
            )

    # ── 2. PubMed Central ─────────────────────────────────────────────────────
    pmc_id = _get_pmc_id(pmid)
    time.sleep(0.4)  # Rate limiting NCBI

    if pmc_id:
        sections = _fetch_pmc_fulltext(pmc_id)
        if sections:
            full_text = "\n\n".join(
                f"## {title}\n{text}" for title, text in sections.items()
            )
            logger.info(f"✓ [{pmid}] Full text from PMC (PMC{pmc_id})")
            return FullTextResult(
                pmid=pmid,
                has_full_text=True,
                source=FullTextSource.PMC,
                text=full_text,
                sections=sections,
                pmc_id=pmc_id,
                oa_url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/",
                is_paywalled=False,
            )

    # ── 3. Europe PMC ─────────────────────────────────────────────────────────
    europe_text = _fetch_europe_pmc(pmid)
    if europe_text:
        logger.info(f"✓ [{pmid}] Full text from Europe PMC")
        return FullTextResult(
            pmid=pmid,
            has_full_text=True,
            source=FullTextSource.EUROPE_PMC,
            text=europe_text,
            is_paywalled=False,
        )

    # ── 4. Unpaywall ──────────────────────────────────────────────────────────
    if article.doi:
        oa_url = _check_unpaywall(article.doi)
        if oa_url and oa_url.endswith(".pdf"):
            pdf_cache = cache_dir / f"{pmid}_unpaywall.pdf"
            success = _download_oa_pdf(oa_url, pdf_cache)
            if success:
                text = _extract_text_from_pdf(pdf_cache)
                if text:
                    logger.info(f"✓ [{pmid}] Full text via Unpaywall: {oa_url}")
                    return FullTextResult(
                        pmid=pmid,
                        has_full_text=True,
                        source=FullTextSource.UNPAYWALL,
                        text=text,
                        pdf_path=str(pdf_cache),
                        oa_url=oa_url,
                        is_paywalled=False,
                    )

    # ── 5. Fallback : abstract uniquement ─────────────────────────────────────
    logger.warning(f"⚠ [{pmid}] No full text available — paywalled article")
    return FullTextResult(
        pmid=pmid,
        has_full_text=False,
        source=FullTextSource.ABSTRACT_ONLY,
        text="",
        is_paywalled=True,
        oa_url=f"https://doi.org/{article.doi}" if article.doi else None,
    )


def fetch_full_texts_for_articles(
    articles: list[PubMedArticle],
    cache_dir: Optional[Path] = None,
) -> dict[str, FullTextResult]:
    """
    Récupère les textes intégraux pour une liste d'articles.
    Retourne un dict {pmid: FullTextResult}.
    """
    results = {}
    paywalled = []

    for article in articles:
        result = get_full_text(article, cache_dir)
        results[article.pmid] = result

        if result.is_paywalled:
            paywalled.append(article)

        time.sleep(1.0)  # Pause entre les requêtes

    # Résumé
    oa_count = sum(1 for r in results.values() if r.has_full_text)
    logger.info(
        f"Full text retrieval: {oa_count}/{len(articles)} articles "
        f"({len(paywalled)} paywalled)"
    )

    if paywalled:
        logger.info("Paywalled articles (need manual PDF upload):")
        for a in paywalled:
            logger.info(
                f"  - PMID {a.pmid}: {a.title[:60]}... "
                f"(DOI: {a.doi}) → Save as pdf_uploads/{a.pmid}.pdf"
            )

    return results


def get_paywalled_articles_info(
    full_text_results: dict[str, FullTextResult],
    articles: list[PubMedArticle],
) -> list[dict]:
    """
    Retourne les infos sur les articles payants pour l'email de notification.
    """
    article_map = {a.pmid: a for a in articles}
    paywalled = []

    for pmid, result in full_text_results.items():
        if result.is_paywalled:
            article = article_map.get(pmid)
            if article:
                paywalled.append({
                    "pmid": pmid,
                    "title": article.title,
                    "journal": article.journal,
                    "doi": article.doi,
                    "doi_url": f"https://doi.org/{article.doi}" if article.doi else "",
                    "pubmed_url": article.url,
                    "upload_filename": f"{pmid}.pdf",
                    "upload_instruction": (
                        f"Si tu as accès à cet article (via ton institution, "
                        f"ResearchGate, ou l'auteur), dépose le PDF dans le dossier "
                        f"pdf_uploads/ sous le nom '{pmid}.pdf', puis relance la génération."
                    ),
                })

    return paywalled
