"""MSL (Membership Solutions Limited) scraper for Swansea Students' Union.

Captures session cookies from a manual browser login, then navigates to the
society's member management page to scrape the member list.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


@dataclass
class Member:
    """A single society member scraped from MSL."""

    name: str
    student_id: str = ""
    email: str = ""
    membership_type: str = ""
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self):
        # Normalize MSL "LASTNAME, FIRSTNAME" to "firstname lastname"
        if "," in self.name:
            parts = [p.strip() for p in self.name.split(",", 1)]
            if len(parts) == 2:
                self.name = f"{parts[1]} {parts[0]}".lower()
        self.name = self.name.strip()


@dataclass
class ScraperResult:
    """Result of a scraping run."""

    members: list[Member]
    total_count: int
    source_url: str
    scraped_at: str


class MSLScraper:
    """Scrapes society member data from the MSL-powered SU website.

    The SU uses MSL (ukmsl.com/client/6166), which powers both the public
    swansea-union.co.uk site and the admin panel at /msl/. Society committee
    members can view their member list through the MSL Website admin area.

    Workflow:
    1. Open a browser to the SU login page.
    2. Wait for the user to log in manually (SSO via Azure AD, or username/password).
    3. Detect successful login (redirect away from /login/).
    4. Capture session cookies.
    5. Navigate to the society member list page.
    6. Scrape the member data from the table.
    """

    def __init__(
        self,
        base_url: str = "https://www.swansea-union.co.uk",
        society_slug: str = "",
        member_list_path: str = "",
        headless: bool = False,
        cookie_file: Optional[Path] = None,
        login_timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.society_slug = society_slug
        self.member_list_path = member_list_path or (
            f"/organisation/societies/{society_slug}/members/"
        )
        self.headless = headless
        self.cookie_file = cookie_file or Path("su_cookies.json")
        self.login_timeout = login_timeout

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── public API ──────────────────────────────────────────────────────

    async def run(self) -> ScraperResult:
        """Run the full scrape workflow. Returns the member list."""
        await self._launch()

        try:
            await self._handle_login()
            member_url = await self._resolve_member_list_url()
            members = await self._scrape_member_list(member_url)
        finally:
            await self._teardown()

        result = ScraperResult(
            members=members,
            total_count=len(members),
            source_url=member_url,
            scraped_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return result

    async def resume(self) -> ScraperResult:
        """Resume with previously saved cookies — skips the login step."""
        if not self.cookie_file.exists():
            raise FileNotFoundError(
                f"No saved cookies at {self.cookie_file}. Run a full `run()` first."
            )

        await self._launch()
        await self._load_cookies()

        try:
            # Verify cookies still work
            await self._page.goto(f"{self.base_url}/", wait_until="networkidle")
            if "/login/" in self._page.url:
                raise RuntimeError(
                    "Saved cookies have expired. Please run a full `run()` to re-login."
                )

            member_url = await self._resolve_member_list_url()
            members = await self._scrape_member_list(member_url)
        finally:
            await self._teardown()

        return ScraperResult(
            members=members,
            total_count=len(members),
            source_url=member_url,
            scraped_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    # ── browser lifecycle ───────────────────────────────────────────────

    async def _launch(self) -> None:
        """Launch browser and create a context."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()

    async def _teardown(self) -> None:
        """Close browser and save cookies."""
        if self._context and self._page:
            try:
                cookies = await self._context.cookies()
                self.cookie_file.write_text(json.dumps(cookies, indent=2))
            except Exception:
                pass

        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _load_cookies(self) -> None:
        """Load previously saved cookies into the browser context."""
        cookies = json.loads(self.cookie_file.read_text())
        await self._context.add_cookies(cookies)

    # ── login flow ──────────────────────────────────────────────────────

    async def _handle_login(self) -> None:
        """Navigate to login page and wait for the user to complete login manually.

        The SU login page offers:
        - Username + Password login
        - SSO via @swansea.ac.uk (Azure AD)
        - SSO via @swansea-union.co.uk

        We just wait until the URL no longer contains '/login/'.
        """
        login_url = f"{self.base_url}/login/"
        print(f"\n  Opening browser to: {login_url}")
        print("  ─────────────────────────────────────────────")
        print("  Please log in manually in the browser window.")
        print("  The script will detect when you're logged in.")
        print(f"  Timeout: {self.login_timeout}s")
        print("  ─────────────────────────────────────────────\n")

        await self._page.goto(login_url, wait_until="networkidle")

        # Wait for login to complete — user must land back on the SU domain
        # (not on Microsoft/SSO redirect pages — hostname check avoids
        # false positives from SU URLs embedded in SAML RelayState params)
        start = time.monotonic()
        while time.monotonic() - start < self.login_timeout:
            url = self._page.url
            host = urlparse(url).hostname or ""
            on_su_domain = host.endswith("swansea-union.co.uk") or host.endswith("swansea.ac.uk")
            is_auth_page = (
                "/login/" in url
                or "/account/" in url
                or "/sso/" in url
            )
            if on_su_domain and not is_auth_page:
                host = urlparse(url).hostname or url
                print(f"  ✓ Login detected! (host: {host})")
                break
            await asyncio.sleep(1)
        else:
            raise TimeoutError(
                f"Login not detected within {self.login_timeout}s. "
                "Please try again and make sure you log in completely."
            )

        # Small pause to let any redirects settle
        await asyncio.sleep(2)

        # Save cookies immediately
        cookies = await self._context.cookies()
        self.cookie_file.write_text(json.dumps(cookies, indent=2))
        print(f"  ✓ Session cookies saved to {self.cookie_file}")

    # ── navigation ──────────────────────────────────────────────────────

    async def _resolve_member_list_url(self) -> str:
        """Try to find the member list page for the society.

        First tries the configured path, then attempts to discover it by
        navigating from the dashboard.
        """
        member_url = f"{self.base_url}{self.member_list_path}"

        # Try the direct URL first
        resp = await self._page.goto(member_url, wait_until="networkidle")
        if resp and resp.status < 400:
            # Check if this looks like a member list page
            content = await self._page.content()
            if any(
                keyword in content.lower()
                for keyword in ["member", "membership", "student id", "student name"]
            ):
                print(f"  ✓ Found member list at: {member_url}")
                return member_url

        # Fall back: try to discover from the organisation dashboard
        print("  Direct member URL not found, trying to discover from dashboard...")
        await self._page.goto(
            f"{self.base_url}/organisation/societies/", wait_until="networkidle"
        )

        # Look for links containing the society slug
        links = await self._page.query_selector_all("a")
        for link in links:
            href = await link.get_attribute("href")
            if href and self.society_slug in href:
                if "member" in href.lower() or "admin" in href.lower():
                    full_url = (
                        href if href.startswith("http") else f"{self.base_url}{href}"
                    )
                    print(f"  ✓ Discovered member list at: {full_url}")
                    return full_url

        # If discovery fails, return the configured URL anyway — maybe the user
        # gave us a path that requires JavaScript rendering
        print(
            f"  ⚠ Could not auto-discover member list. Using configured URL: {member_url}"
        )
        print(
            "  If this doesn't work, set SU_MEMBER_LIST_PATH in your .env to the correct path."
        )
        return member_url

    # ── scraping ────────────────────────────────────────────────────────

    async def _scrape_member_list(self, url: str) -> list[Member]:
        """Scrape the member list from the page.

        MSL typically renders member data in HTML tables. We look for:
        1. <table> elements with member data
        2. <div>/<li> list-style layouts
        """
        await self._page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)  # Let any JS rendering finish

        content = await self._page.content()

        # Strategy 1: Look for HTML tables
        members = await self._scrape_table()
        if members:
            print(f"  ✓ Scraped {len(members)} members from table")
            return members

        # Strategy 2: Look for list-style member cards
        members = await self._scrape_list_items()
        if members:
            print(f"  ✓ Scraped {len(members)} members from list view")
            return members

        # Strategy 3: Generic approach — try to extract any structured data
        members = await self._scrape_generic()
        if members:
            print(f"  ✓ Scraped {len(members)} members using generic extraction")
            return members

        # Nothing found — save the page for debugging
        debug_path = Path("su_debug_page.html")
        debug_path.write_text(content)
        print(f"  ⚠ No member data found. Page saved to {debug_path} for inspection.")
        print(
            "  Open the file and look for member data patterns, then update the scraper."
        )
        return []

    async def _scrape_table(self) -> list[Member]:
        """Try to extract members from HTML tables."""
        tables = await self._page.query_selector_all("table")
        members: list[Member] = []

        for table in tables:
            # Get headers
            headers: list[str] = []
            th_elements = await table.query_selector_all("th")
            for th in th_elements:
                text = (await th.inner_text()).strip().lower()
                headers.append(text)

            if not headers:
                continue

            # Check if this looks like a member table
            member_indicators = {"name", "student", "email", "id", "member", "card"}
            if not any(any(ind in h for ind in member_indicators) for h in headers):
                continue

            # Extract rows
            rows = await table.query_selector_all("tbody tr")
            if not rows:
                rows = await table.query_selector_all("tr")

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                values = [(await cell.inner_text()).strip() for cell in cells]
                member = Member(
                    name=values[0] if len(values) > 0 else "",
                    student_id=self._find_value(values, headers, ["student id", "id", "card number", "card"]),
                    email=self._find_value(values, headers, ["email"]),
                    membership_type=self._find_value(
                        values, headers, ["membership", "type"]
                    ),
                    raw_data=dict(zip(headers, values)),
                )
                if member.name:
                    members.append(member)

        return members

    async def _scrape_list_items(self) -> list[Member]:
        """Try to extract members from list/card-style layouts."""
        members: list[Member] = []

        # Common MSL patterns: .member-card, .member-item, .membership-row
        selectors = [
            ".member-card",
            ".member-item",
            ".membership-row",
            "[class*='member']",
            "li.member",
            ".member-list > div",
        ]

        for selector in selectors:
            elements = await self._page.query_selector_all(selector)
            if not elements:
                continue

            for el in elements:
                text = (await el.inner_text()).strip()
                if not text or len(text) < 3:
                    continue

                # Try to parse name and other fields from the text
                member = self._parse_member_text(text)
                if member and member.name:
                    members.append(member)

            if members:
                break

        return members

    async def _scrape_generic(self) -> list[Member]:
        """Generic extraction — look for any structured data patterns on the page."""
        members: list[Member] = []

        # Try to extract all visible text and look for patterns
        body_text = await self._page.inner_text("body")
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]

        # Swansea student ID: variable length (usually 6-7 digits)
        # Look for patterns like "Name: John Smith" or "John Smith - 1234567"
        name_pattern = re.compile(
            r"^([A-Z][a-z]+(?: [A-Z][a-z]+)+)\s*[-–—]\s*(\d{5,10})\b"
        )
        # Swansea emails: studentnumber@swansea.ac.uk or first.last@swansea.ac.uk
        email_pattern = re.compile(r"([a-zA-Z0-9._%+-]+@swansea\.ac\.uk)")
        student_id_pattern = re.compile(r"\b(\d{5,10})\b")

        current_member: Optional[Member] = None

        for line in lines:
            # Try name + student ID pattern
            match = name_pattern.match(line)
            if match:
                if current_member:
                    members.append(current_member)
                current_member = Member(
                    name=match.group(1), student_id=match.group(2)
                )
                continue

            # Try Swansea email (studentnumber@ or first.last@)
            match = email_pattern.search(line)
            if match and current_member:
                current_member.email = match.group(1)
                continue

            # Try standalone 6-digit student ID
            match = student_id_pattern.search(line)
            if match and current_member and not current_member.student_id:
                current_member.student_id = match.group(1)
                continue

            # If line looks like a name (two+ capitalized words) and we're accumulating
            if (
                current_member
                and re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+", line)
                and "@" not in line
            ):
                members.append(current_member)
                current_member = Member(name=line)
                continue

        if current_member and current_member.name:
            members.append(current_member)

        return members

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _find_value(
        values: list[str], headers: list[str], targets: list[str]
    ) -> str:
        """Find a value by matching a target keyword against headers."""
        for target in targets:
            for i, header in enumerate(headers):
                if target in header and i < len(values):
                    return values[i]
        return ""

    @staticmethod
    def _parse_member_text(text: str) -> Optional[Member]:
        """Try to extract member info from a block of text."""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return None

        name = lines[0] if lines else ""
        student_id = ""
        email = ""

        for line in lines:
            if "@swansea" in line.lower():
                email = line.strip()
            elif re.match(r"^\d{5,10}$", line.strip()):
                student_id = line.strip()

        # If we got nothing useful, the first line might not be a name
        if not name or len(name) < 3:
            return None

        return Member(name=name, student_id=student_id, email=email)
