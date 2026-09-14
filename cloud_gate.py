"""Ворота запуска для облачной рутины: пропускают прогрев только в один
псевдослучайный час в день, чтобы рутина не стартовала в одно и то же время
каждые сутки. Cron дёргает рутину каждый час в вечернем окне, а этот скрипт
решает, тот ли это час — тем же приёмом, что warmup_plan._rng выбирает
настроение дня: хэш от даты, а не системный random.

Код выхода 0 — сегодняшний час настал, можно запускать прогрев.
Код выхода 1 — не сегодняшний час, нормальный исход, выходим молча.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone

WINDOW_START_UTC = 12   # 15:00 МСК
WINDOW_END_UTC = 19     # 22:00 МСК, включительно


def target_hour(day: str) -> int:
    seed = hashlib.sha256(f"geelark-warmup-hour|{day}".encode()).hexdigest()
    span = WINDOW_END_UTC - WINDOW_START_UTC + 1
    return WINDOW_START_UTC + (int(seed[:8], 16) % span)


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    hour = target_hour(now.date().isoformat())
    if now.hour == hour:
        print(f"сегодняшний час настал: {hour:02d}:00 UTC")
        sys.exit(0)
    print(f"не мой час (сейчас {now.hour:02d}, сегодня выбран {hour:02d}) — выхожу")
    sys.exit(1)
