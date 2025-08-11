from typing import Dict, List, Any, Set
import time

from riot_client import (
    get_challenger_entries,
    get_summoner_by_id,
    get_match_ids,
    get_match,
)
from storage import append_jsonl, load_summoners, save_summoners, MATCHES_JSONL


def collect_top_matches(platform_region: str = "kr", max_players: int = 50, max_matches_per_player: int = 10) -> Dict[str, Any]:
    start = time.time()
    seen_match_ids: Set[str] = set()

    # 1) 최신 챌린저 목록
    entries = get_challenger_entries(platform_region)
    entries = sorted(entries, key=lambda e: e.get("leaguePoints", 0), reverse=True)[:max_players]

    # 2) 소환사 PUUID 수집/캐시
    cached = {s.get("id"): s for s in load_summoners()}
    updated_cache: Dict[str, Any] = dict(cached)

    puuids: List[str] = []
    for e in entries:
        summoner_id = e.get("summonerId")
        if not summoner_id:
            continue
        summoner = cached.get(summoner_id)
        if not summoner:
            summoner = get_summoner_by_id(platform_region, summoner_id) or {}
            if summoner:
                updated_cache[summoner_id] = summoner
        if summoner and summoner.get("puuid"):
            puuids.append(summoner["puuid"])

    if updated_cache != cached:
        save_summoners(list(updated_cache.values()))

    # 3) 각 플레이어 최근 매치 ID 가져오기
    all_new_match_ids: List[str] = []
    for puuid in puuids:
        try:
            ids = get_match_ids(platform_region, puuid, count=max_matches_per_player)
            for mid in ids:
                if mid not in seen_match_ids:
                    all_new_match_ids.append(mid)
                    seen_match_ids.add(mid)
        except Exception:
            continue

    # 4) 매치 상세 저장
    matches: List[Dict[str, Any]] = []
    for mid in all_new_match_ids:
        try:
            match = get_match(platform_region, mid)
            matches.append(match)
        except Exception:
            continue

    if matches:
        append_jsonl(MATCHES_JSONL, matches)

    return {
        "platform_region": platform_region,
        "players_collected": len(puuids),
        "matches_fetched": len(matches),
        "duration_sec": round(time.time() - start, 2),
    } 