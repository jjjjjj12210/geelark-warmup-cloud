"""Проверка географии выходного адреса перед работой с аккаунтом.

Зачем. Постоянный IP на нашем тарифе недостижим: при каждом запуске телефона
провайдер выдаёт новый адрес. Дрейф внутри одного штата и провайдера — то, что
происходит у живых людей, и он безобиден. А вот прыжок в другой штат заметен:
у BR-09 при заказе Spectrum/Олбани однажды выдался Comcast в Иллинойсе.

Отсюда правило: перед работой смотрим, где телефон оказался на самом деле, и
если вылез за пределы своего штата — МЕНЯЕМ САМУ СЕССИЮ прокси на новую, в том
же городе и у того же провайдера.

Изначально здесь был перезапуск телефона — предполагалось, что он вытянет
новый адрес из пула. Два живых прогона это опровергли: 01.09 у BR-01 (Флорида)
и 02.09 у BR-04 (Огайо) после перезапуска приходил РОВНО ТОТ ЖЕ адрес.
Привязка сессии переживает перезапуск, поэтому лечит только смена сессии.

Штат — жёсткое требование. Провайдер — мягкое: в справочниках он зовётся
«Verizon Fios», а в данных об адресе может прийти «Verizon Business», и
сравнивать их дословно бессмысленно, поэтому расхождение только отмечается.
"""
from __future__ import annotations

import json
import time
import urllib.request

import gl_api

BOOT_WAIT = 15          # пауза между опросами статуса при перезапуске
BOOT_TRIES = 14

# В справочнике провайдер зовётся торговой маркой, а в данных об адресе стоит
# юридическое лицо: Spectrum принадлежит Charter, Optimum — Cablevision/Altice,
# Fios — это Verizon. Без этой таблицы каждая проверка сыпала бы ложными
# предупреждениями о «не том провайдере».
ISP_ALIASES = {
    "spectrum": ("charter", "spectrum"),
    "optimum online": ("cablevision", "altice", "optimum"),
    "optimum fiber": ("cablevision", "altice", "optimum"),
    "verizon fios": ("verizon",),
    "verizon internet services": ("verizon",),
    "frontier communications": ("frontier",),
    "greenlight networks": ("greenlight", "level 3"),
    "empire access": ("empire", "mcnc"),
    "starry": ("starry",),
    "finger lakes communications group": ("finger lakes",),
}


def isp_matches(expected: str, org: str) -> bool:
    org = (org or "").lower()
    keys = ISP_ALIASES.get((expected or "").lower(), ())
    if not keys:
        keys = ((expected or "").split()[0].lower(),) if expected else ()
    return any(k in org for k in keys)


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def phone_ip(d) -> str:
    """Внешний адрес глазами самого телефона — то же, что увидит Instagram."""
    return d.sh("curl -s --max-time 25 https://api.ipify.org").strip()


def ip_geo(ip: str) -> dict:
    """География адреса. Запрашивается с нашей машины, а не с телефона:
    лишний обращений к сторонним сервисам с устройства лучше не делать."""
    if not ip:
        return {}
    try:
        with urllib.request.urlopen(f"https://ipinfo.io/{ip}/json", timeout=20) as r:
            return json.load(r)
    except Exception:
        return {}


def describe(geo: dict) -> str:
    return f"{geo.get('ip','?')} — {geo.get('city','?')}, {geo.get('region','?')} / {geo.get('org','?')}"


def restart_phone(phone_id: str) -> bool:
    """Перезапуск ради нового адреса из пула."""
    gl_api.post("/open/v1/phone/stop", {"ids": [phone_id]})
    time.sleep(10)
    gl_api.post("/open/v1/phone/start", {"ids": [phone_id], "energySavingMode": 1})
    for _ in range(BOOT_TRIES):
        st = gl_api.post("/open/v1/phone/status", {"ids": [phone_id]})["data"]["successDetails"][0]
        if st["status"] == 0:
            gl_api.post("/open/v1/adb/setStatus", {"ids": [phone_id], "open": True})
            time.sleep(5)
            return True
        time.sleep(BOOT_WAIT)
    return False


def swap_proxy(phone_id: str, attempts: int = 3) -> dict | None:
    """Выдать телефону новую сессию прокси в его же штате.

    Именно это лечит промах региона. Перезапуск телефона — не лечит: живые
    прогоны 01.09 (BR-01, Флорида) и 02.09 (BR-04, Огайо) показали, что после
    перезапуска приходит РОВНО ТОТ ЖЕ адрес — привязка сессии его переживает.
    Значит менять надо саму сессию.
    """
    import json as _json
    import subprocess
    from pathlib import Path
    import gonzo

    here = Path(__file__).parent
    fleet_path = here / "fleet.json"
    fleet = _json.loads(fleet_path.read_text())
    meta = fleet.get(phone_id)
    if not meta:
        return None
    state = meta.get("proxy_state", "New York")
    city = meta.get("proxy_city")
    isp = meta.get("proxy_isp")

    # Ступени отбора, от точного к грубому. Город — самое хрупкое условие: у
    # BR-08 закреплён Фелпс с провайдером Finger Lakes, и в таком городке у
    # поставщика адресов нет вовсе — запрос возвращает пусто, хотя без города
    # тот же запрос отрабатывает. Штат не роняем никогда: это жёсткое
    # требование, ради которого проверка и существует.
    tiers, seen = [], []
    for t in (dict(state=state, city=city, isp=isp),
              dict(state=state, isp=isp),
              dict(state=state)):
        t = {k: v for k, v in t.items() if v}
        if t not in seen:
            seen.append(t); tiers.append(t)

    for tier in tiers:
        for _ in range(attempts):
            r = gonzo.generate(country="US", count=1, ttl=720, **tier)
            raw = (r.get("proxies") or [None])[0]
            if not raw:
                break                      # на этой ступени пусто — грубее
            user, rest = raw.split(":", 1)
            pwd = rest.split("@")[0]
            ip = subprocess.run(
                ["curl", "-s", "--max-time", "30", "--socks5-hostname",
                 "185.162.128.131:10000", "--proxy-user", f"{user}:{pwd}",
                 "https://api.ipify.org"],
                capture_output=True, text=True).stdout.strip()
            if not ip:
                continue
            geo = ip_geo(ip)
            if (geo.get("region") or "").lower() != state.lower():
                continue                   # снова не тот штат — берём следующий

            res = gl_api.post("/open/v1/phone/detail/update", {
                "id": phone_id, "proxyQueryChannel": 2,
                "proxyConfig": {"typeId": 1, "server": "185.162.128.131",
                                "port": 10000, "username": user, "password": pwd}})
            if res.get("code") != 0:
                _log(f"  GeeLark не принял новый прокси: {res.get('msg')}")
                return None

            meta["proxy_user"] = user
            meta["proxy_city"] = geo.get("city")
            line = meta.get("proxy_line")
            pf = here / "proxies.txt"
            if line and pf.exists():
                lines = pf.read_text().splitlines()
                if 1 <= line <= len(lines):
                    lines[line - 1] = f"socks5://{user}:{pwd}@185.162.128.131:10000"
                    pf.write_text("\n".join(lines) + "\n")
            fleet_path.write_text(_json.dumps(fleet, ensure_ascii=False, indent=2))
            if len(tier) < 3:
                _log(f"  точный подбор не дал адреса, взял по условию {tier}")
            _log(f"  выдана новая сессия прокси: {describe(geo)}")
            return geo
    return None


def ensure_region(device_factory, phone_id: str, expected_state: str,
                  expected_isp: str | None = None, attempts: int = 3) -> dict:
    """Добиться, чтобы телефон вышел в нужном штате.

    device_factory — функция без аргументов, возвращающая свежий gl_device.Device
    (после перезапуска старое подключение недействительно, нужно новое).

    Возвращает географию последнего замера. Ключ `ok` говорит, попали ли в штат;
    решение, что делать при неудаче, принимает вызывающий код — здесь мы не
    роняем сценарий молча.
    """
    geo: dict = {}
    for attempt in range(1, attempts + 1):
        d = device_factory()

        # Пустой ответ — это НЕ «не тот регион», а неудача чтения: телефон мог
        # не успеть поднять сеть или отвалилось ADB. Раньше код валил такое в
        # одну кучу с промахом штата (BR-08, 02.09) и зря менял прокси.
        ip = ""
        for _ in range(3):
            ip = phone_ip(d)
            if ip:
                break
            time.sleep(5)
        if not ip:
            _log("  не удалось прочитать адрес телефона — сеть или ADB")
            return {"ok": False, "reason": "адрес не прочитан"}

        geo = ip_geo(ip)
        geo.setdefault("ip", ip)
        state = (geo.get("region") or "").strip()
        org = geo.get("org") or ""

        if not state:
            _log(f"  география по адресу {ip} не определилась")
            return {"ok": False, "ip": ip, "reason": "география не определилась"}

        if state.lower() == expected_state.lower():
            if expected_isp and not isp_matches(expected_isp, org):
                _log(f"  регион верный, но провайдер иной: ждали {expected_isp}, получили {org}")
            _log(f"  география в порядке: {describe(geo)}")
            geo["ok"] = True
            return geo

        _log(f"  вышли не туда: {describe(geo)} — ждали штат {expected_state}")
        if attempt == attempts:
            break

        # Меняем сессию прокси, а не перезапускаем телефон: перезапуск
        # возвращает тот же адрес, это проверено дважды на живых прогонах.
        _log(f"  меняю сессию прокси (попытка {attempt}/{attempts - 1})")
        if swap_proxy(phone_id) is None:
            _log("  подобрать прокси в нужном штате не удалось")
            break
        if not restart_phone(phone_id):     # новый прокси подхватывается при старте
            _log("  телефон не поднялся после смены прокси")
            break

    geo["ok"] = False
    return geo
