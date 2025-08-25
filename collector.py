from typing import Dict, List, Any, Set, Iterable, Optional
import time

from riot_client import (
    get_league_entries,
    get_summoner_by_id,       # 레거시 대비 유지
    get_summoner_by_puuid,    # ★ 신규
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
        except Exception as e:
            # 진단 가시화
            print(f"[entries] tier={t} failed: {e}")
            continue
    return combined


def collect_top_matches(
    platform_region: str = "kr",
    max_players: int = 15,
    max_matches_per_player: int = 3,
    tiers: Iterable[str] = DEFAULT_TIERS,
) -> Dict[str, Any]:
    start = time.time()

    # 기존 저장된 match_id 중복 방지
    existing_ids: Set[str] = load_existing_match_ids(MATCHES_JSONL)

    # 1) 최신 상위 리그(다중 tier) 목록
    entries = _iter_entries(platform_region, tiers)
    # TFT 리그 엔트리는 puuid 기준이므로 leaguePoints 정렬 유지
    entries = sorted(entries, key=lambda e: e.get("leaguePoints", 0), reverse=True)[:max_players]

    # 2) 소환사 PUUID 수집/캐시 + puuid->tier 매핑 + summoner 캐시 갱신
    prev_summoners = load_summoners()
    # id/puuid 기준의 빠른 조회용 캐시
    cached_by_id: Dict[str, Dict[str, Any]] = {}
    cached_by_puuid: Dict[str, Dict[str, Any]] = {}
    for s in prev_summoners:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        sp = s.get("puuid")
        if sid:
            cached_by_id[sid] = s
        if sp:
            cached_by_puuid[sp] = s

    puuids: List[str] = []
    puuid_to_tier: Dict[str, str] = {}

    for e in entries:
        tier = (e.get("_tier") or e.get("tier") or "UNRANKED").upper()

        # ★ TFT: 리그 엔트리에서 puuid가 온다
        puuid = e.get("puuid")
        if puuid:
            puuids.append(puuid)
            puuid_to_tier[puuid] = tier

            # 캐시에 없으면 상세 조회(이름 등) 후 저장
            if puuid not in cached_by_puuid:
                try:
                    summoner = get_summoner_by_puuid(platform_region, puuid)
                    if summoner:
                        summoner["tier"] = tier
                        cached_by_puuid[puuid] = summoner
                except Exception as ex:
                    print(f"[summoner] by-puuid failed puuid={puuid[:10]}..: {ex}")
            else:
                # 티어 최신화
                cached_by_puuid[puuid]["tier"] = tier
            continue

        # 레거시: summonerId만 있는 경우(LoL식)
        summoner_id = e.get("summonerId")
        if summoner_id:
            summoner = cached_by_id.get(summoner_id)
            if not summoner:
                try:
                    summoner = get_summoner_by_id(platform_region, summoner_id) or {}
                except Exception as ex:
                    print(f"[summoner] by-id failed id={summoner_id[:10]}..: {ex}")
                    summoner = {}
            if summoner and summoner.get("puuid"):
                p = summoner["puuid"]
                puuids.append(p)
                puuid_to_tier[p] = tier
                summoner["tier"] = tier
                cached_by_id[summoner_id] = summoner
                cached_by_puuid[p] = summoner

    # 캐시 저장(중복 제거)
    # puuid 우선키로 합치고, 없으면 id로 대체
    uniq: Dict[str, Dict[str, Any]] = {}
    for s in list(cached_by_puuid.values()) + list(cached_by_id.values()):
        if not s:
            continue
        key = s.get("puuid") or s.get("id")
        if key and key not in uniq:
            uniq[key] = s
    if uniq:
        try:
            save_summoners(list(uniq.values()))
        except Exception as ex:
            print(f"[cache] save_summoners failed: {ex}")

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
        except Exception as ex:
            print(f"[match_ids] puuid={puuid[:10]}.. failed: {ex}")
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
                    p["tier"] = puuid_to_tier.get(p_puuid, "UNRANKED")
            match["info"] = info
            matches.append(match)
        except Exception as ex:
            print(f"[match] fetch failed mid={mid}: {ex}")
            continue

    if matches:
        try:
            append_jsonl(MATCHES_JSONL, matches)
        except Exception as ex:
            print(f"[storage] append_jsonl failed: {ex}")

    return {
        "platform_region": platform_region,
        "tiers": [t for t in tiers],
        "players_collected": len(puuids),
        "matches_fetched": len(matches),
        "duration_sec": round(time.time() - start, 2),
    }

