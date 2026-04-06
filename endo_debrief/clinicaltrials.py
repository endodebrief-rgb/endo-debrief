"""
clinicaltrials.py — Intégration ClinicalTrials.gov

Récupère les essais cliniques sur l'endométriose depuis l'API ClinicalTrials.gov v2.
Trois catégories d'intérêt pour Endo Debrief :

  1. ESSAIS EN RECRUTEMENT ACTIF
     → Utiles pour les patientes qui cherchent à participer
     → Angle : "Voici un essai auquel tu peux peut-être participer"

  2. ESSAIS RÉCEMMENT COMPLÉTÉS AVEC RÉSULTATS
     → Résultats d'essais disponibles — souvent avant la publication du papier
     → Angle : "Les résultats sont tombés — voici ce qu'on a appris"

  3. NOUVEAUX ESSAIS ENREGISTRÉS (last 30 days)
     → Signaux sur où va la recherche
     → Angle : "Les chercheurs s'attaquent maintenant à ce problème"

API ClinicalTrials.gov v2 : https://clinicaltrials.gov/data-api/api
Documentation : https://clinicaltrials.gov/data-api/about-api
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CT_API_BASE = "https://clinicaltrials.gov/api/v2"

# Statuts à suivre en priorité
PRIORITY_STATUSES = ["RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED"]
RECRUITING_STATUSES = ["RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"]


class ClinicalTrialItem:
    """Représente un essai clinique avec toutes ses métadonnées."""

    def __init__(self, data: dict):
        proto = data.get("protocolSection", {})
        id_mod = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        desc_mod = proto.get("descriptionModule", {})
        design_mod = proto.get("designModule", {})
        contacts_mod = proto.get("contactsLocationsModule", {})
        outcomes_mod = proto.get("outcomesModule", {})
        eligibility_mod = proto.get("eligibilityModule", {})
        sponsor_mod = proto.get("sponsorCollaboratorsModule", {})

        self.nct_id: str = id_mod.get("nctId", "")
        self.title: str = id_mod.get("briefTitle", "")
        self.official_title: str = id_mod.get("officialTitle", "")
        self.url: str = f"https://clinicaltrials.gov/study/{self.nct_id}"

        self.status: str = status_mod.get("overallStatus", "UNKNOWN")
        self.start_date: str = status_mod.get("startDateStruct", {}).get("date", "")
        self.completion_date: str = status_mod.get("primaryCompletionDateStruct", {}).get("date", "")
        self.last_update: str = status_mod.get("lastUpdateSubmitDate", "")
        self.has_results: bool = data.get("hasResults", False)

        self.brief_summary: str = desc_mod.get("briefSummary", "")
        self.detailed_description: str = desc_mod.get("detailedDescription", "")

        self.phase: str = " / ".join(design_mod.get("phases", []))
        self.enrollment: int = design_mod.get("enrollmentInfo", {}).get("count", 0)
        self.study_type: str = design_mod.get("studyType", "")

        # Interventions
        arms = design_mod.get("armGroups", [])
        interventions = proto.get("armsInterventionsModule", {}).get("interventions", [])
        self.intervention_names: list[str] = [iv.get("name", "") for iv in interventions]
        self.intervention_types: list[str] = list(set(iv.get("type", "") for iv in interventions))

        # Outcomes
        primary_outcomes = outcomes_mod.get("primaryOutcomes", [])
        self.primary_outcome: str = (
            primary_outcomes[0].get("measure", "") if primary_outcomes else ""
        )

        # Éligibilité
        self.eligibility_criteria: str = eligibility_mod.get("eligibilityCriteria", "")
        self.min_age: str = eligibility_mod.get("minimumAge", "")
        self.max_age: str = eligibility_mod.get("maximumAge", "")
        self.sex: str = eligibility_mod.get("sex", "")

        # Sponsor
        self.lead_sponsor: str = sponsor_mod.get("leadSponsor", {}).get("name", "")
        self.sponsor_class: str = sponsor_mod.get("leadSponsor", {}).get("class", "")

        # Localisations
        locations_raw = contacts_mod.get("locations", [])
        self.locations: list[str] = list(set(
            f"{loc.get('city', '')}, {loc.get('country', '')}"
            for loc in locations_raw[:5]
            if loc.get("country")
        ))

    @property
    def abstract(self) -> str:
        """Résumé utilisable comme source pour le script."""
        parts = [self.brief_summary]
        if self.primary_outcome:
            parts.append(f"Primary outcome: {self.primary_outcome}")
        if self.phase:
            parts.append(f"Phase: {self.phase}")
        if self.enrollment:
            parts.append(f"Target enrollment: {self.enrollment} participants")
        if self.eligibility_criteria:
            # Nettoyer les critères d'inclusion
            parts.append(f"Eligibility: {self.eligibility_criteria[:500]}")
        return "\n\n".join(parts)

    @property
    def video_interest_category(self) -> str:
        """Catégorie d'intérêt pour la sélection des vidéos."""
        if self.has_results:
            return "completed_with_results"
        if self.status in RECRUITING_STATUSES:
            return "recruiting"
        return "new_trial"

    def to_dict(self) -> dict:
        return {
            "nct_id": self.nct_id,
            "title": self.title,
            "url": self.url,
            "status": self.status,
            "phase": self.phase,
            "enrollment": self.enrollment,
            "lead_sponsor": self.lead_sponsor,
            "primary_outcome": self.primary_outcome,
            "start_date": self.start_date,
            "completion_date": self.completion_date,
            "has_results": self.has_results,
            "locations": self.locations,
            "video_interest_category": self.video_interest_category,
        }

    def __repr__(self):
        return f"ClinicalTrialItem({self.nct_id}, {self.status}, {self.title[:50]}...)"


def _ct_get(endpoint: str, params: dict, timeout: int = 20) -> dict:
    """Requête GET vers l'API ClinicalTrials.gov v2."""
    url = f"{CT_API_BASE}/{endpoint}"
    params.setdefault("format", "json")

    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def search_recruiting_trials(
    days_back: int = 90,
    max_results: int = 10,
) -> list[ClinicalTrialItem]:
    """
    Recherche les essais en recrutement actif sur l'endométriose.
    Particulièrement utile pour les patientes cherchant à participer.
    """
    logger.info(f"Searching ClinicalTrials.gov for recruiting endo trials...")

    params = {
        "query.cond": "endometriosis",
        "filter.overallStatus": "RECRUITING,ENROLLING_BY_INVITATION,NOT_YET_RECRUITING",
        "fields": (
            "NCTId,BriefTitle,OfficialTitle,OverallStatus,BriefSummary,"
            "DetailedDescription,Phase,EnrollmentCount,StartDate,PrimaryCompletionDate,"
            "LastUpdateSubmitDate,HasResults,LeadSponsorName,LeadSponsorClass,"
            "PrimaryOutcomeMeasure,EligibilityCriteria,MinimumAge,MaximumAge,"
            "Sex,LocationCity,LocationCountry,InterventionName,InterventionType"
        ),
        "pageSize": max_results,
        "sort": "LastUpdateSubmitDate:desc",
    }

    try:
        data = _ct_get("studies", params)
        studies = data.get("studies", [])
        trials = []

        for study in studies:
            try:
                trial = ClinicalTrialItem(study)
                # Filtrer les essais trop anciens
                if _is_recently_active(trial, days_back):
                    trials.append(trial)
            except Exception as e:
                logger.debug(f"Failed to parse trial: {e}")

        logger.info(f"Found {len(trials)} actively recruiting endo trials")
        return trials

    except Exception as e:
        logger.error(f"ClinicalTrials.gov recruiting search failed: {e}")
        return []


def search_completed_trials_with_results(
    days_back: int = 180,
    max_results: int = 10,
) -> list[ClinicalTrialItem]:
    """
    Recherche les essais récemment complétés avec des résultats disponibles.
    Ce sont les plus importants : résultats avant la publication du papier.
    Note : filter.results n'existe pas dans l'API v2 — on filtre en post-processing
    sur le champ hasResults.
    """
    logger.info("Searching for completed endo trials with results...")

    params = {
        "query.cond": "endometriosis",
        "filter.overallStatus": "COMPLETED",
        "fields": (
            "NCTId,BriefTitle,OfficialTitle,OverallStatus,BriefSummary,"
            "Phase,EnrollmentCount,StartDate,PrimaryCompletionDate,"
            "LastUpdateSubmitDate,HasResults,LeadSponsorName,"
            "PrimaryOutcomeMeasure,EligibilityCriteria"
        ),
        "pageSize": max_results * 3,  # On en prend plus pour filtrer ensuite
        "sort": "LastUpdateSubmitDate:desc",
    }

    try:
        data = _ct_get("studies", params)
        studies = data.get("studies", [])
        trials = []

        for study in studies:
            try:
                trial = ClinicalTrialItem(study)
                # Filtrer : uniquement ceux avec résultats ET mis à jour récemment
                if trial.has_results and _updated_recently(trial, days_back):
                    trials.append(trial)
                    if len(trials) >= max_results:
                        break
            except Exception as e:
                logger.debug(f"Failed to parse completed trial: {e}")

        logger.info(f"Found {len(trials)} completed endo trials with results")
        return trials

    except Exception as e:
        logger.error(f"ClinicalTrials.gov completed search failed: {e}")
        return []


def search_new_trials(
    days_back: int = 30,
    max_results: int = 10,
) -> list[ClinicalTrialItem]:
    """
    Recherche les nouveaux essais enregistrés récemment.
    Signal sur les directions de la recherche.
    Note : filter.firstPosted utilise la syntaxe "{date}:MAX" (MAX en majuscules).
    """
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params = {
        "query.cond": "endometriosis",
        "filter.firstPosted": f"{date_from}:MAX",  # MAX en majuscules (syntaxe API v2)
        "fields": (
            "NCTId,BriefTitle,OfficialTitle,OverallStatus,BriefSummary,"
            "Phase,EnrollmentCount,StartDate,PrimaryCompletionDate,"
            "LastUpdateSubmitDate,HasResults,LeadSponsorName,"
            "PrimaryOutcomeMeasure,InterventionName,InterventionType"
        ),
        "pageSize": max_results,
        "sort": "FirstPostDate:desc",
    }

    try:
        data = _ct_get("studies", params)
        studies = data.get("studies", [])
        trials = [ClinicalTrialItem(s) for s in studies]
        logger.info(f"Found {len(trials)} newly registered endo trials")
        return trials
    except Exception as e:
        logger.error(f"ClinicalTrials.gov new trials search failed: {e}")
        return []


def get_trial_details(nct_id: str) -> Optional[ClinicalTrialItem]:
    """Récupère les détails complets d'un essai par son NCT ID."""
    try:
        data = _ct_get(f"studies/{nct_id}", {})
        return ClinicalTrialItem(data)
    except Exception as e:
        logger.error(f"Failed to fetch trial {nct_id}: {e}")
        return None


def get_all_interesting_trials(
    days_back_recruiting: int = 90,
    days_back_completed: int = 180,
    days_back_new: int = 30,
) -> list[ClinicalTrialItem]:
    """
    Récupère tous les essais d'intérêt pour la semaine, toutes catégories.
    Ordonnés par intérêt décroissant :
    1. Complétés avec résultats (nouvelles données disponibles)
    2. En recrutement actif (utile pour les patientes)
    3. Nouveaux essais enregistrés (signal de la recherche)
    """
    all_trials = []

    # Priorité 1 : complétés avec résultats
    completed = search_completed_trials_with_results(days_back=days_back_completed)
    all_trials.extend(completed)
    time.sleep(1)

    # Priorité 2 : en recrutement
    recruiting = search_recruiting_trials(days_back=days_back_recruiting)
    # Éviter les doublons
    existing_ids = {t.nct_id for t in all_trials}
    all_trials.extend(t for t in recruiting if t.nct_id not in existing_ids)
    time.sleep(1)

    # Priorité 3 : nouveaux essais
    new = search_new_trials(days_back=days_back_new)
    existing_ids = {t.nct_id for t in all_trials}
    all_trials.extend(t for t in new if t.nct_id not in existing_ids)

    logger.info(
        f"Total interesting trials: {len(all_trials)} "
        f"({len(completed)} completed, {len(recruiting)} recruiting, {len(new)} new)"
    )

    return all_trials


def _is_recently_active(trial: ClinicalTrialItem, days_back: int) -> bool:
    """Vérifie si un essai a été mis à jour récemment."""
    return _updated_recently(trial, days_back)


def _updated_recently(trial: ClinicalTrialItem, days_back: int) -> bool:
    """Vérifie si la date de mise à jour est dans la fenêtre temporelle."""
    if not trial.last_update:
        return True  # Inclure si date inconnue

    try:
        # Formats possibles : "2024-03-15", "March 15, 2024"
        for fmt in ("%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d"):
            try:
                update_date = datetime.strptime(trial.last_update, fmt)
                cutoff = datetime.now() - timedelta(days=days_back)
                return update_date >= cutoff
            except ValueError:
                continue
    except Exception:
        pass

    return True  # Inclure par défaut si parse échoue


def format_trial_for_scoring(trial: ClinicalTrialItem) -> dict:
    """Formate un essai pour l'envoi au scorer GPT."""
    return {
        "nct_id": trial.nct_id,
        "title": trial.title,
        "status": trial.status,
        "phase": trial.phase,
        "enrollment": trial.enrollment,
        "has_results": trial.has_results,
        "sponsor": trial.lead_sponsor,
        "sponsor_class": trial.sponsor_class,
        "interventions": trial.intervention_names[:3],
        "primary_outcome": trial.primary_outcome[:300] if trial.primary_outcome else "",
        "summary": trial.brief_summary[:500],
        "video_category": trial.video_interest_category,
        "locations_sample": trial.locations[:3],
    }
