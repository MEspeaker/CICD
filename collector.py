from typing import Dict, List, Any, Set, Iterable
import time
import sys

from riot_client import (
    get_league_entries,
    get_summoner_by_id,
    get_summoner_by_puuid,
    get_match_ids,
    get_match,
)
from storage import (
    append_jsonl,
    load_summoners,
    save_summoners,
    MATCHES_JSONL,
    load_existing_match_ids,
)

DEFAULT_TIERS: List[str] = ["challenger", "grandmaster", "master"]


def _iter_entries(platform_region: str, tiers: Iterable[str]) -> List[Dict[str, Any]]:
    """
    각 티어의 엔트리를 모아 합칩니다.
    TFT의 entries는 보통 puuid를 포함하며, summonerId가 없을 수 있습니다.
    """
    combined: List[Dict[str, Any]] = []
    for t in tiers:
        try:
            entries = get_league_entries(platform_region, t)
            # 각 엔트리에 tier 주석(대문자) 보장
            for e in entries:
                e.setdefault("_tier", t.upper())
            combined.extend(entries)
        except Exception as e:
            print(f"[collector] get_league_entries({t}) error: {e}", file=sys.stderr)
            continue
    return combined


def collect_top_matches(
    platform_region: str = "kr",
    max_players: int = 50,
    max_matches_per_player: int = 10,
    tiers: Iterable[str] = DEFAULT_TIERS,
) -> Dict[str, Any]:
    """
    상위 리그 플레이어들(puuid)을 가져와 최근 매치를 수집하고,
    해당 매치의 participants에 puuid 기반 tier 주석을 주입하여 저장합니다.
    """
    start = time.time()

    # 이미 저장된 match_id(중복 방지)
    existing_ids: Set[str] = load_existing_match_ids(MATCHES_JSONL)

    # 1) 최신 상위 리그(다중 tier) 목록
    tiers = [t.strip().lower() for t in tiers if t and t.strip()]
    entries = _iter_entries(platform_region, tiers)

    # leaguePoints 정렬(없으면 0) 후 상위 max_players로 슬라이스
    entries = sorted(entries, key=lambda e: e.get("leaguePoints", 0), reverse=True)[:max_players]

    # 2) PUUID 수집/캐시 + puuid->tier 매핑
    #    캐시는 puuid 키 기준으로 유지합니다.
    existing_cache_list = [s for s in load_summoners() if isinstance(s, dict)]
    cached_by_puuid: Dict[str, Dict[str, Any]] = {
        s.get("puuid"): s for s in existing_cache_list if s.get("puuid")
    }
    updated_cache: Dict[str, Dict[str, Any]] = dict(cached_by_puuid)

    puuids: List[str] = []
    puuid_to_tier: Dict[str, str] = {}

    added_players = 0
    for e in entries:
        tier = (e.get("_tier") or e.get("tier") or "UNRANKED").upper()

        puuid = e.get("puuid")
        if not puuid:
            # (보조) 구형 응답에 summonerId만 있을 가능성
            summoner_id = e.get("summonerId")
            if summoner_id:
                try:
                    sm = get_summoner_by_id(platform_region, summoner_id)
                    puuid = sm.get("puuid") if sm else None
                except Exception as ex:
                    print(f"[collector] get_summoner_by_id fail: {ex}", file=sys.stderr)
                    puuid = None

        if not puuid:
            # puuid가 없으면 이 엔트리는 건너뜁니다.
            continue

        # 이름/기타 필드 캐시 갱신(가능할 때만, 실패해도 진행)
        if puuid not in cached_by_puuid:
            try:
                sm = get_summoner_by_puuid(platform_region, puuid) or {}
            except Exception as ex:
                print(f"[collector] get_summoner_by_puuid fail: {ex}", file=sys.stderr)
                sm = {}

            if sm:
                sm["tier"] = tier
                updated_cache[puuid] = sm
                added_players += 1
            else:
                # 최소한 placeholder라도 보관하여 tier 갱신 반영
                updated_cache.setdefault(puuid, {"puuid": puuid, "tier": tier})
        else:
            # tier 최신화
            try:
                updated_cache[puuid]["tier"] = tier
            except Exception:
                updated_cache[puuid] = {"puuid": puuid, "tier": tier}

        puuids.append(puuid)
        puuid_to_tier[puuid] = tier

    # 캐시 변경이 있으면 저장
    if (len(updated_cache) != len(cached_by_puuid)) or any(
        (cached_by_puuid.get(k) or {}).get("tier") != (v or {}).get("tier")
        for k, v in updated_cache.items()
    ):
        try:
            save_summoners(list(updated_cache.values()))
        except Exception as e:
            print(f"[collector] save_summoners error: {e}", file=sys.stderr)

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
        except Exception as e:
            print(f"[collector] get_match_ids fail for {puuid[:8]}…: {e}", file=sys.stderr)
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
                    # 엔트리에서 수집한 puuid만이라도 확실히 주석 주입
                    p["tier"] = puuid_to_tier.get(p_puuid, (p.get("tier") or "UNRANKED"))
            match["info"] = info
            matches.append(match)
        except Exception as e:
            print(f"[collector] get_match fail {mid}: {e}", file=sys.stderr)
            continue

    if matches:
        try:
            append_jsonl(MATCHES_JSONL, matches)
        except Exception as e:
            print(f"[collector] append_jsonl error: {e}", file=sys.stderr)

    duration = round(time.time() - start, 2)
    print(
        f"[collector] tiers={','.join(tiers)} entries={len(entries)} "
        f"players={len(puuids)}(+{added_players}) new_matches={len(matches)} dur={duration}s"
    )

    return {
        "platform_region": platform_region,
        "tiers": [t for t in tiers],
        "players_collected": len(puuids),
        "matches_fetched": len(matches),
        "duration_sec": duration,
    }



