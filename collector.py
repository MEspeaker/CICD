from typing import Dict, List, Any, Set, Iterable
import time

from riot_client import (
    get_league_entries,
    get_summoner_by_id,
    get_match_ids,
    get_match,
)
from storage import append_jsonl, load_summoners, save_summoners, MATCHES_JSONL, load_existing_match_ids

DEFAULT_TIERS: List[str] = ["challenger", "grandmaster", "master"]

def _iter_entries(platform_region: str, tiers: Iterable[str]) -> List[Dict[str, Any]]:
    combined: List[Dict[str, Any]] = []
    for t in tiers:
        try:
            entries = get_league_entries(platform_region, t)
            combined.extend(entries)
        except Exception:
            continue
    return combined

def collect_top_matches(
    platform_region: str = "kr",
    max_players: int = 50,
    max_matches_per_player: int = 10,
    tiers: Iterable[str] = DEFAULT_TIERS,
) -> Dict[str, Any]:
    start = time.time()

    # 기존 저장된 match_id 중복 방지
    existing_ids: Set[str] = load_existing_match_ids(MATCHES_JSONL)

    # 1) 최신 상위 리그(다중 tier) 목록
    entries = _iter_entries(platform_region, tiers)
    entries = sorted(entries, key=lambda e: e.get("leaguePoints", 0), reverse=True)[:max_players]

    # 2) 소환사 PUUID 수집/캐시 + puuid->tier 매핑 + summoner tier 갱신
    cached_by_id = {s.get("id"): s for s in load_summoners()}
    updated_cache: Dict[str, Any] = dict(cached_by_id)

    puuids: List[str] = []
    puuid_to_tier: Dict[str, str] = {}

    for e in entries:
        summoner_id = e.get("summonerId")
        if not summoner_id:
            continue

        tier = (e.get("_tier") or e.get("tier") or "UNRANKED").upper()

        summoner = cached_by_id.get(summoner_id)
        if not summoner:
            summoner = get_summoner_by_id(platform_region, summoner_id) or {}
            if summoner:
                # tier 주입
                summoner["tier"] = tier
                updated_cache[summoner_id] = summoner
        else:
            # tier 최신화
            if tier:
                summoner["tier"] = tier
                updated_cache[summoner_id] = summoner

        if summoner and summoner.get("puuid"):
            puuids.append(summoner["puuid"])
            puuid_to_tier[summoner["puuid"]] = tier

    if updated_cache != cached_by_id:
        # 리스트로 저장
        save_summoners(list(updated_cache.values()))

    # 3) 각 플레이어 최근 매치 ID 가져오기
    all_new_match_ids: List[str] = []
    seen_this_run: Set[str] = set()

    for puuid in puuids:
        try:
            ids = get_match_ids(platform_region, puuid, count=max_matches_per_player)
            for mid in ids:
                if (mid not in existing_ids) and (mid not in seen_this_run):
                    all_new_match_ids.append(mid)
                    seen_this_run.add(mid)
        except Exception:
            continue

    # 4) 매치 상세 저장 (participants에 tier 주석)
    matches: List[Dict[str, Any]] = []
    for mid in all_new_match_ids:
        try:
            match = get_match(platform_region, mid)
            info = match.get("info", {})
            parts = info.get("participants", [])
            for p in parts:
                puuid = p.get("puuid")
                if puuid:
                    p["tier"] = puuid_to_tier.get(puuid, "UNRANKED")
            match["info"] = info
            matches.append(match)
        except Exception:
            continue

    if matches:
        append_jsonl(MATCHES_JSONL, matches)

    return {
        "platform_region": platform_region,
        "tiers": [t for t in tiers],
        "players_collected": len(puuids),
        "matches_fetched": len(matches),
        "duration_sec": round(time.time() - start, 2),
    }
