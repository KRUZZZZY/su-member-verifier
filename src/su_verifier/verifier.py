"""Cross-reference engine: matches Google Form submissions against the
scraped SU member list and produces verification results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .scraper import Member
from .sheets import FormSubmission


@dataclass
class MatchResult:
    """Result of cross-referencing one form submission."""

    submission: FormSubmission
    matched: bool
    matched_member: Member | None = None
    match_confidence: float = 0.0
    match_method: str = ""
    notes: str = ""


@dataclass
class VerificationReport:
    """Full verification run report."""

    total_submissions: int
    matched: int
    not_found: int
    results: list[MatchResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class Verifier:
    """Cross-references form submissions against the SU member list.

    Matching strategies (tried in order):
    1. Student ID match (exact) — most reliable
    2. Email match (case-insensitive, domain-normalized)
    3. Name match (fuzzy, for when IDs/emails are missing)
    """

    def __init__(
        self,
        fuzzy_name_threshold: float = 0.85,
    ):
        self.fuzzy_name_threshold = fuzzy_name_threshold

    # ── public API ──────────────────────────────────────────────────────

    def verify(
        self,
        submissions: list[FormSubmission],
        su_members: list[Member],
    ) -> VerificationReport:
        """Cross-reference all submissions against the SU member list."""
        results: list[MatchResult] = []
        errors: list[str] = []

        # Build lookup indices for fast matching
        member_by_id: dict[str, Member] = {}
        member_by_email: dict[str, Member] = {}
        member_by_name: dict[str, Member] = {}

        for m in su_members:
            if m.student_id:
                member_by_id[m.student_id.strip().lower()] = m
            if m.email:
                member_by_email[self._normalize_email(m.email)] = m
            if m.name:
                member_by_name[self._normalize_name(m.name)] = m

        for sub in submissions:
            try:
                result = self._match_submission(
                    sub, member_by_id, member_by_email, member_by_name
                )
                results.append(result)
            except Exception as e:
                errors.append(f"Error processing row {sub.row_number}: {e}")
                results.append(
                    MatchResult(
                        submission=sub,
                        matched=False,
                        notes=f"Error: {e}",
                    )
                )

        matched_count = sum(1 for r in results if r.matched)

        return VerificationReport(
            total_submissions=len(submissions),
            matched=matched_count,
            not_found=len(submissions) - matched_count,
            results=results,
            errors=errors,
        )

    # ── matching logic ──────────────────────────────────────────────────

    def _match_submission(
        self,
        sub: FormSubmission,
        by_id: dict[str, Member],
        by_email: dict[str, Member],
        by_name: dict[str, Member],
    ) -> MatchResult:
        """Try to match a single submission using available data."""

        # Strategy 1: Student ID (most reliable)
        if sub.student_id:
            key = sub.student_id.strip().lower()
            if key in by_id:
                return MatchResult(
                    submission=sub,
                    matched=True,
                    matched_member=by_id[key],
                    match_confidence=1.0,
                    match_method="student_id",
                    notes="Exact student ID match",
                )

        # Strategy 2: Email
        if sub.student_email:
            key = self._normalize_email(sub.student_email)
            if key in by_email:
                return MatchResult(
                    submission=sub,
                    matched=True,
                    matched_member=by_email[key],
                    match_confidence=0.95,
                    match_method="email",
                    notes="Email address match",
                )
            # Try domain-stripped: just the local part
            local = key.split("@")[0] if "@" in key else key
            for email_key, member in by_email.items():
                if email_key.split("@")[0] == local:
                    return MatchResult(
                        submission=sub,
                        matched=True,
                        matched_member=member,
                        match_confidence=0.9,
                        match_method="email_local",
                        notes="Email local-part match (different domain)",
                    )

            # Swansea-specific: extract student ID from 123456@swansea.ac.uk emails
            extracted_id = self._extract_student_id_from_email(sub.student_email)
            if extracted_id and extracted_id in by_id and not sub.student_id:
                return MatchResult(
                    submission=sub,
                    matched=True,
                    matched_member=by_id[extracted_id],
                    match_confidence=0.98,
                    match_method="email_to_student_id",
                    notes="Student ID extracted from Swansea email format",
                )

        # Strategy 3: Name (fuzzy — least reliable, used as fallback)
        if sub.raw_row:
            # Try to find a name field in the submission
            name = self._extract_name_from_submission(sub)
            if name:
                norm_name = self._normalize_name(name)
                # Exact name match
                if norm_name in by_name:
                    return MatchResult(
                        submission=sub,
                        matched=True,
                        matched_member=by_name[norm_name],
                        match_confidence=0.7,
                        match_method="name_exact",
                        notes="Exact name match (verify manually)",
                    )
                # Fuzzy name match
                best = self._fuzzy_match_name(norm_name, by_name)
                if best:
                    return MatchResult(
                        submission=sub,
                        matched=True,
                        matched_member=best,
                        match_confidence=0.5,
                        match_method="name_fuzzy",
                        notes="Fuzzy name match (verify manually)",
                    )

        # No match found
        return MatchResult(
            submission=sub,
            matched=False,
            notes=(
                f"No match: ID='{sub.student_id}', "
                f"email='{sub.student_email}' not found in SU member list"
            ),
        )

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Normalize email for comparison: lowercase, strip whitespace.

        Swansea uses multiple formats:
          - 123456@swansea.ac.uk (student number)
          - j.doe@swansea.ac.uk (first_initial.last)

        We normalize to lowercase. For student-number emails, we also
        extract the student ID for secondary matching.
        """
        return email.strip().lower()

    @staticmethod
    def _extract_student_id_from_email(email: str) -> str:
        """Try to extract a student ID from a Swansea email address.

        Format: 123456@swansea.ac.uk → '123456'
        Returns empty string if not a student-number email.
        """
        email = email.strip().lower()
        match = re.match(r"^(\d{5,10})@swansea\.ac\.uk$", email)
        return match.group(1) if match else ""

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize name for comparison: lowercase, strip titles/punctuation."""
        normalized = name.strip().lower()
        # Remove punctuation first so "Dr." becomes "Dr"
        normalized = "".join(
            c for c in normalized if c.isalpha() or c.isspace()
        )
        # Collapse multiple spaces
        normalized = " ".join(normalized.split())
        # Remove common titles
        for title in ("mr ", "mrs ", "ms ", "miss ", "dr ", "prof "):
            if normalized.startswith(title):
                normalized = normalized[len(title) :]
        return normalized

    @staticmethod
    def _extract_name_from_submission(sub: FormSubmission) -> str:
        """Try to extract a name from the submission's raw data."""
        # Look for a "Name" or "Full Name" field
        for key in sub.raw_row:
            if "name" in key.lower():
                val = str(sub.raw_row[key]).strip()
                if val and len(val) > 2:
                    return val
        return ""

    def _fuzzy_match_name(
        self, name: str, candidates: dict[str, Member]
    ) -> Member | None:
        """Find the best fuzzy name match using token similarity."""

        def token_similarity(a: str, b: str) -> float:
            """Jaccard-like token overlap."""
            tokens_a = set(a.split())
            tokens_b = set(b.split())
            if not tokens_a or not tokens_b:
                return 0.0
            intersection = tokens_a & tokens_b
            union = tokens_a | tokens_b
            return len(intersection) / len(union)

        best_score = 0.0
        best_member = None

        for cand_name, member in candidates.items():
            score = token_similarity(name, cand_name)
            if score > best_score and score >= self.fuzzy_name_threshold:
                best_score = score
                best_member = member

        return best_member
