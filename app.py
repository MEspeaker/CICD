from flask import Flask, jsonify, request, send_from_directory
from collector import collect_top_matches
from scheduler import start_scheduler_from_env

app = Flask(__name__)


@app.route("/")
def root():
    return "TFT Tracker is running"


@app.route("/collect", methods=["POST"])  # trigger manual collection
def collect():
    region = request.args.get("region", "kr")
    players = int(request.args.get("players", "50"))
    per_player = int(request.args.get("per_player", "10"))
    result = collect_top_matches(region, players, per_player)
    return jsonify(result)


@app.route("/html/<path:filename>")
def static_html(filename: str):
    return send_from_directory("html", filename)


if __name__ == "__main__":
    # 환경변수로 COLLECT_INTERVAL_SEC이 지정되면 백그라운드 수집 시작
    start_scheduler_from_env()
    app.run(host="0.0.0.0", port=5000)
