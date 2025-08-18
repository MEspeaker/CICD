from flask import Flask, jsonify, request, send_from_directory
from collector import collect_top_matches, DEFAULT_TIERS
from scheduler import start_scheduler_from_env
from storage import load_summoners, MATCHES_JSONL
import json
import os
from pathlib import Path

app = Flask(__name__)


@app.route("/")
def root():
    return send_from_directory("html", "index.html")


@app.route("/collect", methods=["POST"])  # trigger manual collection
def collect():
    region = request.args.get("region", "kr")
    players = int(request.args.get("players", "50"))
    per_player = int(request.args.get("per_player", "10"))
    tiers_param = request.args.get("tiers")
    tiers = DEFAULT_TIERS if not tiers_param else [t.strip().lower() for t in tiers_param.split(",") if t.strip()]
    result = collect_top_matches(region, players, per_player, tiers)
    return jsonify(result)


@app.route("/html/<path:filename>")
def static_html(filename: str):
    return send_from_directory("html", filename)


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
        "last_updated": None
    }
    
    # 소환사 수
    summoners = load_summoners()
    stats["total_summoners"] = len(summoners)
    
    # 매치 수 및 티어별 분석
    if MATCHES_JSONL.exists():
        try:
            with MATCHES_JSONL.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        match = json.loads(line)
                        stats["total_matches"] += 1
                        
                        # 매치 참가자들의 티어 정보 분석
                        if "info" in match and "participants" in match["info"]:
                            for participant in match["info"]["participants"]:
                                tier = participant.get("tier", "UNRANKED")
                                if tier in stats["matches_by_tier"]:
                                    stats["matches_by_tier"][tier] += 1
                                else:
                                    stats["matches_by_tier"][tier] = 1
                        
                        # 최근 수집 시간 업데이트
                        if "gameCreation" in match.get("info", {}):
                            game_time = match["info"]["gameCreation"]
                            if not stats["last_updated"] or game_time > stats["last_updated"]:
                                stats["last_updated"] = game_time
        except Exception as e:
            stats["error"] = str(e)
    
    return jsonify(stats)


@app.route("/api/matches/by-tier/<tier>")
def get_matches_by_tier(tier: str):
    """특정 티어의 매치 데이터를 반환"""
    if not MATCHES_JSONL.exists():
        return jsonify({"matches": [], "total": 0})
    
    matches = []
    try:
        with MATCHES_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    match = json.loads(line)
                    # 매치에서 해당 티어 플레이어가 있는지 확인
                    if "info" in match and "participants" in match["info"]:
                        has_tier = any(
                            participant.get("tier", "").upper() == tier.upper()
                            for participant in match["info"]["participants"]
                        )
                        if has_tier:
                            matches.append(match)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    return jsonify({"matches": matches, "total": len(matches), "tier": tier})


if __name__ == "__main__":
    # 환경변수로 COLLECT_INTERVAL_SEC이 지정되면 백그라운드 수집 시작
    start_scheduler_from_env()
    app.run(host="0.0.0.0", port=5000)
