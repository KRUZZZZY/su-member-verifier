"""CSV reader for Google Forms responses — no Google Cloud needed.

Committee member workflow:
1. Open the Google Form → Responses tab
2. Click "Download responses (.csv)"
3. Save as responses.csv in the project folder
4. Run su-verify with --csv responses.csv
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class FormSubmission:
    """A single form submission row from the CSV."""

    row_number: int
    discord_username: str
    student_email: str
    student_id: str
    verified: bool = False
    raw_row: dict | None = None

    def __post_init__(self):
        if self.raw_row is None:
            self.raw_row = {}


class CSVReader:
    """Reads Google Form responses from an exported CSV file.

    Expected CSV columns (exact header names from Google Forms):
      - "Discord Username"
      - "Student Email"
      - "Student ID"

    Optional column for tracking:
      - "Verified" (TRUE/FALSE or empty)
    """

    def __init__(
        self,
        csv_path: str | Path = "responses.csv",
        csv_url: str = "",
        col_discord_user: str = "Discord Username",
        col_student_email: str = "Student Email",
        col_student_id: str = "Student ID",
        col_verified: str = "Verified",
    ):
        self.csv_path = Path(csv_path)
        self.csv_url = csv_url
        self.col_discord_user = col_discord_user
        self.col_student_email = col_student_email
        self.col_student_id = col_student_id
        self.col_verified = col_verified

        self._rows: list[dict] = []
        self._headers: list[str] = []
        self._read_only = False  # True when fetching from URL (can't write back)

    # ── reading ─────────────────────────────────────────────────────────

    def get_pending_submissions(self) -> list[FormSubmission]:
        """Get all form submissions that haven't been verified yet."""
        self._load()
        submissions: list[FormSubmission] = []

        for i, row in enumerate(self._rows, start=2):  # Row 1 is headers
            discord_user = str(row.get(self.col_discord_user, "")).strip()
            student_email = str(row.get(self.col_student_email, "")).strip()
            student_id = str(row.get(self.col_student_id, "")).strip()
            verified_raw = str(row.get(self.col_verified, "")).strip().lower()

            if not discord_user and not student_email and not student_id:
                continue

            if verified_raw in ("yes", "true", "1", "verified", "✓", "x"):
                continue
            if "not found" in verified_raw:
                continue

            submissions.append(
                FormSubmission(
                    row_number=i,
                    discord_username=discord_user,
                    student_email=student_email,
                    student_id=student_id,
                    verified=False,
                    raw_row=row,
                )
            )

        return submissions

    def get_all_submissions(self) -> list[FormSubmission]:
        """Get ALL form submissions (including already verified)."""
        self._load()
        submissions: list[FormSubmission] = []

        for i, row in enumerate(self._rows, start=2):
            discord_user = str(row.get(self.col_discord_user, "")).strip()
            student_email = str(row.get(self.col_student_email, "")).strip()
            student_id = str(row.get(self.col_student_id, "")).strip()
            verified_raw = str(row.get(self.col_verified, "")).strip().lower()

            if not discord_user and not student_email and not student_id:
                continue

            submissions.append(
                FormSubmission(
                    row_number=i,
                    discord_username=discord_user,
                    student_email=student_email,
                    student_id=student_id,
                    verified=verified_raw in ("yes", "true", "1", "verified", "✓", "x"),
                    raw_row=row,
                )
            )

        return submissions

    # ── writing ─────────────────────────────────────────────────────────

    def mark_verified(self, row_number: int) -> None:
        """Mark a row as verified. No-op in URL mode (can't write to published sheet)."""
        self._load()
        if self._read_only:
            return
        row_idx = row_number - 2
        if 0 <= row_idx < len(self._rows):
            self._rows[row_idx][self.col_verified] = "TRUE"
            self._save()

    def mark_rejected(self, row_number: int, reason: str = "") -> None:
        """Mark a row as rejected. No-op in URL mode (can't write to published sheet)."""
        self._load()
        if self._read_only:
            return
        row_idx = row_number - 2
        if 0 <= row_idx < len(self._rows):
            value = f"NOT FOUND: {reason}" if reason else "NOT FOUND"
            self._rows[row_idx][self.col_verified] = value
            self._save()

    # ── internal ────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load CSV into memory — from URL if configured, otherwise local file."""
        if self._rows:
            return

        if self.csv_url:
            self._load_from_url()
        else:
            self._load_from_file()

        # Check required columns exist
        missing = []
        for col in [self.col_discord_user, self.col_student_email, self.col_student_id]:
            if col not in self._headers:
                missing.append(col)
        if missing:
            raise ValueError(
                f"CSV missing required columns: {missing}\n"
                f"Found headers: {self._headers}\n"
                "Check your Google Form question titles or CSV_COL_* settings in .env"
            )

        # Ensure Verified column exists (add if not)
        if self.col_verified not in self._headers:
            self._headers.append(self.col_verified)
            for row in self._rows:
                row[self.col_verified] = ""

    def _load_from_url(self) -> None:
        """Fetch published Google Sheet as CSV."""
        resp = httpx.get(self.csv_url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        content = resp.text

        reader = csv.DictReader(io.StringIO(content))
        self._headers = reader.fieldnames or []
        self._rows = list(reader)
        self._read_only = True

    def _load_from_file(self) -> None:
        """Load CSV from local file."""
        if not self.csv_path.exists():
            raise FileNotFoundError(
                f"CSV file not found: {self.csv_path}\n"
                "Export it from Google Forms: Responses tab → Download responses (.csv)"
            )

        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self._headers = reader.fieldnames or []
            self._rows = list(reader)

    def _save(self) -> None:
        """Write changes back to CSV."""
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._headers)
            writer.writeheader()
            writer.writerows(self._rows)
