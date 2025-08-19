import os
import threading
import time
from typing import Optional, List

from collector import collect_top_matches, DEFAULT_TIERS

class CollectorThread(threading.Thread):
    def __init__(self, interval_seconds: int, region: str = "kr",
                 players: int = 50, per_player: int = 10, tiers: List[str] = None):
        super().__init__(daemon=True)
        self.interval_seconds = interval_seconds
        self.region = region
        self.players = players
        self.per_player = per_player
        self.tiers = tiers or DEFAULT_TIERS
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                res = collect_top_matches(self.region, self.players, self.per_player, self.tiers)
                # 간단 로그 (stdout)
                print(f"[collector] matches={res['matches_fetched']} players={res['players_collected']} "
                      f"dur={res['duration_sec']}s tiers={','.join(self.tiers)}")
            except Exception as e:
                print(f"[collector] error: {e}")
            # stop-aware sleep
            for _ in range(self.interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

def start_scheduler_from_env() -> Optional[CollectorThread]:
    interval_env = os.getenv("COLLECT_INTERVAL_SEC", "").strip()
    if not interval_env:
        return None
    try:
        interval = int(interval_env)
    except ValueError:
        return None
    region = os.getenv("COLLECT_REGION", "kr")
    players = int(os.getenv("COLLECT_PLAYERS", "50"))
    per_player = int(os.getenv("COLLECT_PER_PLAYER", "10"))

    tiers_param = os.getenv("COLLECT_TIERS", "")
    if tiers_param.strip():
        tiers = [t.strip().lower() for t in tiers_param.split(",") if t.strip()]
    else:
        tiers = DEFAULT_TIERS

    t = CollectorThread(interval, region, players, per_player, tiers)
    t.start()
    return t
