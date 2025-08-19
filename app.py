from flask import Flask, jsonify, request, send_from_directory
from collector import collect_top_matches, DEFAULT_TIERS
from scheduler import start_scheduler_from_env
from storage import load_summoners, MATCHES_JSONL
from pathlib import Path
import json
import os

app = Flask(__name__)

# --- 스케줄러 중복 기동 방지 ---
def _maybe_start_scheduler_once():
    if app.config.get("_SCHEDULER_STARTED"):
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

@app.before_first_request
def _boot_scheduler():
    _maybe_start_scheduler_once()

# --- 정적/루트 ---
@app.route("/")
def root():
    return send_from_directory("html", "index.html")

@app.route("/html/<path:filename>")
def static_html(filename: str):
    return send_from_directory("html", filename)

# --- 수동 수집 트리거 ---
@app.route("/collect", methods=["POST"])
def collect():
    region = request.args.get("region", "kr")
    players = int(request.args.get("players", "50"))
    per_player = int(request.args.get("per_player", "10"))
    tiers_param = request.args.get("tiers")
    tiers = DEFAULT_TIERS if not tiers_param else [t.strip().lower() for t in tiers_param.split(",") if t.strip()]
    result = collect_top_matches(region, players, per_player, tiers)
    return jsonify(result)

# --- 프론트용 API ---
@app.route("/api/tiers")
def get_tiers():
    """드롭다운에 사용할 티어 목록"""
    return jsonify({"tiers": [t.upper() for t in DEFAULT_TIERS]})

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

# --- 데이터 제공 ---
@app.route("/api/matches")
def get_matches():
    """수집된 매치 데이터를 반환"""
    if not MATCHES_JSONL.exists():
        return jsonify({"matches": [], "total": 0})

    matches = []
    try:
        with MATCHES_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    matches.append(json.loads(line))
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
                    match = json.loads(line)
                    stats["total_matches"] += 1

                    # 티어 집계 (participants에 주입한 tier 사용)
                    info = match.get("info", {})
                    parts = info.get("participants", [])
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
    matches = []
    try:
        with MATCHES_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                match = json.loads(line)
                info = match.get("info", {})
                parts = info.get("participants", [])
                if any((p.get("tier") or "").upper() == want for p in parts):
                    matches.append(match)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"matches": matches, "total": len(matches), "tier": want})

if __name__ == "__main__":
    # 개발 서버에서 리로더로 인한 중복 기동 방지
    _maybe_start_scheduler_once()
    app.run(host="0.0.0.0", port=5000, use_reloader=False)

