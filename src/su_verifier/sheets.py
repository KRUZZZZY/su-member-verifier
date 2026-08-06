"""Google Sheets integration for reading membership form submissions.

Uses a Google Cloud service account for authentication. The service account
email must be shared with Editor access on the target spreadsheet.

Setup:
1. Create a project in Google Cloud Console
2. Enable Google Sheets API
3. Create a service account → download JSON key
4. Share your sheet with the service account email
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import gspread
from oauth2client.service_account import ServiceAccountCredentials


@dataclass
class FormSubmission:
    """A single form submission row from the sheet."""

    row_number: int
    discord_username: str
    student_email: str
    student_id: str
    verified: bool = False
    raw_row: dict = None

    def __post_init__(self):
        if self.raw_row is None:
            self.raw_row = {}


class SheetsReader:
    """Reads form submissions from a Google Sheet and updates verification status."""

    SCOPE = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(
        self,
        credentials_file: str | Path = "credentials.json",
        sheet_id: str = "",
        worksheet_name: str = "Form Responses 1",
        col_discord_user: str = "Discord Username",
        col_student_email: str = "Student Email",
        col_student_id: str = "Student ID",
        col_verified: str = "Verified",
    ):
        self.credentials_file = Path(credentials_file)
        self.sheet_id = sheet_id
        self.worksheet_name = worksheet_name
        self.col_discord_user = col_discord_user
        self.col_student_email = col_student_email
        self.col_student_id = col_student_id
        self.col_verified = col_verified

        self._client: Optional[gspread.Client] = None
        self._worksheet: Optional[gspread.Worksheet] = None

    # ── connection ──────────────────────────────────────────────────────

    def connect(self) -> None:
        """Authenticate and open the target worksheet."""
        if not self.credentials_file.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_file}\n"
                "Download it from Google Cloud Console → APIs & Services → Credentials"
            )

        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            str(self.credentials_file), self.SCOPE
        )
        self._client = gspread.authorize(credentials)

        sheet = self._client.open_by_key(self.sheet_id)
        self._worksheet = (
            sheet.worksheet(self.worksheet_name)
            if self.worksheet_name
            else sheet.sheet1
        )
        print(f"  ✓ Connected to sheet: {sheet.title} → {self._worksheet.title}")

    # ── reading ─────────────────────────────────────────────────────────

    def get_pending_submissions(self) -> list[FormSubmission]:
        """Get all form submissions that haven't been verified yet.

        Returns rows where the Verified column is empty/false.
        """
        if not self._worksheet:
            self.connect()

        all_rows = self._worksheet.get_all_records()
        headers = self._worksheet.row_values(1)

        submissions: list[FormSubmission] = []
        for i, row in enumerate(all_rows, start=2):  # Row 1 is headers, data starts at 2
            discord_user = str(row.get(self.col_discord_user, "")).strip()
            student_email = str(row.get(self.col_student_email, "")).strip()
            student_id = str(row.get(self.col_student_id, "")).strip()
            verified_raw = str(row.get(self.col_verified, "")).strip().lower()

            # Skip empty rows
            if not discord_user and not student_email and not student_id:
                continue

            # Skip already verified rows
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
        if not self._worksheet:
            self.connect()

        all_rows = self._worksheet.get_all_records()
        submissions: list[FormSubmission] = []

        for i, row in enumerate(all_rows, start=2):
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
        """Mark a row as verified in the sheet."""
        if not self._worksheet:
            self.connect()

        # Find the verified column index
        headers = self._worksheet.row_values(1)
        try:
            col_idx = headers.index(self.col_verified) + 1  # 1-indexed
        except ValueError:
            # If the column doesn't exist yet, we can't mark it
            print(f"  ⚠ Column '{self.col_verified}' not found in sheet headers")
            return

        self._worksheet.update_cell(row_number, col_idx, "TRUE")
        print(f"  ✓ Marked row {row_number} as verified")

    def mark_rejected(self, row_number: int, reason: str = "") -> None:
        """Mark a row as rejected/not-found in the sheet."""
        if not self._worksheet:
            self.connect()

        headers = self._worksheet.row_values(1)
        try:
            col_idx = headers.index(self.col_verified) + 1
        except ValueError:
            print(f"  ⚠ Column '{self.col_verified}' not found in sheet headers")
            return

        value = f"NOT FOUND: {reason}" if reason else "NOT FOUND"
        self._worksheet.update_cell(row_number, col_idx, value)
        print(f"  ✗ Marked row {row_number} as not found")
