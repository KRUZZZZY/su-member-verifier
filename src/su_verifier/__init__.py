"""SU Member Verifier — Discord membership verification for Swansea Uni societies.

Scrapes the MSL-powered SU member list, cross-references CSV submissions
(exported from Google Forms), and assigns Discord roles to verified members.

No Google Cloud billing required — uses CSV file export from Google Forms.
"""

from .csv_reader import CSVReader, FormSubmission
from .discord_api import DiscordRoleAssigner
from .scraper import MSLScraper, Member, ScraperResult
from .verifier import MatchResult, VerificationReport, Verifier

__version__ = "1.0.0"
__all__ = [
    "MSLScraper",
    "Member",
    "ScraperResult",
    "CSVReader",
    "FormSubmission",
    "Verifier",
    "MatchResult",
    "VerificationReport",
    "DiscordRoleAssigner",
]
