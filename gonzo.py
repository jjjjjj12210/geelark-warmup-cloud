"""Клиент GonzoProxy: выпуск прокси по требованию.

Нужен, чтобы не выпрашивать новые прокси руками каждый раз, когда истекает
липкая сессия. Ключ берётся из .env (GONZO_API_KEY), в чат его тащить не надо.

    .venv-adb/bin/python gonzo.py countries
    .venv-adb/bin/python gonzo.py isps --country US --state "New York"
    .venv-adb/bin/python gonzo.py generate --country US --state "New York" --count 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

BASE = "https://api.gonzoproxy.app/functions/v1/proxy-api"
ENV = Path(__file__).parent / ".env"


def _api_key() -> str:
    key = os.environ.get("GONZO_API_KEY")
    if not key and ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith("GONZO_API_KEY="):
                key = line.split("=", 1)[1].strip()
                break
    if not key:
        sys.exit(
            "нет GONZO_API_KEY. Возьми ключ в кабинете GonzoProxy "
            "(Settings → API Keys) и допиши строкой в ~/Documents/GeeLark-Manager/.env:\n"
            "  GONZO_API_KEY=<ключ>"
        )
    return key


def _call(path: str, body: dict | None = None, method: str = "POST") -> dict | list:
    # Ключ только заголовком — в документации отдельно оговорено, что в URL и
    # query его передавать нельзя.
    headers = {"x-api-key": _api_key(), "Content-Type": "application/json"}
    url = f"{BASE}{path}"
    if method == "GET":
        r = requests.get(url, headers=headers, params=body or {}, timeout=60)
    else:
        r = requests.post(url, headers=headers, json=body or {}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"GonzoProxy {path} → HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except ValueError:
        return {"_raw": r.text}


# --- публичное API -----------------------------------------------------

def generate(*, country: str = "US", state: str | None = None,
             city: str | None = None, isp: str | None = None,
             count: int = 1, ttl: int | None = None,
             ttl_unit: str = "hours", rotation: bool = False,
             fmt: str | None = None) -> dict | list:
    """Выпустить прокси. rotation=False — липкая сессия (нам нужна именно она).

    ttl задаём в часах. Опытным путём выяснено, что связка connect.gonzoproxy.app
    отвергает подключение при ttl больше 720 часов (1000h уже падает), поэтому
    выше этого значения не просим.
    """
    # format не передаём без нужды: любое значение, кроме отсутствия параметра,
    # даёт 400 «Unsupported format». Названия городов уходят как есть — API сам
    # приводит их к виду city_New-York (пробелы в дефисы), угадывать не надо.
    body: dict = {"country": country, "count": count, "rotation": rotation}
    if fmt:
        body["format"] = fmt
    if state:
        body["state"] = state
    if city:
        body["city"] = city
    if isp:
        body["isp"] = isp
    if ttl:
        body["ttl"] = min(ttl, 720) if ttl_unit == "hours" else ttl
        body["ttl_unit"] = ttl_unit
    return _call("/generate", body)


def countries() -> dict | list:
    return _call("/countries", method="GET")


def states(country: str) -> dict | list:
    return _call("/states", {"country": country}, method="GET")


def isps(country: str, state: str | None = None) -> dict | list:
    body = {"country": country}
    if state:
        body["state"] = state
    return _call("/isps", body, method="GET")


def parse_proxy(raw) -> dict | None:
    """Привести ответ /generate к единому виду {scheme, server, port, username,
    password}. Формат ответа в документации не описан, поэтому разбираем и
    строку `scheme://user:pass@host:port`, и словарь с отдельными полями."""
    import re
    if isinstance(raw, str):
        m = re.match(r"^(?:(?P<scheme>\w+)://)?(?P<user>[^:@]+):(?P<pwd>[^@]+)@"
                     r"(?P<host>[^:]+):(?P<port>\d+)$", raw.strip())
        if m:
            return {"scheme": m["scheme"] or "socks5", "server": m["host"],
                    "port": int(m["port"]), "username": m["user"], "password": m["pwd"]}
        return None
    if isinstance(raw, dict):
        host = raw.get("host") or raw.get("server") or raw.get("ip")
        port = raw.get("port")
        user = raw.get("login") or raw.get("username") or raw.get("user")
        pwd = raw.get("password") or raw.get("pass")
        if host and port and user and pwd:
            return {"scheme": raw.get("scheme") or raw.get("protocol") or "socks5",
                    "server": host, "port": int(port), "username": user, "password": pwd}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("countries")
    s = sub.add_parser("states"); s.add_argument("--country", default="US")
    i = sub.add_parser("isps"); i.add_argument("--country", default="US"); i.add_argument("--state")

    g = sub.add_parser("generate")
    g.add_argument("--country", default="US")
    g.add_argument("--state")
    g.add_argument("--city")
    g.add_argument("--isp")
    g.add_argument("--count", type=int, default=1)
    g.add_argument("--ttl", type=int, default=720, help="часы, потолок 720")

    a = ap.parse_args()
    if a.cmd == "countries":
        out = countries()
    elif a.cmd == "states":
        out = states(a.country)
    elif a.cmd == "isps":
        out = isps(a.country, a.state)
    else:
        out = generate(country=a.country, state=a.state, city=a.city, isp=a.isp,
                       count=a.count, ttl=a.ttl)
    print(json.dumps(out, ensure_ascii=False, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
