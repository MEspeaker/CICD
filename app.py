from flask import Flask, jsonify, request, send_from_directory
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
import json
import os

# storage만은 모듈 로드시 바로 써도 안전
from storage import load_summoners, MATCHES_JSONL

app = Flask(__name__)

# --- 스케줄러 중복 기동 방지 (지연 임포트) ---
def _maybe_start_scheduler_once():
    if app.config.get("_SCHEDULER_STARTED"):
        return
    # 여기서 import (최상단에서 하지 않음: 연쇄 ImportError 방지)
    try:
        from scheduler import start_scheduler_from_env
    except Exception as e:
        app.logger.warning(f"[scheduler] import skipped: {e}")
        app.config["_SCHEDULER_STARTED"] = False
        app.config["_SCHEDULER_OBJ"] = None
        return

    t = start_scheduler_from_env()
    app.config["_SCHEDULER_STARTED"] = bool(t)
    app.config["_SCHEDULER_OBJ"] = t
    if t:
        app.logger.info(
            f"[scheduler] started: interval={t.interval_seconds}s region={t.region} "
            f"players={t.players} per_player={t.per_player} tiers={','.join(t.tiers)}"
        )
    else:
        app.logger.info("[scheduler] not started (COLLECT_INTERVAL_SEC not set)")

# --- 정적/루트 ---
@app.route("/")
def root():
    return send_from_directory("html", "index.html")

@app.route("/html/<path:filename>")
def static_html(filename: str):
    return send_from_directory("html", filename)

# --- 수동 수집 트리거 (지연 임포트) ---
@app.route("/collect", methods=["POST"])
def collect():
    # ⬇️ collector는 여기서 import (연쇄 ImportError 방지)
    from collector import collect_top_matches, DEFAULT_TIERS
    region = request.args.get("region", "kr")
    players = int(request.args.get("players", "15"))          # 기본값 안정화(15명)
    per_player = int(request.args.get("per_player", "3"))     # 기본 3매치
    tiers_param = request.args.get("tiers")
    tiers = DEFAULT_TIERS if not tiers_param else [t.strip().lower() for t in tiers_param.split(",") if t.strip()]
    result = collect_top_matches(region, players, per_player, tiers)
    return jsonify(result)

# --- 프론트용 API ---
@app.route("/api/tiers")
def get_tiers():
    """드롭다운에 사용할 티어 목록"""
    # ⬇️ 여기서 import (collector를 최상단에 두지 않음)
    try:
        from collector import DEFAULT_TIERS
        tiers = [t.upper() for t in DEFAULT_TIERS]
    except Exception:
        tiers = ["CHALLENGER", "GRANDMASTER", "MASTER"]  # 폴백
    return jsonify({"tiers": tiers})

@app.route("/api/summoners")
def get_summoners_api():
    """캐시된 소환사 목록(이름/PUUID/티어 등)"""
    return jsonify({"summoners": load_summoners()})

@app.route("/api/health")
def health():
    """상태 확인"""
    data_dir = Path(os.getenv("DATA_DIR", "data")).resolve()
    has_api_key = bool(os.getenv("RIOT_API_KEY"))
    return jsonify({
        "ok": True,
        "has_api_key": has_api_key,
        "data_dir": str(data_dir),
        "matches_file_exists": MATCHES_JSONL.exists(),
        "summoners_count": len(load_summoners())
    })

# --- 원시 데이터 제공 ---
@app.route("/api/matches")
def get_matches():
    """수집된 매치 데이터를 반환"""
    if not MATCHES_JSONL.exists():
        return jsonify({"matches": [], "total": 0})

    matches: List[Dict[str, Any]] = []
    try:
        with MATCHES_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        matches.append(json.loads(line))
                    except Exception:
                        continue
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"matches": matches, "total": len(matches)})

@app.route("/api/stats")
def get_stats():
    """수집된 데이터의 통계 정보를 반환"""
    stats = {
        "total_matches": 0,
        "total_summoners": 0,
        "matches_by_tier": {},
        "recent_collections": [],
        "last_updated": None,
    }

    # 소환사 수
    summoners = load_summoners()
    stats["total_summoners"] = len(summoners)

    # 매치 수 및 티어별 분석
    if MATCHES_JSONL.exists():
        try:
            with MATCHES_JSONL.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        match = json.loads(line)
                    except Exception:
                        continue
                    stats["total_matches"] += 1

                    # 티어 집계 (participants에 주입한 tier 사용)
                    info = match.get("info", {}) or {}
                    parts = info.get("participants", []) or []
                    for p in parts:
                        tier = (p.get("tier") or "UNRANKED").upper()
                        stats["matches_by_tier"][tier] = stats["matches_by_tier"].get(tier, 0) + 1

                    # 최근 업데이트 시간 (ms)
                    game_time = info.get("gameCreation")
                    if isinstance(game_time, int):
                        if not stats["last_updated"] or game_time > stats["last_updated"]:
                            stats["last_updated"] = game_time
        except Exception as e:
            stats["error"] = str(e)

    return jsonify(stats)

@app.route("/api/matches/by-tier/<tier>")
def get_matches_by_tier(tier: str):
    """특정 티어의 매치 데이터를 반환"""
    if not MATCHES_JSONL.exists():
        return jsonify({"matches": [], "total": 0, "tier": tier})

    want = tier.upper()
    matches: List[Dict[str, Any]] = []
    try:
        with MATCHES_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    match = json.loads(line)
                except Exception:
                    continue
                info = match.get("info", {}) or {}
                parts = info.get("participants", []) or []
                if any((p.get("tier") or "").upper() == want for p in parts):
                    matches.append(match)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"matches": matches, "total": len(matches), "tier": want})

# =========================
#   요약 엔드포인트 (신규)
# =========================

def _load_summoner_name_map() -> Dict[str, str]:
    """puuid -> 표시용 이름 맵 (없으면 puuid 축약)"""
    name_map: Dict[str, str] = {}
    try:
        for s in load_summoners():
            if not isinstance(s, dict):
                continue
            p = s.get("puuid")
            nm = s.get("name")
            if not nm:
                g = s.get("gameName")
                t = s.get("tagLine")
                if g and t:
                    nm = f"{g}#{t}"
            if p:
                name_map[p] = nm or (str(p)[:8] + "…")
    except Exception:
        pass
    return name_map

def _summarize_match(match: dict, name_map: dict) -> dict:
    meta = match.get("metadata", {}) or {}
    info = match.get("info", {}) or {}
    mids = meta.get("match_id")

    raw_ts = info.get("gameCreation")
    try:
        t_ms = int(raw_ts)
    except Exception:
        t_ms = 0

    parts = info.get("participants", []) or []

    # 티어 집계 (UNRANKED 제외)
    tiers = [ (p.get("tier") or "UNRANKED").upper() for p in parts ]
    c = Counter(t for t in tiers if t != "UNRANKED")
    tier_summary = ", ".join(f"{k}×{v}" for k, v in c.most_common()) or "티어 정보 없음"

    players = []
    for p in parts:
        puuid = p.get("puuid", "")
        name = name_map.get(puuid, (str(puuid)[:8] + "…") if puuid else "알 수 없음")
        # 전체 traits/units 준비
        all_traits = [
            {
                "name": tr.get("name"),
                "tier_current": tr.get("tier_current"),
                "num_units": tr.get("num_units"),
                "style": tr.get("style"),
            } for tr in (p.get("traits") or [])
        ]
        all_units = [
            {
                "name": u.get("character_id"),
                "star": u.get("tier"),
                "items": u.get("itemNames") or [],
            } for u in (p.get("units") or [])
        ]
        players.append({
            "name": name,
            "tier": (p.get("tier") or "UNRANKED").upper(),
            "placement": p.get("placement"),
            "augments": p.get("augments") or [],
            # 요약용 상위 3
            "top_traits": sorted(all_traits, key=lambda tr: (tr.get("tier_current") or 0, tr.get("num_units") or 0), reverse=True)[:3],
            "core_units": sorted(all_units, key=lambda u: (u.get("star") or 0), reverse=True)[:3],
            # 상세용 전체
            "traits": all_traits,
            "units": all_units,
        })

    # 시간 문자열 두 형태 (KST)
    kst = timezone(timedelta(hours=9))
    if t_ms > 0:
        dt = datetime.fromtimestamp(t_ms / 1000, tz=kst)
        game_time_kst_iso = dt.isoformat(timespec="seconds")          # 예: 2025-08-25T17:56:01+09:00
        game_time_kst_plain = dt.strftime("%Y-%m-%d %H:%M:%S")        # 예: 2025-08-25 17:56:01
    else:
        game_time_kst_iso = "알 수 없음"
        game_time_kst_plain = "알 수 없음"

    return {
        "match_id": mids,
        "gameCreation": t_ms,
        "gameTimeKST": game_time_kst_iso,
        "gameTimeKSTPlain": game_time_kst_plain,   # ← 프런트는 이걸 쓰면 +09:00 안 보입니다
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

    matches: List[Dict[str, Any]] = []
    try:
        with MATCHES_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if want_tier:
                    parts = (m.get("info", {}) or {}).get("participants", []) or []
                    if not any((p.get("tier") or "").upper() == want_tier for p in parts):
                        continue
                matches.append(m)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 최신순 정렬
    matches.sort(key=lambda m: (m.get("info", {}) or {}).get("gameCreation", 0), reverse=True)

    # 요약 변환 + limit
    out = [_summarize_match(m, name_map) for m in matches[:limit]]

    return jsonify({"matches": out, "total": len(matches)})

@app.route("/api/admin/backfill-names", methods=["POST"])
def backfill_names():
    """
    matches.jsonl에서 발견한 puuid 중, summoners.json에 이름이 비어 있는 항목을
    Riot API로 조회하여 이름을 채웁니다. (최대 limit명)
    사용 예: curl -X POST "https://.../api/admin/backfill-names?limit=30"
    """
    limit = int(request.args.get("limit", "30"))
    limit = max(1, min(100, limit))

    # 지연 임포트 (연쇄 ImportError 방지)
    try:
        from riot_client import get_summoner_by_puuid
        from storage import load_summoners, save_summoners
    except Exception as e:
        return jsonify({"ok": False, "error": f"import failed: {e}"}), 500

    # 현재 캐시 로드
    cache = { (s.get("puuid") or ""): s for s in (load_summoners() or []) if isinstance(s, dict) }
    need: List[str] = []

    # matches.jsonl에서 puuid 수집
    try:
        if MATCHES_JSONL.exists():
            with MATCHES_JSONL.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        m = json.loads(line)
                    except Exception:
                        continue
                    parts = (m.get("info", {}) or {}).get("participants", []) or []
                    for p in parts:
                        puuid = p.get("puuid")
                        if not puuid: continue
                        rec = cache.get(puuid)
                        has_name = bool(rec and (rec.get("name") or (rec.get("gameName") and rec.get("tagLine"))))
                        if not has_name and puuid not in need:
                            need.append(puuid)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    fetched = 0
    out_errors = []
    for puuid in need[:limit]:
        try:
            sm = get_summoner_by_puuid(request.args.get("region","kr") or "kr", puuid)
            if sm:
                # 캐시에 병합/저장
                old = cache.get(puuid) or {}
                old.update(sm)
                cache[puuid] = old
                fetched += 1
        except Exception as e:
            out_errors.append(str(e))

    # 저장
    try:
        from storage import save_summoners
        save_summoners(list(cache.values()))
    except Exception as e:
        out_errors.append(f"save_summoners: {e}")

    return jsonify({"ok": True, "attempted": min(limit, len(need)), "fetched": fetched, "errors": out_errors})


# --- 엔트리포인트 ---
if __name__ == "__main__":
    # 스케줄러 시작 (Flask 2.2+ 호환)
    with app.app_context():
        _maybe_start_scheduler_once()
    app.run(host="0.0.0.0", port=5000, use_reloader=False)



