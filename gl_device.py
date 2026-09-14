"""Обёртка над adb для облачного телефона GeeLark.

Держит одно подключение на весь сеанс и сама перелогинивается, когда GeeLark
рвёт сессию по простою. Работает голым adb: никаких агентов на устройство не
ставится, лишнего следа автоматизации не остаётся.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import time

import gl_api

# На Mac adb стоит через Homebrew по фиксированному пути; в облачном
# окружении (другая ОС, другой способ установки) его надо искать в PATH,
# а если и там нет — сообщить внятно, а не тихо падать на каждой команде.
ADB = shutil.which("adb") or "/opt/homebrew/bin/adb"


class Device:
    def __init__(self, phone_id: str):
        self.phone_id = phone_id
        self.addr = ""
        self.pwd = ""
        self.connect()

    # --- подключение ---------------------------------------------------

    def connect(self) -> None:
        data = gl_api.post("/open/v1/adb/getData", {"ids": [self.phone_id]})
        item = data["data"]["items"][0]
        if item["code"] != 0:
            raise RuntimeError(f"ADB недоступен: {item.get('msg') or item['code']} — телефон запущен?")
        self.addr = f"{item['ip']}:{item['port']}"
        self.pwd = item["pwd"]
        subprocess.run([ADB, "connect", self.addr], capture_output=True, timeout=60)
        self._glogin()

    def _glogin(self) -> bool:
        r = subprocess.run([ADB, "-s", self.addr, "shell", "glogin", self.pwd],
                           capture_output=True, text=True, timeout=60)
        return "success" in r.stdout or "already logged" in r.stdout

    # --- команды -------------------------------------------------------

    def sh(self, cmd: str, timeout: int = 60) -> str:
        r = subprocess.run([ADB, "-s", self.addr, "shell", cmd],
                           capture_output=True, text=True, timeout=timeout)
        out = r.stdout + r.stderr
        if "glogin to login first" in out:          # сессия протухла
            self._glogin()
            r = subprocess.run([ADB, "-s", self.addr, "shell", cmd],
                               capture_output=True, text=True, timeout=timeout)
            out = r.stdout + r.stderr
        return out.strip()

    def tap(self, x: int, y: int, jitter: int = 6) -> None:
        """Тап с небольшим разбросом — палец не попадает в одну точку дважды."""
        self.sh(f"input tap {x + random.randint(-jitter, jitter)} {y + random.randint(-jitter, jitter)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int | None = None) -> None:
        ms = ms or random.randint(280, 620)
        j = lambda v: v + random.randint(-12, 12)
        self.sh(f"input swipe {j(x1)} {j(y1)} {j(x2)} {j(y2)} {ms}")

    def key(self, code: str) -> None:
        self.sh(f"input keyevent {code}")

    def text(self, s: str) -> None:
        self.sh("input text " + json.dumps(s).replace(" ", "%s"))

    def push(self, local: str, remote: str, timeout: int = 300) -> None:
        """Заливка файла с переподключением.

        GeeLark роняет ADB-сессию по простою, и `push` — самая длинная операция
        в сценарии, так что попадает под это чаще прочих. Идёт мимо sh(), где
        перелогин уже есть, поэтому обрыв обрабатываем здесь отдельно."""
        for attempt in (1, 2):
            r = subprocess.run([ADB, "-s", self.addr, "push", local, remote],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return
            err = r.stderr.strip()
            if attempt == 1 and ("offline" in err or "not found" in err):
                subprocess.run([ADB, "disconnect", self.addr], capture_output=True, timeout=30)
                self.connect()
                continue
            raise RuntimeError(f"adb push не прошёл: {err}")

    def add_to_gallery(self, remote: str) -> None:
        """Без этой рассылки файл лежит на диске, но галерея его не видит.

        Путь обязательно в кавычках: скобки и пробелы в имени файла иначе
        роняют команду с `syntax error: unexpected '('`, причём молча —
        ошибка уходит в stdout, а не в исключение, и пропажа обнаруживается
        только потом, пустым пикером галереи."""
        r = self.sh(
            "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            f'-d "file://{remote}"'
        )
        if "Broadcast completed" not in r:
            raise RuntimeError(f"медиасканеру не удалось сообщить о файле: {r}")

    def screencap(self, path: str) -> str:
        """Снимок экрана. exec-out идёт мимо sh(), поэтому glogin проверяем сами:
        протухшая сессия иначе пишет в файл текст ошибки вместо PNG."""
        for attempt in (1, 2):
            with open(path, "wb") as f:
                subprocess.run([ADB, "-s", self.addr, "exec-out", "screencap", "-p"],
                               stdout=f, timeout=120)
            with open(path, "rb") as f:
                if f.read(8) == b"\x89PNG\r\n\x1a\n":
                    return path
            if attempt == 1:
                self._glogin()
        raise RuntimeError(f"не удалось снять экран: {path}")

    def ui(self) -> str:
        self.sh("uiautomator dump /sdcard/ui.xml")
        return self.sh("cat /sdcard/ui.xml", timeout=120)

    def dump(self) -> str:
        """Свежий дамп UI-дерева — в отличие от ui(), явно удаляет старый файл
        первым, чтобы не поймать устаревший кэш при быстрой смене экрана."""
        self.sh("rm -f /sdcard/ui.xml")
        return self.ui()

    def current_app(self) -> str:
        out = self.sh("dumpsys activity activities | grep -m1 topResumedActivity")
        m = re.search(r"\s([\w.]+)/([\w.]+)", out)
        return m.group(1) if m else "?"

    # --- поиск элементов по тексту --------------------------------------
    #
    # Жёсткие координаты хрупкие: другая версия приложения или другое
    # разрешение — и тап уходит мимо, молча. Там, где у элемента есть текст
    # или content-desc, надёжнее искать его в UI-дереве. Координаты остаются
    # запасным вариантом для иконок без подписи (см. publish.py).

    _NODE_RE = re.compile(r"<node[^>]*>")
    _TEXT_RE = re.compile(r'text="([^"]*)"')
    _DESC_RE = re.compile(r'content-desc="([^"]*)"')
    _BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')

    def find(self, *, text: str | None = None, desc: str | None = None,
             exact: bool = False, xml: str | None = None) -> tuple[int, int] | None:
        """Центр первого элемента, чей text/content-desc содержит (или равен
        при exact=True) искомую строку. Можно передать готовый xml, чтобы не
        тратить время на повторный dump при последовательных поисках на одном
        экране."""
        xml = xml if xml is not None else self.dump()
        for m in self._NODE_RE.finditer(xml):
            node = m.group(0)
            b = self._BOUNDS_RE.search(node)
            if not b:
                continue
            for pattern, rex in ((text, self._TEXT_RE), (desc, self._DESC_RE)):
                if pattern is None:
                    continue
                mm = rex.search(node)
                val = mm.group(1) if mm else ""
                hit = (val == pattern) if exact else (pattern in val)
                if hit:
                    x1, y1, x2, y2 = map(int, b.groups())
                    return ((x1 + x2) // 2, (y1 + y2) // 2)
        return None

    def find_all(self, *, text: str | None = None, desc: str | None = None,
                 exact: bool = False, xml: str | None = None) -> list[tuple[int, int, int, int]]:
        """Все совпадения списком bounds (x1, y1, x2, y2), сверху вниз.

        Нужно там, где на экране несколько одинаковых элементов и важно, какой
        именно брать — например, иконки звука у разных рядов таймлайна."""
        xml = xml if xml is not None else self.dump()
        out: list[tuple[int, int, int, int]] = []
        for m in self._NODE_RE.finditer(xml):
            node = m.group(0)
            b = self._BOUNDS_RE.search(node)
            if not b:
                continue
            for pattern, rex in ((text, self._TEXT_RE), (desc, self._DESC_RE)):
                if pattern is None:
                    continue
                mm = rex.search(node)
                val = mm.group(1) if mm else ""
                hit = (val == pattern) if exact else (pattern in val)
                if hit:
                    out.append(tuple(map(int, b.groups())))  # type: ignore[arg-type]
                    break
        return sorted(out, key=lambda r: r[1])

    def has_text(self, text: str, *, xml: str | None = None) -> bool:
        return self.find(text=text, xml=xml) is not None

    def tap_text(self, text: str | None = None, desc: str | None = None, *,
                 timeout: float = 12.0, poll: float = 1.0,
                 exact: bool = False) -> tuple[int, int]:
        """Дождаться элемента по тексту/content-desc и тапнуть по нему.

        Кидает LookupError, если за timeout секунд элемент не появился —
        вызывающий код сам решает, что это значит (обычно неожиданный экран),
        вместо того чтобы тап тихо ушёл в пустоту."""
        deadline = time.time() + timeout
        while True:
            pos = self.find(text=text, desc=desc, exact=exact)
            if pos:
                self.tap(*pos)
                return pos
            if time.time() >= deadline:
                raise LookupError(f"не нашёл на экране: text={text!r} desc={desc!r}")
            time.sleep(poll)
