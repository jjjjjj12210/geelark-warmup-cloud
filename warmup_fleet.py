"""Прогрев всего парка: обходит телефоны по очереди, каждому свой сеанс.

Почему по очереди, а не разом. Девять аккаунтов, одновременно проснувшихся в
одну и ту же минуту и одинаково полиставших ленту, — это ровно тот почерк, от
которого мы уходим. Порядок телефонов перемешивается, между сеансами случайная
пауза, длительность каждого сеанса своя (см. warmup.py).

Телефон поднимается только на время своего сеанса и сразу гасится: минуты
идут на каждый работающий телефон, держать весь парк включённым ради одного
активного — впустую.

    .venv-adb/bin/python warmup_fleet.py                 # один круг по всем
    .venv-adb/bin/python warmup_fleet.py --range 2-6     # свои границы сеанса
    .venv-adb/bin/python warmup_fleet.py --gap 3-12      # паузы между телефонами
    .venv-adb/bin/python warmup_fleet.py --only BR-03,BR-07
"""
from __future__ import annotations

import argparse
import json
from datetime import date
import random
import subprocess
import sys
import time
from pathlib import Path

import geo_check
import gl_api
import gl_device
import warmup_plan

HERE = Path(__file__).parent
_VENV_PY = HERE / ".venv-adb" / "bin" / "python"
# Локальный venv есть только на Mac. В облаке (или где угодно без него)
# используем тот же интерпретатор, которым запущен сам оркестратор —
# каким бы он ни был, у него уже есть зависимости, раз этот файл выполняется.
PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def start(phone_id: str) -> bool:
    gl_api.post("/open/v1/phone/start", {"ids": [phone_id], "energySavingMode": 1})
    for _ in range(14):
        st = gl_api.post("/open/v1/phone/status", {"ids": [phone_id]})["data"]["successDetails"][0]
        if st["status"] == 0:
            gl_api.post("/open/v1/adb/setStatus", {"ids": [phone_id], "open": True})
            time.sleep(5)
            return True
        time.sleep(15)
    return False


def stop(phone_id: str) -> bool:
    """Остановить телефон, не сдаваясь при первой сетевой ошибке.

    Незакрытый телефон продолжает тарифицироваться. Полагаться на
    энергосбережение GeeLark нельзя: 31.08 BR-05 остался включённым после
    обрыва связи и прожёг ~330 минут, хотя energySavingMode был включён —
    похоже, живое ADB-подключение считается активностью."""
    for attempt in range(1, 4):
        try:
            gl_api.post("/open/v1/phone/stop", {"ids": [phone_id]})
            return True
        except Exception as e:
            log(f"  не удалось погасить (попытка {attempt}/3): {e}")
            time.sleep(3 * attempt)
    return False


def stop_all(ids: list[str]) -> None:
    """Последняя страховка: гасим всё, что могло остаться включённым."""
    try:
        st = gl_api.post("/open/v1/phone/status", {"ids": ids})["data"]["successDetails"]
        running = [s["id"] for s in st if s["status"] == 0]
    except Exception:
        running = ids                      # статус не узнать — гасим вслепую
    if not running:
        return
    log(f"страховка: гашу оставшиеся включёнными ({len(running)})")
    for pid in running:
        stop(pid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", dest="rng", default="1-5",
                    help="границы длительности одного сеанса, минуты")
    ap.add_argument("--gap", default="2-9",
                    help="пауза между телефонами, минуты")
    ap.add_argument("--only", default=None, help="только эти телефоны, через запятую")
    ap.add_argument("--include-unlogged", action="store_true",
                    help="греть и те, где вход не выполнен (по умолчанию пропускаются)")
    ap.add_argument("--no-geo-check", action="store_true")
    ap.add_argument("--ignore-plan", action="store_true",
                    help="не спрашивать warmup_plan, греть всех подряд по --range")
    ap.add_argument("--preview", action="store_true",
                    help="только показать, что кому выпало сегодня, ничего не запускать")
    a = ap.parse_args()

    fleet = json.loads((HERE / "fleet.json").read_text())
    items = [(pid, m) for pid, m in fleet.items()]
    if a.only:
        want = {s.strip() for s in a.only.split(",")}
        items = [(p, m) for p, m in items if m["name"] in want]
    if not a.include_unlogged:
        # Греть телефон без вошедшего аккаунта бессмысленно: приложение покажет
        # экран входа, никакой истории просмотра не появится, а минуты сгорят.
        skipped = [m["name"] for _, m in items if not m.get("logged_in")]
        items = [(p, m) for p, m in items if m.get("logged_in")]
        if skipped:
            log(f"пропускаю без входа: {', '.join(sorted(skipped))}")

    if not items:
        sys.exit("некого греть")

    today = date.today()
    # Возраст прогрева — сколько дней аккаунт уже «живёт». От него зависит,
    # что ему сегодня разрешено: подписки и истории открываются не сразу.
    plans = {}
    for pid, m in items:
        started = m.get("warmup_started")
        age = (today - date.fromisoformat(started)).days + 1 if started else 1
        plans[pid] = warmup_plan.plan_for(m.get("account") or m["name"], age, today)
        plans[pid]["age"] = age

    if not a.ignore_plan:
        skipped_today = [m["name"] for pid, m in items if plans[pid]["skip"]]
        items = [(pid, m) for pid, m in items if not plans[pid]["skip"]]
        if skipped_today:
            log(f"сегодня не заходят: {', '.join(sorted(skipped_today))}")

    if a.preview:
        RU = ["пн","вт","ср","чт","пт","сб","вс"]
        log(f"план на {RU[today.weekday()]} {today.strftime('%d.%m.%Y')}:")
        for pid, m in sorted(items, key=lambda x: x[1]["name"]):
            pl = plans[pid]
            log(f"  {m['name']}  день {pl['age']:>2} [{pl['phase']:<13}] "
                f"{pl['minutes']:>4} мин  {pl['mood']:<18} лайков {pl['likes']}, "
                f"подписок {pl['follows']}")
        return 0

    if not items:
        log("сегодня никто не заходит — так тоже бывает")
        return 0

    random.shuffle(items)                       # порядок каждый круг новый
    log(f"круг по {len(items)} телефонам: {', '.join(m['name'] for _, m in items)}")

    done, failed = [], []
    touched: list[str] = []
    try:
        _run_round(items, plans, a, fleet, today, done, failed, touched)
    finally:
        # Что бы ни случилось выше — обрыв сети, Ctrl+C, ошибка в коде —
        # телефоны не должны остаться включёнными.
        stop_all(touched or [pid for pid, _ in items])

    w = gl_api.post("/open/v1/pay/wallet", {})["data"]
    log(f"круг закончен. Прогрето: {len(done)} ({', '.join(done) or '—'})"
        + (f", с ошибкой: {', '.join(failed)}" if failed else ""))
    log(f"осталось минут: {w['availableTimeAddOn']}")
    return 0


def _run_round(items, plans, a, fleet, today, done, failed, touched) -> None:
    gap_lo, _, gap_hi = a.gap.partition("-")
    for i, (pid, meta) in enumerate(items, 1):
        name = meta["name"]
        log(f"--- {i}/{len(items)}  {name} ({meta.get('account','?')}) ---")
        touched.append(pid)
        if not start(pid):
            log(f"  {name}: не поднялся, пропускаю"); failed.append(name); continue
        try:
            if not a.no_geo_check:
                geo = geo_check.ensure_region(lambda: gl_device.Device(pid), pid,
                                              meta.get("proxy_state", "New York"),
                                              meta.get("proxy_isp"), attempts=2)
                if not geo.get("ok"):
                    log(f"  {name}: не в своём регионе, сеанс пропускаю")
                    failed.append(name); continue
            cmd = [PY, str(HERE / "warmup.py"), "--phone", pid]
            if a.ignore_plan:
                cmd += ["--range", a.rng]
            else:
                cmd += ["--plan", json.dumps(plans[pid], ensure_ascii=False)]
            r = subprocess.run(cmd, cwd=HERE, text=True)
            (done if r.returncode == 0 else failed).append(name)
            if r.returncode == 0 and not meta.get("warmup_started"):
                meta["warmup_started"] = today.isoformat()
                (HERE / "fleet.json").write_text(
                    json.dumps(fleet, ensure_ascii=False, indent=2))
        except Exception as e:
            log(f"  {name}: сбой — {e}"); failed.append(name)
        finally:
            stop(pid)
            log(f"  {name}: телефон погашен")

        if i < len(items):
            pause = random.uniform(float(gap_lo), float(gap_hi or gap_lo))
            log(f"пауза {pause:.1f} мин перед следующим")
            time.sleep(pause * 60)


if __name__ == "__main__":
    sys.exit(main())
