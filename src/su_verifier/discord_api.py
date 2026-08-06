"""Discord API integration for assigning roles to verified members.

Uses the Discord HTTP API directly (via httpx) rather than a full bot client.
This is lighter weight since we only need role assignment — no event handling.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


@dataclass
class DiscordUser:
    """A Discord user found by username."""

    id: str
    username: str
    discriminator: str
    nickname: str | None = None


@dataclass
class AssignmentResult:
    """Result of attempting to assign a role."""

    submission_row: int
    discord_username: str
    success: bool
    error: str = ""


class DiscordRoleAssigner:
    """Assigns Discord roles to verified members via the Discord HTTP API."""

    API_BASE = "https://discord.com/api/v10"

    def __init__(
        self,
        bot_token: str,
        guild_id: str,
        verified_role_id: str,
    ):
        if not bot_token or bot_token in ("your_bot_token_here", "paste_your_token_here"):
            raise ValueError(
                "DISCORD_BOT_TOKEN is not set. Run the tool again to enter it, "
                "or edit .env manually."
            )
        if not guild_id:
            raise ValueError("DISCORD_GUILD_ID is not set")
        if not verified_role_id:
            raise ValueError("DISCORD_VERIFIED_ROLE_ID is not set")

        self.bot_token = bot_token
        self.guild_id = guild_id
        self.verified_role_id = verified_role_id

    # ── public API ──────────────────────────────────────────────────────

    def assign_role(
        self, discord_username: str, row_number: int = 0
    ) -> AssignmentResult:
        """Find a Discord user by username and assign the verified role.

        Args:
            discord_username: Discord username (e.g., 'kruzzzzy' or 'user#1234')
            row_number: Sheet row number for reporting
        """
        # Find the user
        try:
            user = self._find_member(discord_username)
            if not user:
                return AssignmentResult(
                    submission_row=row_number,
                    discord_username=discord_username,
                    success=False,
                    error=f"User '{discord_username}' not found in the server",
                )
        except Exception as e:
            return AssignmentResult(
                submission_row=row_number,
                discord_username=discord_username,
                success=False,
                error=f"Error finding user: {e}",
            )

        # Assign the role
        try:
            self._add_role(user.id, self.verified_role_id)
            return AssignmentResult(
                submission_row=row_number,
                discord_username=discord_username,
                success=True,
            )
        except Exception as e:
            return AssignmentResult(
                submission_row=row_number,
                discord_username=discord_username,
                success=False,
                error=f"Error assigning role: {e}",
            )

    def assign_roles_batch(
        self, usernames: list[tuple[int, str]]
    ) -> list[AssignmentResult]:
        """Assign roles to multiple users with rate-limit handling."""
        results: list[AssignmentResult] = []
        for row_number, username in usernames:
            result = self.assign_role(username, row_number)
            results.append(result)
            if result.success:
                time.sleep(0.5)  # Rate limit: ~2 role assignments/sec
        return results

    # ── internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _request_with_retry(
        method: str, url: str, headers: dict, **kwargs
    ) -> httpx.Response:
        """Make an HTTP request with retry on rate limits (429)."""
        max_retries = 3
        response = None
        for attempt in range(max_retries):
            with httpx.Client(timeout=30) as client:
                response = client.request(method, url, headers=headers, **kwargs)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            retry_after = float(response.headers.get("Retry-After", 1))
            if attempt < max_retries - 1:
                time.sleep(retry_after + 1)
        assert response is not None
        response.raise_for_status()
        return response

    # ── Discord API calls ───────────────────────────────────────────────

    def _find_member(self, username: str) -> DiscordUser | None:
        """Find a guild member by username.

        Discord doesn't have a direct "search by username" endpoint for bots.
        We use the guild member search endpoint.
        """
        clean_username = username.split("#")[0].strip()

        url = f"{self.API_BASE}/guilds/{self.guild_id}/members/search"
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

        response = DiscordRoleAssigner._request_with_retry(
            "GET", url, headers, params={"query": clean_username, "limit": 10}
        )
        members = response.json()

        # Require exact username match — no partial/fallback matching
        # (false negative = human reviews it; false positive = wrong person gets role)
        for member in members:
            user = member.get("user", {})
            if user.get("username", "").lower() == clean_username.lower():
                return DiscordUser(
                    id=user["id"],
                    username=user["username"],
                    discriminator=user.get("discriminator", "0"),
                    nickname=member.get("nick"),
                )

        return None

    def _add_role(self, user_id: str, role_id: str) -> None:
        """Add a role to a guild member."""
        url = (
            f"{self.API_BASE}/guilds/{self.guild_id}/members/{user_id}/roles/{role_id}"
        )
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

        DiscordRoleAssigner._request_with_retry("PUT", url, headers)

    # ── validation ──────────────────────────────────────────────────────

    def validate_bot_permissions(self) -> dict:
        """Check that the bot has the required permissions."""
        url = f"{self.API_BASE}/guilds/{self.guild_id}/members/@me"
        headers = {"Authorization": f"Bot {self.bot_token}"}

        issues = []

        with httpx.Client(timeout=30) as client:
            try:
                response = DiscordRoleAssigner._request_with_retry("GET", url, headers)
                if response.status_code == 404:
                    issues.append(
                        "Bot is not in the server. Use the OAuth2 URL Generator "
                        "in Discord Developer Portal to invite it."
                    )
                elif response.status_code == 403:
                    issues.append(
                        "Bot lacks permissions or token is invalid."
                    )
                elif response.status_code == 200:
                    # Check role hierarchy
                    guild_url = f"{self.API_BASE}/guilds/{self.guild_id}"
                    guild_resp = DiscordRoleAssigner._request_with_retry(
                        "GET", guild_url, headers
                    )
                    if guild_resp.status_code == 200:
                        guild_data = guild_resp.json()
                        roles = guild_data.get("roles", [])
                        target_role = next(
                            (r for r in roles if r["id"] == self.verified_role_id),
                            None,
                        )
                        if target_role:
                            bot_role = next(
                                (
                                    r
                                    for r in roles
                                    if r.get("managed") and r.get("tags", {}).get("bot_id")
                                ),
                                None,
                            )
                            if bot_role and bot_role.get("position", -1) <= target_role.get(
                                "position", 0
                            ):
                                issues.append(
                                    "Bot's role is below the verified role in the "
                                    "hierarchy. Move the bot's role above it in "
                                    "Server Settings → Roles."
                                )
                        else:
                            issues.append(
                                f"Verified role ID '{self.verified_role_id}' "
                                "not found in server."
                            )
            except Exception as e:
                issues.append(f"Could not validate permissions: {e}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }
