#!/usr/bin/env python3
"""Mission skill for Claude Code - handles mission-based authorization."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

MISSION_AUTHORITY_URL = os.getenv(
    "MISSION_AUTHORITY_URL",
    "http://localhost:8001"
)

WIKI_URL = os.getenv(
    "WIKI_URL",
    "http://localhost:8002"
)

@click.group()
def cli():
    """Mission skill - request and use missions for authorized agent actions."""
    pass


@cli.command()
@click.option("--task", required=True, help="Natural language description of the task")
@click.option("--scope", multiple=True, required=True, help="Permissions needed (repeatable)")
@click.option("--duration-hours", type=int, default=1, help="Mission duration in hours")
def request(task: str, scope: tuple[str, ...], duration_hours: int):
    """Request a mission from Mission Authority.

    Example:
        /mission request --task "Read AI safety wiki" --scope wiki_read --duration-hours 2
    """
    # Get agent SPIFFE ID (from environment or default)
    agent_id = _get_agent_spiffe_id()

    # Request mission
    mission_data = {
        "mission_text": task,
        "agent_id": agent_id,
        "scope": list(scope),
        "duration_hours": duration_hours
    }

    click.echo(f"Requesting mission from {MISSION_AUTHORITY_URL}...")
    result = _call_api("POST", "/missions", data=mission_data)

    mission_id = result["mission_id"]

    click.echo(f"✓ Mission requested: {mission_id}")
    click.echo(f"  Task: {task}")
    click.echo(f"  Scope: {', '.join(scope)}")
    click.echo(f"  Duration: {duration_hours} hours")
    click.echo()
    click.echo("Next steps:")
    click.echo(f"  1. Approve: python mock_mission_authority.py approve {mission_id}")
    click.echo(f"  2. Check status: python ~/.claude/skills/mission/skill.py status --id {mission_id}")
    click.echo(f"  3. Use mission: python ~/.claude/skills/mission/skill.py exchange --id {mission_id} --resource wiki")

    # Save mission ID for later use
    _save_mission_id(mission_id)


@cli.command()
@click.option("--id", "mission_id", help="Mission ID (uses last if not specified)")
def status(mission_id: Optional[str]):
    """Check mission status.

    Example:
        /mission status
        /mission status --id M-20260618-001
    """
    if not mission_id:
        mission_id = _load_mission_id()

    result = _call_api("GET", f"/missions/{mission_id}")

    click.echo(f"Mission: {mission_id}")
    click.echo(f"  Status: {result['status']}")
    click.echo(f"  Task: {result['mission_text']}")

    if result['status'] == 'active':
        click.echo(f"  ✓ Approved by: {result.get('approver_id', 'N/A')}")
        click.echo(f"  Expires: {result.get('expires_at', 'N/A')}")
        click.echo()
        click.echo("Mission is ready to use!")
        click.echo(f"  Exchange token: python ~/.claude/skills/mission/skill.py exchange --id {mission_id} --resource wiki")
    elif result['status'] == 'pending':
        click.echo()
        click.echo("⏳ Waiting for approval")
        click.echo(f"  Approve: python mock_mission_authority.py approve {mission_id}")
    elif result['status'] == 'canceled':
        click.echo()
        click.echo("❌ Mission was canceled")
    elif result['status'] == 'expired':
        click.echo()
        click.echo("⏰ Mission expired")


@cli.command()
@click.option("--id", "mission_id", help="Mission ID (uses last if not specified)")
@click.option("--resource", required=True, help="Resource to access (e.g., wiki)")
@click.option("--scope", help="Specific scope (e.g., wiki_read)")
def exchange(mission_id: Optional[str], resource: str, scope: Optional[str]):
    """Exchange mission token for access token.

    Example:
        /mission exchange --resource wiki --scope wiki_read
    """
    if not mission_id:
        mission_id = _load_mission_id()

    # Get mission token (from Mission Authority after approval)
    mission_token = _get_mission_token(mission_id)

    # Exchange for access token
    exchange_data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": mission_token,
        "resource": resource,
        "scope": scope or f"{resource}_read"
    }

    result = _call_api("POST", "/token-exchange", data=exchange_data)

    access_token = result["access_token"]
    expires_in = result["expires_in"]

    click.echo(f"✓ Access token obtained for {resource}")
    click.echo(f"  Scope: {result['scope']}")
    click.echo(f"  Expires in: {expires_in // 3600} hours")

    # Save access token for wiki operations
    _save_access_token(resource, access_token)

    click.echo()
    click.echo("Token saved! You can now use wiki commands:")
    click.echo("  Example: python ~/.claude/skills/mission/skill.py read-wiki --topic ai-safety")


@cli.command()
@click.option("--topic", required=True, help="Wiki topic to read")
def read_wiki(topic: str):
    """Read wiki content using mission access token.

    Example:
        /mission read-wiki --topic ai-safety
    """
    # Get wiki access token
    access_token = _load_access_token("wiki")
    if not access_token:
        click.echo("❌ No wiki access token. Run exchange command first")
        sys.exit(1)

    # Call wiki API
    click.echo(f"Reading wiki topic '{topic}' from {WIKI_URL}...")

    result = _call_api(
        "GET",
        f"/topics/{topic}/pages",
        base_url=WIKI_URL,
        token=access_token
    )

    click.echo(f"✓ Read wiki topic: {topic}")
    click.echo(f"  Pages found: {len(result.get('pages', []))}")
    click.echo()

    # Display page titles
    for page in result.get('pages', []):
        click.echo(f"  • {page['title']}")

    # Save content for agent to use
    _save_wiki_content(topic, result)
    click.echo()
    click.echo(f"Content saved to ~/.claude/cache/wiki-{topic}.json")


# Helper functions

def _get_agent_spiffe_id() -> str:
    """Get agent SPIFFE ID from environment or use default."""
    spiffe_id = os.getenv("SPIFFE_ID")
    if spiffe_id:
        return spiffe_id

    # Fallback for development
    return "spiffe://cluster.local/ns/default/sa/claude-code"


def _get_mission_token(mission_id: str) -> str:
    """Get mission token for approved mission."""
    # Mission token is stored after approval
    token_file = Path.home() / ".claude" / "missions" / f"{mission_id}.token"

    if not token_file.exists():
        click.echo(f"❌ Mission token not found: {token_file}", err=True)
        click.echo("Mission must be approved first", err=True)
        sys.exit(1)

    return token_file.read_text().strip()


def _call_api(method: str, path: str, base_url: str = None, data: dict = None, token: str = None) -> dict:
    """Call API endpoint (Mission Authority or Wiki)."""
    import urllib.request
    import urllib.error

    if base_url is None:
        base_url = MISSION_AUTHORITY_URL

    url = f"{base_url}{path}"

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req_data = json.dumps(data).encode() if data else None
    request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        click.echo(f"❌ API error ({e.code}): {error_body}", err=True)
        sys.exit(1)
    except urllib.error.URLError as e:
        click.echo(f"❌ Connection error: {e.reason}", err=True)
        click.echo(f"   Make sure the service is running at {base_url}", err=True)
        sys.exit(1)


def _save_mission_id(mission_id: str):
    """Save mission ID for later use."""
    cache_dir = Path.home() / ".claude" / "missions"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "last_mission.txt").write_text(mission_id)


def _load_mission_id() -> str:
    """Load last mission ID."""
    mission_file = Path.home() / ".claude" / "missions" / "last_mission.txt"
    if not mission_file.exists():
        click.echo("❌ No mission found. Create one with: request command", err=True)
        sys.exit(1)
    return mission_file.read_text().strip()


def _save_access_token(resource: str, token: str):
    """Save access token for resource."""
    cache_dir = Path.home() / ".claude" / "missions"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{resource}_token.txt").write_text(token)


def _load_access_token(resource: str) -> Optional[str]:
    """Load access token for resource."""
    token_file = Path.home() / ".claude" / "missions" / f"{resource}_token.txt"
    if not token_file.exists():
        return None
    return token_file.read_text().strip()


def _save_wiki_content(topic: str, content: dict):
    """Save wiki content for agent to use."""
    cache_dir = Path.home() / ".claude" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"wiki-{topic}.json").write_text(json.dumps(content, indent=2))


if __name__ == "__main__":
    cli()
