from typing import Dict, List, Any, Set, Iterable
import time

from riot_client import (
    get_league_entries,
    get_summoner_by_id,
    get_summoner_by_puuid,   
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
            # 각 엔트리에 tier 주석
            for e in entries:
                e.setdefault("_tier", t.upper())
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

    existing_ids: Set[str] = load_existing_match_ids(MATCHES_JSONL)

    # 1) 최신 상위 리그(다중 tier) 목록
    entries = _iter_entries(platform_region, tiers)
    # TFT 응답은 leaguePoints가 없을 수도 있어 방어
    entries = sorted(entries, key=lambda e: e.get("leaguePoints", 0), reverse=True)[:max_players]

    # 2) PUUID 수집/캐시 + puuid->tier 매핑
    cached = {s.get("puuid"): s for s in load_summoners() if isinstance(s, dict) and s.get("puuid")}
    updated_cache: Dict[str, Any] = dict((s.get("puuid"), s) for s in load_summoners() if isinstance(s, dict) and s.get("puuid"))

    puuids: List[str] = []
    puuid_to_tier: Dict[str, str] = {}

    for e in entries:
        tier = (e.get("_tier") or e.get("tier") or "UNRANKED").upper()

        puuid = e.get("puuid")
        if not puuid:
            # 구형 응답에 summonerId만 있을 가능성에 대비(거의 없음)
            summoner_id = e.get("summonerId")
            if summoner_id:
                try:
                    sm = get_summoner_by_id(platform_region, summoner_id)
                    puuid = sm.get("puuid") if sm else None
                except Exception:
                    puuid = None

        if not puuid:
            continue

        # 이름 캐시 갱신(가능할 때만, 실패해도 진행)
        if puuid not in cached:
            try:
                sm = get_summoner_by_puuid(platform_region, puuid) or {}
            except Exception:
                sm = {}
            if sm:
                sm["tier"] = tier
                updated_cache[puuid] = sm
            else:
                # 최소한 tier만 기록하는 placeholder
                updated_cache.setdefault(puuid, {"puuid": puuid, "tier": tier})
        else:
            # tier 최신화
            try:
                updated_cache[puuid]["tier"] = tier
            except Exception:
                updated_cache[puuid] = {"puuid": puuid, "tier": tier}

        puuids.append(puuid)
        puuid_to_tier[puuid] = tier

    if updated_cache and (len(updated_cache) != len(cached) or any(
        (cached.get(k) or {}).get("tier") != (v or {}).get("tier") for k, v in updated_cache.items()
    )):
        # 딕셔너리를 리스트로 변환해 저장
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
            info = match.get("info", {}) or {}
            parts = info.get("participants", []) or []
            for p in parts:
                p_puuid = p.get("puuid")
                if p_puuid:
                    p["tier"] = puuid_to_tier.get(p_puuid, p.get("tier") or "UNRANKED")
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


