"""Parse browser game URLs into API connection details."""

from urllib.parse import parse_qs, urlparse


def parse_game_url(url):
    """Extract base_url, game_id, and player_id from a browser game URL."""
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"not a valid URL: {url!r}")
    qs = parse_qs(parsed.query)
    game_id = (qs.get("game_id") or [None])[0]
    player_id = (qs.get("player_id") or [None])[0]
    if not game_id or not player_id:
        raise ValueError(
            "URL must include game_id and player_id query params "
            "(copy the link from your browser while in the game)"
        )
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return base_url, game_id, player_id
