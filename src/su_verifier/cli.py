"""CLI entry point for su-member-verifier.

Usage:
    su-verify run          Full run: verify CSV submissions + assign roles
    su-verify scrape       Scrape the SU member list (save to JSON)
    su-verify verify       Verify CSV submissions against scraped member list
    su-verify status       Check bot permissions and configuration
    su-verify resume       Resume with saved cookies (skip manual login)

Default backend: CSV file (exported from Google Forms → Download responses .csv)
Google Sheets backend: use --sheets if you have credentials.json set up
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .csv_reader import CSVReader
from .discord_api import DiscordRoleAssigner
from .scraper import MSLScraper, Member
from .verifier import VerificationReport, Verifier

console = Console()


# ── helpers ─────────────────────────────────────────────────────────────


def load_config() -> dict:
    """Load configuration from .env file and environment."""
    load_dotenv()

    return {
        "discord_bot_token": os.getenv("DISCORD_BOT_TOKEN", ""),
        "discord_guild_id": os.getenv("DISCORD_GUILD_ID", ""),
        "discord_verified_role_id": os.getenv("DISCORD_VERIFIED_ROLE_ID", ""),
        "su_base_url": os.getenv(
            "SU_BASE_URL", "https://www.swansea-union.co.uk"
        ),
        "su_society_slug": os.getenv("SU_SOCIETY_SLUG", ""),
        "su_member_list_path": os.getenv("SU_MEMBER_LIST_PATH", ""),
        "headless": os.getenv("HEADLESS", "false").lower() == "true",
        "csv_path": os.getenv("CSV_PATH", "responses.csv"),
        "csv_url": os.getenv("CSV_URL", ""),
        "csv_col_discord_user": os.getenv("CSV_COL_DISCORD_USER", "Discord Username"),
        "csv_col_student_email": os.getenv("CSV_COL_STUDENT_EMAIL", "Student Email"),
        "csv_col_student_id": os.getenv("CSV_COL_STUDENT_ID", "Student ID"),
    }


def _load_members(members_file: str) -> list[Member]:
    """Load scraped SU members from JSON file."""
    path = Path(members_file)
    if not path.exists():
        console.print(
            f"[red]Error:[/red] {members_file} not found. "
            "Run 'su-verify scrape' first."
        )
        sys.exit(1)

    data = json.loads(path.read_text())
    members = [
        Member(
            name=m["name"],
            student_id=m.get("student_id", ""),
            email=m.get("email", ""),
            membership_type=m.get("membership_type", ""),
        )
        for m in data["members"]
    ]
    return members


def print_report(report: VerificationReport) -> None:
    """Pretty-print a verification report."""
    console.print()
    console.rule("Verification Report")

    summary = Table(title="Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Count", style="green")
    summary.add_row("Total submissions", str(report.total_submissions))
    summary.add_row("Matched ✓", str(report.matched))
    summary.add_row("Not found ✗", str(report.not_found))
    console.print(summary)

    if report.errors:
        console.print("\n[red]Errors:[/red]")
        for error in report.errors:
            console.print(f"  [red]•[/red] {error}")

    if report.results:
        table = Table(title="Results")
        table.add_column("Row", style="dim")
        table.add_column("Discord User", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Method", style="yellow")
        table.add_column("Notes", style="dim")

        for r in report.results:
            status = (
                "[green]✓ MATCHED[/green]" if r.matched else "[red]✗ NOT FOUND[/red]"
            )
            table.add_row(
                str(r.submission.row_number),
                r.submission.discord_username,
                status,
                r.match_method or "-",
                r.notes[:60] if r.notes else "-",
            )

        console.print(table)


# ── CLI commands ────────────────────────────────────────────────────────


def _ensure_first_run():
    """One-time setup: create .env if missing, download Chromium if not installed."""
    from pathlib import Path

    def _set_env_var(key: str, value: str, env_path: Path) -> None:
        """Set or update a key=value in the .env file."""
        if not env_path.exists():
            env_path.write_text(f"{key}={value}\n")
            os.environ[key] = value
            return
        lines = env_path.read_text().splitlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n")
        os.environ[key] = value

    env_file = Path(".env")
    env_template = Path(".env.example")

    if not env_file.exists() and env_template.exists():
        env_file.write_text(env_template.read_text())
        print("  [!] Created .env from template — edit it with your Discord token")
        print(f"      {env_file.absolute()}")

    # Prompt for CSV_URL if not set (committee admin should provide this)
    if not os.getenv("CSV_URL", ""):
        print("\n  The Google Sheet is key-protected. Get the CSV_URL from a committee admin.")
        url = input("  Paste CSV_URL (or press Enter to skip): ").strip()
        if url:
            _set_env_var("CSV_URL", url, env_file)
            print("  [OK] CSV_URL saved")

    # Prompt for bot token if not set
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token or token == "paste_your_token_here":
        print("\n  A Discord bot token is required. Get it from a committee admin")
        print("  or create one at https://discord.com/developers/applications")
        token = input("  Paste DISCORD_BOT_TOKEN (or press Enter to skip): ").strip()
        if token:
            _set_env_var("DISCORD_BOT_TOKEN", token, env_file)
            print("  [OK] Bot token saved")

    # Check if Chromium is installed; download if missing
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                p.chromium.launch()
            except Exception:
                print("  [!] Downloading Chromium browser (one-time, ~150MB)...")
                import subprocess, sys
                subprocess.check_call(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                print("  [OK] Chromium installed")
    except Exception:
        pass  # Playwright issues will surface when commands actually run


@click.group(invoke_without_command=True)
@click.version_option(version="1.0.0")
@click.pass_context
def main(ctx):
    """SU Member Verifier — Discord membership verification for Swansea Uni societies."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return
    _ensure_first_run()


@main.command()
@click.option(
    "--output", "-o", default="su_members.json", help="Output file for scraped members"
)
def scrape(output: str):
    """Scrape the SU member list. Opens a browser for manual login."""
    config = load_config()

    console.print("[bold]SU Member Verifier — Scrape Mode[/bold]")

    scraper = MSLScraper(
        base_url=config["su_base_url"],
        society_slug=config["su_society_slug"],
        member_list_path=config["su_member_list_path"],
        headless=config["headless"],
    )

    async def _run():
        return await scraper.run()

    result = asyncio.run(_run())

    output_data = {
        "scraped_at": result.scraped_at,
        "source_url": result.source_url,
        "total_count": result.total_count,
        "members": [
            {
                "name": m.name,
                "student_id": m.student_id,
                "email": m.email,
                "membership_type": m.membership_type,
            }
            for m in result.members
        ],
    }

    Path(output).write_text(json.dumps(output_data, indent=2))
    console.print(f"\n[green]✓[/green] Saved {result.total_count} members to {output}")


@main.command()
@click.option(
    "--members-file", "-m", default="su_members.json",
    help="JSON file with scraped members",
)
@click.option(
    "--csv", "-c", "csv_file", default="responses.csv",
    help="CSV file exported from Google Forms",
)
@click.option("--dry-run", is_flag=True, help="Verify but don't update the CSV")
@click.option(
    "--sheets", is_flag=True,
    help="Use Google Sheets API instead of CSV (requires credentials.json)",
)
def verify(members_file: str, csv_file: str, dry_run: bool, sheets: bool):
    """Cross-reference form submissions against scraped SU member list.

    Default: reads responses.csv (exported from Google Forms).
    Use --sheets for Google Sheets API with credentials.json.
    """
    config = load_config()

    console.print("[bold]SU Member Verifier — Verify Mode[/bold]")

    su_members = _load_members(members_file)
    console.print(f"Loaded {len(su_members)} SU members from {members_file}")

    reader = _get_reader(config, csv_file, sheets)
    submissions = reader.get_pending_submissions()
    console.print(f"Found {len(submissions)} pending submissions")

    if not submissions:
        console.print("[yellow]No pending submissions to verify.[/yellow]")
        return

    verifier = Verifier()
    report = verifier.verify(submissions, su_members)
    print_report(report)

    if not dry_run:
        for result in report.results:
            if result.matched:
                reader.mark_verified(result.submission.row_number)
            else:
                reader.mark_rejected(
                    result.submission.row_number, "Not in SU member list"
                )
        console.print("\n[green]✓[/green] CSV updated.")
    else:
        console.print(
            "\n[yellow]Dry run — CSV not modified. Remove --dry-run to apply.[/yellow]"
        )


@main.command()
@click.option(
    "--members-file", "-m", default="su_members.json",
    help="JSON file with scraped members",
)
@click.option(
    "--csv", "-c", "csv_file", default="responses.csv",
    help="CSV file exported from Google Forms",
)
@click.option(
    "--dry-run", is_flag=True,
    help="Show what would happen without assigning roles",
)
@click.option(
    "--keep-data", is_flag=True,
    help="Keep member list and cookies on disk after run (default: delete for privacy)",
)
@click.option(
    "--sheets", is_flag=True,
    help="Use Google Sheets API instead of CSV (requires credentials.json)",
)
def run(members_file: str, csv_file: str, dry_run: bool, keep_data: bool, sheets: bool):
    """Full pipeline: scrape SU members + verify submissions + assign Discord roles.

    Auto-scrapes the member list if su_members.json doesn't exist.
    Use --no-scrape to skip scraping and use an existing members file.
    """
    config = load_config()

    console.print("[bold]SU Member Verifier — Full Run[/bold]")

    # Auto-scrape if no members file exists
    members_path = Path(members_file)
    if not members_path.exists():
        console.print("\n[bold]Step 1: Scraping SU member list...[/bold]")
        _do_scrape(config, members_file)
        console.print()

    su_members = _load_members(members_file)
    reader = _get_reader(config, csv_file, sheets)
    submissions = reader.get_pending_submissions()

    console.print(
        f"Loaded {len(su_members)} SU members | "
        f"{len(submissions)} pending submissions"
    )

    if not submissions:
        console.print("[yellow]No pending submissions to verify.[/yellow]")
        _cleanup_sensitive_files(members_file)
        return

    verifier = Verifier()
    report = verifier.verify(submissions, su_members)
    print_report(report)

    if not dry_run:
        discord = DiscordRoleAssigner(
            bot_token=config["discord_bot_token"],
            guild_id=config["discord_guild_id"],
            verified_role_id=config["discord_verified_role_id"],
        )

        console.print("\n[bold]Assigning Discord roles...[/bold]")
        assigned = 0
        failed = 0

        for result in report.results:
            if not result.matched:
                reader.mark_rejected(
                    result.submission.row_number, "Not in SU member list"
                )
                continue

            discord_result = discord.assign_role(
                result.submission.discord_username,
                result.submission.row_number,
            )

            if discord_result.success:
                reader.mark_verified(result.submission.row_number)
                console.print(
                    f"  [green]✓[/green] {result.submission.discord_username} "
                    f"→ role assigned (row {result.submission.row_number})"
                )
                assigned += 1
            else:
                console.print(
                    f"  [red]✗[/red] {result.submission.discord_username}: "
                    f"{discord_result.error}"
                )
                failed += 1

        console.print(
            f"\n[green]✓[/green] {assigned} roles assigned, "
            f"[red]✗[/red] {failed} failed"
        )
    else:
        console.print(
            "\n[yellow]Dry run — no roles assigned. Remove --dry-run to apply.[/yellow]"
        )

    # Clean up sensitive data unless --keep-data is set
    if not keep_data and not dry_run:
        _cleanup_sensitive_files(members_file)


@main.command()
def resume():
    """Resume with saved cookies — skip the manual login step."""
    config = load_config()

    console.print("[bold]SU Member Verifier — Resume Mode[/bold]")

    scraper = MSLScraper(
        base_url=config["su_base_url"],
        society_slug=config["su_society_slug"],
        member_list_path=config["su_member_list_path"],
        headless=config["headless"],
    )

    async def _run():
        return await scraper.resume()

    result = asyncio.run(_run())

    output_data = {
        "scraped_at": result.scraped_at,
        "source_url": result.source_url,
        "total_count": result.total_count,
        "members": [
            {
                "name": m.name,
                "student_id": m.student_id,
                "email": m.email,
                "membership_type": m.membership_type,
            }
            for m in result.members
        ],
    }

    output_file = "su_members.json"
    Path(output_file).write_text(json.dumps(output_data, indent=2))
    console.print(
        f"\n[green]✓[/green] Saved {result.total_count} members to {output_file}"
    )


@main.command()
@click.option(
    "--csv", "-c", "csv_file", default="responses.csv",
    help="CSV file exported from Google Forms",
)
def status(csv_file: str):
    """Check bot permissions, CSV file, and configuration."""
    config = load_config()

    console.print("[bold]SU Member Verifier — Status Check[/bold]")
    console.print()

    # Check .env
    required_vars = [
        ("DISCORD_BOT_TOKEN", config["discord_bot_token"]),
        ("DISCORD_GUILD_ID", config["discord_guild_id"]),
        ("DISCORD_VERIFIED_ROLE_ID", config["discord_verified_role_id"]),
    ]

    console.print("[bold]Configuration:[/bold]")
    for name, value in required_vars:
        if value and value not in ("your_bot_token_here", ""):
            masked = value[:8] + "..." if len(value) > 8 else value
            console.print(f"  [green]✓[/green] {name}: {masked}")
        else:
            console.print(f"  [red]✗[/red] {name}: [red]MISSING[/red]")

    # Check CSV
    csv_path = Path(csv_file)
    if csv_path.exists():
        try:
            reader = CSVReader(
                csv_path=csv_path,
                col_discord_user=config.get("csv_col_discord_user", "Discord Username"),
                col_student_email=config.get("csv_col_student_email", "Student Email"),
                col_student_id=config.get("csv_col_student_id", "Student ID"),
            )
            subs = reader.get_pending_submissions()
            console.print(
                f"  [green]✓[/green] CSV found: {csv_file} "
                f"({len(subs)} pending)"
            )
        except Exception as e:
            console.print(f"  [red]✗[/red] CSV error: {e}")
    else:
        console.print(
            f"  [dim]CSV not found: {csv_file}[/dim]\n"
            "    Export from Google Forms: Responses tab → Download responses (.csv)"
        )

    # Discord bot
    if config["discord_bot_token"] and config["discord_bot_token"] != "your_bot_token_here":
        console.print("\n[bold]Discord Bot:[/bold]")
        try:
            discord = DiscordRoleAssigner(
                bot_token=config["discord_bot_token"],
                guild_id=config["discord_guild_id"],
                verified_role_id=config["discord_verified_role_id"],
            )
            result = discord.validate_bot_permissions()
            if result["valid"]:
                console.print("  [green]✓[/green] Bot permissions OK")
            else:
                for issue in result["issues"]:
                    console.print(f"  [red]✗[/red] {issue}")
        except Exception as e:
            console.print(f"  [red]✗[/red] Could not validate: {e}")

    # Saved cookies
    cookie_file = Path("su_cookies.json")
    if cookie_file.exists():
        import time

        age = cookie_file.stat().st_mtime
        hours_ago = (time.time() - age) / 3600
        console.print(
            f"\n  [green]✓[/green] Saved cookies "
            f"({hours_ago:.1f}h old — use 'su-verify resume' to reuse)"
        )
    else:
        console.print(
            "\n  [dim]No saved cookies yet. Run 'su-verify scrape' first.[/dim]"
        )

    console.print()


# ── backend selector ────────────────────────────────────────────────────


def _do_scrape(config: dict, output_file: str) -> None:
    """Run the scraper and save members to a file (used by auto-scrape in 'run')."""
    scraper = MSLScraper(
        base_url=config["su_base_url"],
        society_slug=config["su_society_slug"],
        member_list_path=config["su_member_list_path"],
        headless=config["headless"],
    )

    async def _run():
        return await scraper.run()

    result = asyncio.run(_run())

    output_data = {
        "scraped_at": result.scraped_at,
        "source_url": result.source_url,
        "total_count": result.total_count,
        "members": [
            {
                "name": m.name,
                "student_id": m.student_id,
                "email": m.email,
                "membership_type": m.membership_type,
            }
            for m in result.members
        ],
    }

    Path(output_file).write_text(json.dumps(output_data, indent=2))
    console.print(f"  Scraped {result.total_count} members → {output_file}")


def _cleanup_sensitive_files(members_file: str) -> None:
    """Delete sensitive data files after a verification run.

    Removes: su_members.json (real names + student IDs),
    su_cookies.json (SU session), su_debug_page.html (page dumps).
    Use --keep-data to skip cleanup for debugging.
    """
    for path in [members_file, "su_cookies.json", "su_debug_page.html"]:
        p = Path(path)
        if p.exists():
            p.unlink()
            console.print(f"  [dim]Cleaned up {p.name}[/dim]")


def _get_reader(config: dict, csv_file: str, use_sheets: bool):
    """Return the appropriate reader backend (CSV or Google Sheets)."""
    if use_sheets:
        try:
            from .sheets import SheetsReader

            return SheetsReader(
                credentials_file=os.getenv(
                    "GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json"
                ),
                sheet_id=os.getenv("GOOGLE_SHEET_ID", ""),
                worksheet_name=os.getenv("GOOGLE_SHEET_WORKSHEET", "Form Responses 1"),
                col_discord_user=os.getenv("SHEET_COL_DISCORD_USER", "Discord Username"),
                col_student_email=os.getenv("SHEET_COL_STUDENT_EMAIL", "Student Email"),
                col_student_id=os.getenv("SHEET_COL_STUDENT_ID", "Student ID"),
                col_verified=os.getenv("SHEET_COL_VERIFIED", "Verified"),
            )
        except ImportError:
            console.print(
                "[red]Error:[/red] Google Sheets support requires gspread.\n"
                "Install with: pip install gspread oauth2client"
            )
            sys.exit(1)

    return CSVReader(
        csv_path=csv_file,
        csv_url=config.get("csv_url", ""),
        col_discord_user=config.get("csv_col_discord_user", "Discord Username"),
        col_student_email=config.get("csv_col_student_email", "Student Email"),
        col_student_id=config.get("csv_col_student_id", "Student ID"),
    )


if __name__ == "__main__":
    main()
