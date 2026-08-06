"""Tests for CSV reader module."""

import csv
import tempfile
from pathlib import Path

import pytest

from su_verifier.csv_reader import CSVReader, FormSubmission


class TestCSVReader:
    """Test the CSV reader for Google Forms exports."""

    @pytest.fixture
    def sample_csv(self):
        """Create a temporary CSV file matching Google Forms export format."""
        content = [
            ["Discord Username", "Student Email", "Student ID"],
            ["john#1234", "john.smith@swansea.ac.uk", "123456"],
            ["jane#5678", "jane.doe@swansea.ac.uk", ""],
            ["bob#9012", "", "999999"],
            ["", "", ""],  # Empty row (should be skipped)
            ["alice_verified", "alice@swansea.ac.uk", "111111"],
        ]
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        writer = csv.writer(tmp)
        writer.writerows(content)
        tmp.close()
        yield tmp.name
        Path(tmp.name).unlink()

    @pytest.fixture
    def csv_with_verified(self):
        """CSV with some rows already marked verified."""
        content = [
            ["Discord Username", "Student Email", "Student ID", "Verified"],
            ["john#1234", "john@swansea.ac.uk", "123456", "TRUE"],
            ["jane#5678", "jane@swansea.ac.uk", "765432", ""],
            ["bob#9012", "bob@swansea.ac.uk", "999999", "TRUE"],
        ]
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        writer = csv.writer(tmp)
        writer.writerows(content)
        tmp.close()
        yield tmp.name
        Path(tmp.name).unlink()

    def test_read_pending_submissions(self, sample_csv):
        """Should return only unverified, non-empty rows."""
        reader = CSVReader(csv_path=sample_csv)
        subs = reader.get_pending_submissions()

        assert len(subs) == 4  # 4 data rows: john, jane, bob, alice (empty row skipped)
        assert subs[0].discord_username == "john#1234"
        assert subs[0].student_email == "john.smith@swansea.ac.uk"
        assert subs[0].student_id == "123456"
        assert subs[1].discord_username == "jane#5678"
        assert subs[1].student_id == ""
        assert subs[2].discord_username == "bob#9012"
        assert subs[2].student_email == ""
        assert subs[2].student_id == "999999"

    def test_get_all_submissions(self, sample_csv):
        """Should return all non-empty rows including unverified."""
        reader = CSVReader(csv_path=sample_csv)
        subs = reader.get_all_submissions()

        assert len(subs) == 4  # 4 data rows, empty row skipped

    def test_mark_verified(self, csv_with_verified):
        """Marking a row should persist to the CSV file."""
        reader = CSVReader(csv_path=csv_with_verified)

        # Before: only 1 pending (jane)
        pending = reader.get_pending_submissions()
        assert len(pending) == 1
        assert pending[0].discord_username == "jane#5678"

        # Mark jane as verified
        reader.mark_verified(3)  # Row 3 = jane

        # After: 0 pending
        pending = reader.get_pending_submissions()
        assert len(pending) == 0

        # Verify the file was written
        reader2 = CSVReader(csv_path=csv_with_verified)
        pending2 = reader2.get_pending_submissions()
        assert len(pending2) == 0

    def test_mark_rejected(self, csv_with_verified):
        """Rejected rows should be marked with NOT FOUND."""
        reader = CSVReader(csv_path=csv_with_verified)
        reader.mark_rejected(3, "Not in SU list")

        # Should now be 0 pending (the verified column is set, even if NOT FOUND)
        pending = reader.get_pending_submissions()
        assert len(pending) == 0

    def test_missing_file(self):
        """Should raise FileNotFoundError if CSV doesn't exist."""
        reader = CSVReader(csv_path="nonexistent.csv")
        with pytest.raises(FileNotFoundError):
            reader.get_pending_submissions()

    def test_missing_columns(self):
        """Should raise ValueError if required columns are missing."""
        content = [
            ["Wrong Header", "Student Email", "Student ID"],
            ["john", "john@swansea.ac.uk", "123456"],
        ]
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        writer = csv.writer(tmp)
        writer.writerows(content)
        tmp.close()

        try:
            reader = CSVReader(csv_path=tmp.name)
            with pytest.raises(ValueError) as excinfo:
                reader.get_pending_submissions()
            assert "Discord Username" in str(excinfo.value)
        finally:
            Path(tmp.name).unlink()

    def test_form_submission_defaults(self):
        """FormSubmission dataclass defaults."""
        fs = FormSubmission(
            row_number=1, discord_username="test", student_email="", student_id=""
        )
        assert fs.verified is False
        assert fs.raw_row == {}

    def test_auto_adds_verified_column(self, sample_csv):
        """If CSV has no Verified column, it should be added automatically."""
        reader = CSVReader(csv_path=sample_csv)
        reader.get_pending_submissions()  # Triggers _load which adds Verified

        # Mark one and verify it persists
        reader.mark_verified(3)  # jane

        reader2 = CSVReader(csv_path=sample_csv)
        subs = reader2.get_all_submissions()
        # jane should be verified now
        jane = next(s for s in subs if s.discord_username == "jane#5678")
        assert jane.verified is True
