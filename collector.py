from typing import Dict, List, Any, Set, Iterable
import time
import sys

from riot_client import (
    get_league_entries,
    get_summoner_by_id,
    get_summoner_by_puuid,
    get_account_by_puuid,   # ★ 추가
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
    각 티어의 엔트리를 합칩니다.
    TFT entries는 보통 puuid를 포함하며, summonerId는 없을 수 있습니다.
    """
    combined: List[Dict[str, Any]] = []
    for t in tiers:
        try:
            entries = get_league_entries(platform_region, t)
            for e in entries:
                e.setdefault("_tier", t.upper())
            combined.extend(entries)
        except Exception as e:
            print(f"[collector] get_league_entries({t}) error: {e}", file=sys.stderr)
            continue
    return combined


def _enrich_summoner_record(platform_region: str, puuid: str) -> Dict[str, Any]:
    """
    puuid로 소환사 정보를 가져오되, name이 비어 있을 경우
    Riot Account API로 gameName/tagLine을 보강합니다.
    """
    sm: Dict[str, Any] = {}
    try:
        sm = get_summoner_by_puuid(platform_region, puuid) or {}
    except Exception as ex:
        print(f"[collector] get_summoner_by_puuid fail: {ex}", file=sys.stderr)
        sm = {}

    if not sm.get("name") and (not sm.get("gameName") or not sm.get("tagLine")):
        try:
            acct = get_account_by_puuid(platform_region, puuid) or {}
            # gameName/tagLine이 있으면 보강
            if acct.get("gameName") and acct.get("tagLine"):
                sm["gameName"] = acct["gameName"]
                sm["tagLine"]  = acct["tagLine"]
        except Exception as ex:
            print(f"[collector] get_account_by_puuid fail: {ex}", file=sys.stderr)

    # 최소 필드
    sm.setdefault("puuid", puuid)
    return sm


def collect_top_matches(
    platform_region: str = "kr",
    max_players: int = 50,
    max_matches_per_player: int = 10,
    tiers: Iterable[str] = DEFAULT_TIERS,
) -> Dict[str, Any]:
    """
    상위 리그 플레이어들(puuid)을 가져와 최근 매치를 수집하고,
    - participants에 puuid 기반 tier 주석 주입
    - info._collected_for = { puuid, tier } 주석 추가
    - 수집 대상 참가자엔 is_source=True 부여
    """
    start = time.time()

    # 이미 저장된 match_id(중복 방지)
    existing_ids: Set[str] = load_existing_match_ids(MATCHES_JSONL)

    # 1) 상위 리그(다중 tier) 목록 → LP 정렬 → 상위 max_players
    tiers_list = [t.strip().lower() for t in tiers if t and t.strip()]
    entries = _iter_entries(platform_region, tiers_list)
    entries = sorted(entries, key=lambda e: e.get("leaguePoints", 0), reverse=True)[:max_players]

    # 2) PUUID 수집/캐시 + puuid->tier 매핑
    existing_cache_list = [s for s in load_summoners() if isinstance(s, dict)]
    cached_by_puuid: Dict[str, Dict[str, Any]] = {s.get("puuid"): s for s in existing_cache_list if s.get("puuid")}
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
                    sm_id = get_summoner_by_id(platform_region, summoner_id)
                    puuid = sm_id.get("puuid") if sm_id else None
                except Exception as ex:
                    print(f"[collector] get_summoner_by_id fail: {ex}", file=sys.stderr)
                    puuid = None

        if not puuid:
            continue

        # 캐시 갱신 (실제 닉네임 보강)
        if puuid not in cached_by_puuid:
            sm = _enrich_summoner_record(platform_region, puuid)
            if sm:
                sm["tier"] = tier
                updated_cache[puuid] = sm
                added_players += 1
            else:
                updated_cache.setdefault(puuid, {"puuid": puuid, "tier": tier})
        else:
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

    # 3) 각 플레이어 최근 매치 ID 가져오기 (매치의 '수집원' 추적)
    all_new_match_ids: List[str] = []
    seen_this_run: Set[str] = set()
    mid_source: Dict[str, str] = {}  # match_id -> source puuid

    for puuid in puuids:
        try:
            ids = get_match_ids(platform_region, puuid, count=max_matches_per_player)
            for mid in ids:
                if (mid not in existing_ids) and (mid not in seen_this_run):
                    all_new_match_ids.append(mid)
                    seen_this_run.add(mid)
                    mid_source[mid] = puuid
        except Exception as e:
            print(f"[collector] get_match_ids fail for {puuid[:8]}…: {e}", file=sys.stderr)
            continue

    # 4) 매치 상세 저장 (participants tier 주석 + 수집원 주석)
    matches: List[Dict[str, Any]] = []
    for mid in all_new_match_ids:
        try:
            match = get_match(platform_region, mid)
            info = match.get("info", {}) or {}
            parts = info.get("participants", []) or []

            src_puuid = mid_source.get(mid)
            src_tier = puuid_to_tier.get(src_puuid, "UNRANKED") if src_puuid else None
            info["_collected_for"] = {"puuid": src_puuid, "tier": src_tier}

            for p in parts:
                p_puuid = p.get("puuid")
                if p_puuid:
                    p["tier"] = puuid_to_tier.get(p_puuid, (p.get("tier") or "UNRANKED"))
                    if src_puuid and p_puuid == src_puuid:
                        p["is_source"] = True

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
        f"[collector] tiers={','.join(tiers_list)} entries={len(entries)} "
        f"players={len(puuids)}(+{added_players}) new_matches={len(matches)} dur={duration}s"
    )

    return {
        "platform_region": platform_region,
        "tiers": [t for t in tiers_list],
        "players_collected": len(puuids),
        "matches_fetched": len(matches),
        "duration_sec": duration,
    }




