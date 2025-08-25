# 맨 위 import에 추가
from collections import Counter
from datetime import datetime, timezone, timedelta

# ...중략...

def _load_summoner_name_map():
    """puuid -> 표시용 이름 맵 (없으면 puuid 축약)"""
    name_map = {}
    try:
        for s in load_summoners():
            p = s.get("puuid")
            # TFT API에 따라 'name' 또는 'gameName'+'tagLine'이 있을 수 있음
            nm = s.get("name")
            if not nm:
                g = s.get("gameName")
                t = s.get("tagLine")
                if g and t:
                    nm = f"{g}#{t}"
            if p:
                name_map[p] = nm or (p[:8] + "…")
    except Exception:
        pass
    return name_map

def _summarize_match(match: dict, name_map: dict) -> dict:
    """한 매치를 사람이 읽기 좋은 요약으로 변환"""
    meta = match.get("metadata", {})
    info = match.get("info", {})
    mids = meta.get("match_id")
    t_ms = info.get("gameCreation") or 0
    parts = info.get("participants", []) or []

    # 참가자 티어 집계
    tiers = [ (p.get("tier") or "UNRANKED").upper() for p in parts ]
    c = Counter(tiers)
    # "CHALLENGER×3, MASTER×1" 형태로 표시
    tier_summary = ", ".join(f"{k}×{v}" for k, v in c.most_common())

    # 참가자 요약
    players = []
    for p in parts:
        puuid = p.get("puuid", "")
        name = name_map.get(puuid, puuid[:8] + "…")
        players.append({
            "name": name,
            "tier": (p.get("tier") or "UNRANKED").upper(),
            "placement": p.get("placement"),
            "augments": p.get("augments") or [],
            # 주 사용 특성 상위만 간결히 (style/num_units 기준 정렬)
            "top_traits": sorted(
                [
                    {
                        "name": tr.get("name"),
                        "tier_current": tr.get("tier_current"),
                        "num_units": tr.get("num_units"),
                    }
                    for tr in (p.get("traits") or [])
                ],
                key=lambda tr: (tr.get("tier_current") or 0, tr.get("num_units") or 0),
                reverse=True
            )[:3],
            # 대표 유닛 3개만 (별 등급 내림차순)
            "core_units": sorted(
                [
                    {
                        "name": u.get("character_id"),
                        "star": u.get("tier"),
                        "items": u.get("itemNames") or [],
                    }
                    for u in (p.get("units") or [])
                ],
                key=lambda u: (u.get("tier") or 0),
                reverse=True
            )[:3],
        })

    # KST ISO 문자열도 함께 제공(프론트에서 그대로 보여주기 편함)
    kst = timezone(timedelta(hours=9))
    iso_kst = datetime.fromtimestamp(t_ms / 1000, tz=kst).isoformat(timespec="seconds")

    return {
        "match_id": mids,
        "gameCreation": t_ms,
        "gameTimeKST": iso_kst,
        "tier_summary": tier_summary,
        "players": players,
    }

@app.route("/api/matches/summary")
def get_matches_summary():
    """
    매치 요약 리스트:
      - 최신순 정렬
      - 티어는 중복 집계(CHALLENGER×3 형태)
      - 참가자: 이름/티어/등수/augments/대표 traits/대표 유닛
    쿼리:
      - tier (선택): 특정 티어가 포함된 매치만
      - limit (선택): 기본 50
    """
    want_tier = (request.args.get("tier") or "").upper().strip()
    try:
        limit = max(1, min(200, int(request.args.get("limit", "50"))))
    except ValueError:
        limit = 50

    if not MATCHES_JSONL.exists():
        return jsonify({"matches": [], "total": 0})

    name_map = _load_summoner_name_map()

    matches = []
    try:
        with MATCHES_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    m = json.loads(line)
                    # tier 필터링: 참가자 중 하나라도 해당 티어이면 통과
                    if want_tier:
                        parts = (m.get("info", {}) or {}).get("participants", []) or []
                        if not any((p.get("tier") or "").upper() == want_tier for p in parts):
                            continue
                    matches.append(m)
                except Exception:
                    continue
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 최신순 정렬
    matches.sort(key=lambda m: (m.get("info", {}) or {}).get("gameCreation", 0), reverse=True)

    # 요약 변환 + limit
    out = [_summarize_match(m, name_map) for m in matches[:limit]]

    return jsonify({"matches": out, "total": len(matches)})


