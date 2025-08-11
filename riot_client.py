import os
from typing import Any, Dict, List, Optional

import requests
from rate_limiter import get_global_limiter


def _get_api_key() -> str:
    api_key = os.getenv("RIOT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing RIOT_API_KEY environment variable")
    return api_key


def get_regional_routing(platform_region: str) -> str:
    region = platform_region.lower()
    americas = {"na", "na1", "br", "br1", "lan", "la1", "las", "la2", "oc1"}
    europe = {"euw", "euw1", "eune", "eun1", "tr", "tr1", "ru"}
    asia = {"kr", "jp", "jp1", "kr"}

    if region in americas:
        return "americas"
    if region in europe:
        return "europe"
    return "asia"


def _headers() -> Dict[str, str]:
    return {"X-Riot-Token": _get_api_key()}


def _limited_get(url: str, **kwargs):
    limiter = get_global_limiter()
    limiter.acquire()
    return requests.get(url, **kwargs)


# --- League entries by tier ---
SUPPORTED_LEAGUE_TIERS = {"challenger", "grandmaster", "master"}


def get_league_entries(platform_region: str, tier: str) -> List[Dict[str, Any]]:
    t = tier.lower().strip()
    if t not in SUPPORTED_LEAGUE_TIERS:
        raise ValueError(f"Unsupported tier: {tier}")
    url = f"https://{platform_region}.api.riotgames.com/tft/league/v1/{t}"
    resp = _limited_get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    entries = data.get("entries", [])
    # annotate tier for convenience
    for e in entries:
        e.setdefault("_tier", t.upper())
    return entries


# --- Legacy helpers for backward compatibility ---

def get_challenger_entries(platform_region: str) -> List[Dict[str, Any]]:
    return get_league_entries(platform_region, "challenger")


def get_summoner_by_id(platform_region: str, encrypted_summoner_id: str) -> Optional[Dict[str, Any]]:
    url = (
        f"https://{platform_region}.api.riotgames.com/tft/summoner/v1/summoners/{encrypted_summoner_id}"
    )
    resp = _limited_get(url, headers=_headers(), timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def get_match_ids(platform_region: str, puuid: str, count: int = 20) -> List[str]:
    regional = get_regional_routing(platform_region)
    url = (
        f"https://{regional}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids"
    )
    resp = _limited_get(url, headers=_headers(), params={"count": count}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_match(platform_region: str, match_id: str) -> Dict[str, Any]:
    regional = get_regional_routing(platform_region)
    url = f"https://{regional}.api.riotgames.com/tft/match/v1/matches/{match_id}"
    resp = _limited_get(url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json() 