"""Tests for SU Member Verifier."""

import pytest

from su_verifier.scraper import Member
from su_verifier.csv_reader import FormSubmission
from su_verifier.verifier import Verifier


class TestVerifier:
    """Test the cross-reference verification engine."""

    @pytest.fixture
    def su_members(self):
        return [
            Member(
                name="John Smith",
                student_id="123456",
                email="john.smith@swansea.ac.uk",
            ),
            Member(
                name="Jane Doe",
                student_id="765432",
                email="j.doe@swansea.ac.uk",  # first.last format, different from student-number email
            ),
            Member(
                name="Bob Wilson",
                student_id="",
                email="bob.wilson@swansea.ac.uk",
            ),
            Member(
                name="Alice Brown",
                student_id="999999",
                email="",
            ),
        ]

    @pytest.fixture
    def verifier(self):
        return Verifier()

    def test_exact_student_id_match(self, verifier, su_members):
        """Student ID should be the most reliable match."""
        sub = FormSubmission(
            row_number=2,
            discord_username="john#1234",
            student_email="john.smith@swansea.ac.uk",
            student_id="123456",
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 1
        result = report.results[0]
        assert result.matched
        assert result.match_method == "student_id"
        assert result.match_confidence == 1.0
        assert result.matched_member.name == "John Smith"

    def test_email_match_fallback(self, verifier, su_members):
        """When student ID is missing, fall back to email match."""
        sub = FormSubmission(
            row_number=3,
            discord_username="bob#9012",
            student_email="bob.wilson@swansea.ac.uk",
            student_id="",  # No student ID provided
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 1
        result = report.results[0]
        assert result.matched
        assert result.match_method == "email"
        assert result.match_confidence == 0.95
        assert result.matched_member.name == "Bob Wilson"

    def test_email_to_student_id_extraction(self, verifier, su_members):
        """Swansea-specific: 765432@swansea.ac.uk → extract ID 765432 → match."""
        sub = FormSubmission(
            row_number=4,
            discord_username="jane#5678",
            student_email="765432@swansea.ac.uk",  # student-number email
            student_id="",  # no explicit ID, but email contains it
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 1
        result = report.results[0]
        assert result.matched
        assert result.match_method == "email_to_student_id"
        assert result.match_confidence == 0.98
        assert result.matched_member.name == "Jane Doe"

    def test_email_to_id_respects_explicit_id(self, verifier, su_members):
        """If student_id IS provided, don't override with email-extracted ID."""
        sub = FormSubmission(
            row_number=5,
            discord_username="jane_alt",
            student_email="111111@swansea.ac.uk",  # different from 765432
            student_id="765432",  # explicit correct ID
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 1
        result = report.results[0]
        assert result.match_method == "student_id"  # explicit ID wins
        assert result.matched_member.name == "Jane Doe"

    def test_email_case_insensitive(self, verifier, su_members):
        """Email matching should be case-insensitive."""
        sub = FormSubmission(
            row_number=6,
            discord_username="bob#9012",
            student_email="BOB.WILSON@SWANSEA.AC.UK",
            student_id="",
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 1

    def test_no_match(self, verifier, su_members):
        """A submission with no matching data should not match."""
        sub = FormSubmission(
            row_number=7,
            discord_username="ghost#0000",
            student_email="ghost@swansea.ac.uk",
            student_id="000000",
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 0
        assert report.not_found == 1

    def test_empty_submission_skipped(self, verifier, su_members):
        """Empty submissions should not error, just not match."""
        sub = FormSubmission(
            row_number=8,
            discord_username="",
            student_email="",
            student_id="",
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 0

    def test_multiple_submissions_mixed(self, verifier, su_members):
        """Test a batch of mixed submissions."""
        submissions = [
            FormSubmission(
                row_number=2,
                discord_username="john#1234",
                student_email="john.smith@swansea.ac.uk",
                student_id="123456",
            ),
            FormSubmission(
                row_number=3,
                discord_username="ghost#0000",
                student_email="ghost@swansea.ac.uk",
                student_id="000000",
            ),
            FormSubmission(
                row_number=4,
                discord_username="alice#3456",
                student_email="different@other.ac.uk",
                student_id="999999",
            ),
        ]
        report = verifier.verify(submissions, su_members)
        assert report.total_submissions == 3
        assert report.matched == 2
        assert report.not_found == 1

    def test_student_id_takes_priority_over_email(self, verifier, su_members):
        """Student ID match should take priority even if email differs."""
        sub = FormSubmission(
            row_number=9,
            discord_username="alice#3456",
            student_email="alice.different@swansea.ac.uk",  # Different email!
            student_id="999999",
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 1
        assert report.results[0].match_method == "student_id"

    def test_exact_name_match(self, verifier, su_members):
        """When ID and email are missing from submission, try name matching."""
        sub = FormSubmission(
            row_number=10,
            discord_username="john_alt",
            student_email="",
            student_id="",
            raw_row={"Full Name": "John Smith"},
        )
        report = verifier.verify([sub], su_members)
        assert report.matched == 1
        assert report.results[0].match_method == "name_exact"
        assert report.results[0].match_confidence == 0.7


class TestMemberParsing:
    """Test the Member dataclass and parsing helpers."""

    def test_member_creation(self):
        m = Member(
            name="Test User",
            student_id="123456",
            email="test@swansea.ac.uk",
        )
        assert m.name == "Test User"
        assert m.student_id == "123456"
        assert m.email == "test@swansea.ac.uk"

    def test_member_defaults(self):
        m = Member(name="Minimal")
        assert m.name == "Minimal"
        assert m.student_id == ""
        assert m.email == ""

    def test_normalize_email(self):
        assert Verifier._normalize_email("Test@Swansea.ac.uk") == "test@swansea.ac.uk"
        assert Verifier._normalize_email("  user@domain.com  ") == "user@domain.com"

    def test_extract_student_id_from_email(self):
        """Swansea email format: 1234567@swansea.ac.uk → '1234567'."""
        assert Verifier._extract_student_id_from_email("1234567@swansea.ac.uk") == "1234567"
        assert Verifier._extract_student_id_from_email("123456@swansea.ac.uk") == "123456"   # 6-digit
        assert Verifier._extract_student_id_from_email("12345@swansea.ac.uk") == "12345"     # 5-digit
        assert Verifier._extract_student_id_from_email("1234567@SWANSEA.AC.UK") == "1234567"
        assert Verifier._extract_student_id_from_email("j.doe@swansea.ac.uk") == ""
        assert Verifier._extract_student_id_from_email("not-an-email") == ""
        assert Verifier._extract_student_id_from_email("1234@swansea.ac.uk") == ""   # too short

    def test_normalize_name(self):
        assert Verifier._normalize_name("Mr John Smith") == "john smith"
        assert Verifier._normalize_name("Dr. Jane Doe") == "jane doe"
        assert Verifier._normalize_name("  ALICE   BROWN  ") == "alice brown"
