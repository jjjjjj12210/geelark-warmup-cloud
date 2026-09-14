"""Развёртывание парка облачных телефонов GeeLark под несколько аккаунтов.

Один аккаунт = один телефон = один прокси. Общий IP связывает аккаунты между
собой, поэтому прокси не переиспользуются ни при каких обстоятельствах.

    .venv-adb/bin/python fleet.py check-proxies      # проверить прокси, бесплатно
    .venv-adb/bin/python fleet.py create --count 10  # создать телефоны
    .venv-adb/bin/python fleet.py list               # что есть сейчас
    .venv-adb/bin/python fleet.py install-ig         # поставить Instagram на все
    .venv-adb/bin/python fleet.py start --all        # поднять
    .venv-adb/bin/python fleet.py stop --all         # погасить (минуты!)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import gl_api

HERE = Path(__file__).parent
PROXY_FILE = HERE / "proxies.txt"
FLEET_FILE = HERE / "fleet.json"          # id → аккаунт, прокси, состояние

# Модель фиксирована: координаты в publish.py сняты именно на ней. Другая
# модель — часть тапов уедет, см. PUBLISH-SCENARIO.md.
MOBILE_TYPE = "Android 15"
REGION = "us"
BRAND = "Samsung"
MODEL = "Galaxy S23 Ultra"
GROUP = "Brusher"

PROXY_RE = re.compile(
    r"^(?P<scheme>socks5|http|https)://"
    r"(?P<user>[^:@]+):(?P<pwd>[^@]+)@"
    r"(?P<host>[^:]+):(?P<port>\d+)$"
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_proxies() -> list[dict]:
    if not PROXY_FILE.exists():
        sys.exit(f"нет файла с прокси: {PROXY_FILE}")
    out = []
    for i, line in enumerate(PROXY_FILE.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = PROXY_RE.match(line)
        if not m:
            sys.exit(f"строка {i}: не разобрал прокси — {line[:40]}...")
        out.append({
            "scheme": m["scheme"], "server": m["host"], "port": int(m["port"]),
            "username": m["user"], "password": m["pwd"], "line": i,
        })
    return out


def load_fleet() -> dict:
    return json.loads(FLEET_FILE.read_text()) if FLEET_FILE.exists() else {}


def save_fleet(data: dict) -> None:
    FLEET_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# --- команды -----------------------------------------------------------

def cmd_check_proxies(_: argparse.Namespace) -> int:
    """Прогнать все прокси через проверялку GeeLark. Ничего не тратит."""
    proxies = load_proxies()
    log(f"проверяю {len(proxies)} прокси")
    ok, seen_ips = 0, {}
    for p in proxies:
        r = gl_api.post("/open/v1/proxy/check", {
            "proxyQueryChannel": "IP2Location", "proxyType": p["scheme"],
            "server": p["server"], "port": p["port"],
            "username": p["username"], "password": p["password"],
        })
        d = r.get("data") or {}
        if d.get("detectStatus"):
            ip = d.get("outboundIP", "?")
            where = f"{d.get('countryCode')}/{d.get('subdivision')}/{d.get('city')}"
            dup = "  ⚠ IP ПОВТОРЯЕТСЯ" if ip in seen_ips else ""
            seen_ips.setdefault(ip, p["line"])
            print(f"  {p['line']:2}. ✓ {ip:<16} {where:<28} {d.get('isp','')}{dup}")
            ok += 1
        else:
            print(f"  {p['line']:2}. ✗ не отвечает: {d.get('message') or r.get('msg')}")
    log(f"живых {ok} из {len(proxies)}, уникальных IP {len(seen_ips)}")
    # Одинаковый IP у двух телефонов = связанные аккаунты, это блокер.
    return 0 if ok == len(proxies) and len(seen_ips) == len(proxies) else 1


def cmd_list(_: argparse.Namespace) -> int:
    r = gl_api.post("/open/v1/phone/list", {"page": 1, "pageSize": 100})
    items = r["data"].get("items") or []
    fleet = load_fleet()
    print(f"телефонов: {len(items)}")
    for p in items:
        pid = p.get("id")
        meta = fleet.get(pid, {})
        eq = p.get("equipmentInfo") or {}
        print(f"  {pid}  {p.get('serialName'):<16} {eq.get('deviceModel','?'):<10} "
              f"аккаунт={meta.get('account') or '—'}  прокси#{meta.get('proxy_line') or '—'}")
    plan = gl_api.post("/open/v1/pay/plan/info", {})["data"]
    wallet = gl_api.post("/open/v1/pay/wallet", {})["data"]
    print(f"слотов {plan['profiles']}, свободно {plan['availableProfiles']}, "
          f"минут {wallet['availableTimeAddOn']}")
    return 0


def cmd_create(a: argparse.Namespace) -> int:
    proxies = load_proxies()
    fleet = load_fleet()
    used_lines = {m.get("proxy_line") for m in fleet.values()}
    free = [p for p in proxies if p["line"] not in used_lines]

    plan = gl_api.post("/open/v1/pay/plan/info", {})["data"]
    slots = plan["availableProfiles"]
    n = min(a.count, len(free), slots)
    if n < a.count:
        log(f"просили {a.count}, делаю {n}: свободных прокси {len(free)}, слотов {slots}")
    if n <= 0:
        sys.exit("нечего создавать: нет свободных прокси или слотов")

    for i in range(n):
        p = free[i]
        name = f"{a.prefix}-{p['line']:02d}"
        body = {
            "mobileType": MOBILE_TYPE, "chargeMode": 0, "region": REGION,
            "data": [{
                "profileName": name,
                "proxyInformation": (f"{p['scheme']}://{p['username']}:{p['password']}"
                                     f"@{p['server']}:{p['port']}"),
                "proxyQueryChannel": 2,
                "surfaceBrandName": BRAND, "surfaceModelName": MODEL,
                "mobileLanguage": "baseOnIP", "netType": 0,
                "profileGroup": GROUP,
                "profileNote": "ADB-публикация Reels",
            }],
        }
        r = gl_api.post("/open/v1/phone/addNew", body)
        det = (r.get("data") or {}).get("details") or [{}]
        d0 = det[0]
        if d0.get("code") != 0:
            log(f"  {name}: ОШИБКА {d0.get('code')} {d0.get('msg')}")
            continue
        pid = d0["id"]
        eq = d0.get("equipmentInfo") or {}
        fleet[pid] = {
            "name": name, "proxy_line": p["line"], "account": None,
            "model": eq.get("deviceModel"), "created": time.strftime("%Y-%m-%d %H:%M"),
        }
        save_fleet(fleet)
        log(f"  {name}: создан {pid} ({eq.get('deviceBrand')} {eq.get('deviceModel')})")
        time.sleep(2)                      # Base-план не любит пачки подряд
    return 0


def _phone_ids(a: argparse.Namespace) -> list[str]:
    fleet = load_fleet()
    if a.phone:
        return [a.phone]
    return list(fleet.keys())


def cmd_start(a: argparse.Namespace) -> int:
    ids = _phone_ids(a)
    if not ids:
        sys.exit("парк пуст")
    log(f"поднимаю {len(ids)} телефонов — минуты идут на каждый")
    gl_api.post("/open/v1/phone/start", {"ids": ids, "energySavingMode": 1})
    for _ in range(20):
        st = gl_api.post("/open/v1/phone/status", {"ids": ids})["data"]["successDetails"]
        running = [s for s in st if s["status"] == 0]
        log(f"  запущено {len(running)}/{len(ids)}")
        if len(running) == len(ids):
            break
        time.sleep(15)
    gl_api.post("/open/v1/adb/setStatus", {"ids": ids, "open": True})
    log("ADB включён")
    return 0


def cmd_stop(a: argparse.Namespace) -> int:
    ids = _phone_ids(a)
    if not ids:
        sys.exit("парк пуст")
    gl_api.post("/open/v1/phone/stop", {"ids": ids})
    log(f"остановлено: {len(ids)}")
    w = gl_api.post("/open/v1/pay/wallet", {})["data"]
    log(f"осталось минут: {w['availableTimeAddOn']}")
    return 0


def cmd_install_ig(a: argparse.Namespace) -> int:
    """Поставить полноценный Instagram (не Lite) на телефоны парка."""
    ids = _phone_ids(a)
    for pid in ids:
        r = gl_api.post("/open/v1/app/installable/list",
                        {"envId": pid, "name": "instagram", "page": 1, "pageSize": 50})
        app = next((x for x in r["data"]["items"]
                    if x.get("packageName") == "com.instagram.android"), None)
        if not app:
            log(f"  {pid}: Instagram не найден в библиотеке")
            continue
        ver = app["appVersionInfoList"][0]
        gl_api.post("/open/v1/app/install", {"envId": pid, "appVersionId": ver["id"]})
        log(f"  {pid}: ставлю Instagram {ver['versionName']}")
        time.sleep(2)
    return 0


def _check_one(p: dict) -> dict:
    """Проверить один прокси через GeeLark. Возвращает data проверки."""
    r = gl_api.post("/open/v1/proxy/check", {
        "proxyQueryChannel": "IP2Location", "proxyType": p["scheme"],
        "server": p["server"], "port": p["port"],
        "username": p["username"], "password": p["password"],
    })
    return r.get("data") or {}


def cmd_health(a: argparse.Namespace) -> int:
    """Проверить прокси всего парка, не запуская телефоны. Ничего не тратит."""
    proxies = {p["line"]: p for p in load_proxies()}
    fleet = load_fleet()
    dead = []
    for pid, meta in fleet.items():
        p = proxies.get(meta.get("proxy_line"))
        if not p:
            print(f"  {meta['name']:<8} прокси #{meta.get('proxy_line')} нет в proxies.txt")
            dead.append(pid)
            continue
        d = _check_one(p)
        if d.get("detectStatus"):
            print(f"  {meta['name']:<8} ✓ {d.get('outboundIP'):<16} "
                  f"{d.get('subdivision')}/{d.get('city')}  {d.get('isp','')}")
        else:
            print(f"  {meta['name']:<8} ✗ {d.get('message') or 'не отвечает'}")
            dead.append(pid)
    print(f"\nживых {len(fleet) - len(dead)} из {len(fleet)}")
    if dead:
        print("починить:  .venv-adb/bin/python fleet.py rotate-proxies")
    return 1 if dead else 0


def cmd_rotate_proxies(a: argparse.Namespace) -> int:
    """Заменить умершие прокси на свежие и прописать их телефонам.

    Новый прокси заказывается с ТОЙ ЖЕ географией, что была у старого: смена
    штата или провайдера у живого аккаунта выглядит куда подозрительнее, чем
    смена адреса внутри того же города.
    """
    import gonzo

    proxies = {p["line"]: p for p in load_proxies()}
    fleet = load_fleet()
    lines = PROXY_FILE.read_text().splitlines()

    targets = []
    for pid, meta in fleet.items():
        p = proxies.get(meta.get("proxy_line"))
        if a.phone and pid != a.phone:
            continue
        if p is None:
            targets.append((pid, meta, None))
            continue
        d = _check_one(p)
        if not d.get("detectStatus"):
            targets.append((pid, meta, d))
        elif a.force:
            targets.append((pid, meta, d))

    if not targets:
        log("все прокси живые, менять нечего")
        return 0

    log(f"меняю прокси на {len(targets)} телефонах")
    for pid, meta, old in targets:
        geo = meta.get("geo") or {}
        state = geo.get("state") or (old or {}).get("subdivision") or "New York"
        raw = gonzo.generate(country="US", state=state, count=1, ttl=720)
        # Ответ может быть строкой, списком строк или словарём — разбираем всё.
        cand = raw
        if isinstance(cand, dict):
            for k in ("proxies", "data", "result", "items"):
                if k in cand:
                    cand = cand[k]
                    break
        if isinstance(cand, list) and cand:
            cand = cand[0]
        new = gonzo.parse_proxy(cand)
        if not new:
            log(f"  {meta['name']}: не разобрал ответ GonzoProxy: {str(raw)[:200]}")
            continue

        chk = _check_one(new)
        if not chk.get("detectStatus"):
            log(f"  {meta['name']}: выданный прокси не отвечает, пропускаю")
            continue

        r = gl_api.post("/open/v1/phone/detail/update", {
            "id": pid,
            "proxyQueryChannel": 2,
            "proxyConfig": {
                "typeId": 1,                       # socks5
                "server": new["server"], "port": new["port"],
                "username": new["username"], "password": new["password"],
            },
        })
        if r.get("code") != 0:
            log(f"  {meta['name']}: GeeLark отказал: {r.get('msg')}")
            continue

        # Обновляем proxies.txt на той же строке, чтобы нумерация не поехала.
        idx = meta.get("proxy_line")
        newline = (f"{new['scheme']}://{new['username']}:{new['password']}"
                   f"@{new['server']}:{new['port']}")
        if idx and 1 <= idx <= len(lines):
            lines[idx - 1] = newline
        meta["geo"] = {"state": chk.get("subdivision"), "city": chk.get("city")}
        meta["proxy_rotated"] = time.strftime("%Y-%m-%d %H:%M")
        log(f"  {meta['name']}: новый IP {chk.get('outboundIP')} "
            f"({chk.get('subdivision')}/{chk.get('city')}, {chk.get('isp','')})")

    PROXY_FILE.write_text("\n".join(lines) + "\n")
    save_fleet(fleet)
    return 0


def cmd_delete(a: argparse.Namespace) -> int:
    if not a.phone:
        sys.exit("укажи --phone <id>; массового удаления тут намеренно нет")
    st = gl_api.post("/open/v1/phone/status", {"ids": [a.phone]})["data"]["successDetails"][0]
    log(f"удаляю {st['serialName']} ({a.phone}), статус {st['status']}")
    r = gl_api.post("/open/v1/phone/delete", {"ids": [a.phone]})
    log(f"ответ: {r.get('msg')}, успешно {r['data']['successAmount']}")
    fleet = load_fleet()
    fleet.pop(a.phone, None)
    save_fleet(fleet)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-proxies")
    sub.add_parser("list")

    c = sub.add_parser("create")
    c.add_argument("--count", type=int, default=10)
    c.add_argument("--prefix", default="BR")

    for name in ("start", "stop", "install-ig"):
        s = sub.add_parser(name)
        s.add_argument("--phone", default=None, help="один телефон; иначе весь парк")
        s.add_argument("--all", action="store_true", help="весь парк (по умолчанию)")

    d = sub.add_parser("delete")
    d.add_argument("--phone", required=True)

    sub.add_parser("health")

    rp = sub.add_parser("rotate-proxies")
    rp.add_argument("--phone", default=None, help="только этот телефон")
    rp.add_argument("--force", action="store_true",
                    help="менять даже живые прокси (обычно не нужно)")

    a = ap.parse_args()
    return {
        "check-proxies": cmd_check_proxies, "list": cmd_list, "create": cmd_create,
        "start": cmd_start, "stop": cmd_stop, "install-ig": cmd_install_ig,
        "delete": cmd_delete, "health": cmd_health, "rotate-proxies": cmd_rotate_proxies,
    }[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
