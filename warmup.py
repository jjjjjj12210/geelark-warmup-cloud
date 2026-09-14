"""Прогрев аккаунта Instagram на облачном телефоне GeeLark.

Ведёт себя как обычный зритель, а не как бот с одним сценарием: чередует
Reels, ленту, Stories, чистый Explore-грид без запроса, текстовый поиск и
заходы в чужие профили — то есть разные типы контента, а не один и тот же
формат по кругу. Внутри каждого блока — лайки, изредка save или заглянуть в
комментарии, всё с паузами из humanize.py (см. там же, почему они разные при
каждом вызове). Ничего не публикует и не подписывается пачками — задача в
том, чтобы у аккаунта появилась история нормального потребления контента до
первой публикации.

Длительность сеанса по умолчанию случайная, 1–5 минут: одинаковые по времени
заходы выглядят как расписание, а не как живой человек.

    .venv-adb/bin/python warmup.py                    # случайно 1–5 мин
    .venv-adb/bin/python warmup.py --range 2-8        # случайно в своих границах
    .venv-adb/bin/python warmup.py --minutes 4        # ровно 4 минуты
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time

import gl_device
import humanize

PHONE_ID = "633516545653342563"          # Brusher-IG-01
PKG = "com.instagram.android"

W, H = 720, 1440
NAV = {                                   # нижняя панель
    "home":    (72, 1326),
    "reels":   (215, 1326),
    "search":  (503, 1326),
    "profile": (648, 1326),
}
# Правый край экрана Reels: лайк двойным тапом по центру, остальное — иконки
# справа. Координаты сняты с живого прогона, могут потребовать перекалибровки
# на другом разрешении (см. PUBLISH-SCENARIO.md про то же для publish.py).
REEL_RAIL = {"comment": (670, 723), "save": (670, 1057), "author": (60, 1210)}

QUERIES = ["procreate brushes", "digital art", "ipad lettering",
           "procreate tutorial", "sketchbook art"]

# Кружки историй в верхней плашке ленты. Индекс 0 — "Your story" (публикация
# собственной), его не трогаем — смотрим только чужие.
STORY_X = [275, 456, 639]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def remaining(deadline: float) -> float:
    return max(0.0, deadline - time.time())


# --- блоки -----------------------------------------------------------------

def watch_reels(d: gl_device.Device, like_budget: list[int], deadline: float,
                 count: int | None = None) -> None:
    d.tap(*NAV["reels"]); humanize.wait("screen")
    for i in range(count or random.randint(3, 7)):
        if time.time() >= deadline:
            log("  время вышло, досматривать не начинаю")
            return
        dwell = random.choice([  # часть роликов долистывается сразу, часть досматривается
            random.uniform(2.5, 6),
            random.uniform(6, 15),
            random.uniform(15, 32),
        ])
        dwell = min(dwell, max(2.0, remaining(deadline)))
        log(f"  ролик {i + 1}: смотрю {dwell:.0f} сек")
        time.sleep(dwell)

        if like_budget[0] > 0 and dwell > 4 and humanize.maybe(0.55):
            d.sh(f"input tap {W // 2} {H // 2}"); time.sleep(0.12)
            d.sh(f"input tap {W // 2} {H // 2}")          # двойной тап — лайк
            like_budget[0] -= 1
            log(f"  ↳ лайк (осталось {like_budget[0]})")
            humanize.wait("tap")
        elif dwell > 10 and humanize.maybe(0.12):
            d.tap(*REEL_RAIL["save"])
            log("  ↳ save")
            humanize.wait("tap")
        elif dwell > 12 and humanize.maybe(0.1):
            log("  ↳ заглянул в комментарии")
            d.tap(*REEL_RAIL["comment"]); humanize.wait("render")
            for _ in range(random.randint(1, 3)):
                d.swipe(360, 1000, 360, random.randint(500, 750))
                humanize.wait("tap")
            d.key("KEYCODE_BACK"); humanize.wait("tap")

        d.swipe(360, 1050, 360, 320)
        humanize.wait("tap")


def scroll_feed(d: gl_device.Device, like_budget: list[int], deadline: float,
                swipes: int | None = None) -> None:
    d.tap(*NAV["home"]); humanize.wait("screen")
    n = swipes or random.randint(4, 9)
    log(f"  лента: до {n} прокруток")
    for _ in range(n):
        if time.time() >= deadline:
            return
        # Лента — самое частое место, где живой человек ставит лайк. Без этого
        # в дни с настроением «полистал ленту» бюджет лайков было некуда деть:
        # блок не получал его вовсе (BR-04, 02.09 — два блока ленты, ноль лайков).
        if like_budget[0] > 0 and humanize.maybe(0.3):
            d.sh(f"input tap {W // 2} 700"); time.sleep(0.12)
            d.sh(f"input tap {W // 2} 700")          # двойной тап по посту — лайк
            like_budget[0] -= 1
            log(f"  ↳ лайк в ленте (осталось {like_budget[0]})")
            humanize.wait("tap")
        d.swipe(360, 1000, 360, random.randint(380, 560))
        humanize.wait("read")


def view_stories(d: gl_device.Device, deadline: float) -> None:
    d.tap(*NAV["home"]); humanize.wait("screen")
    x = random.choice(STORY_X)
    log("  открыл историю в плашке")
    d.tap(x, 220); humanize.wait("render")
    segments = random.randint(2, 6)
    for i in range(segments):
        if time.time() >= deadline:
            break
        dwell = max(0.8, min(humanize.around(3.0, 1.6), remaining(deadline)))
        log(f"  история {i + 1}/{segments}: {dwell:.1f} сек")
        time.sleep(dwell)
        if humanize.maybe(0.8):
            d.tap(600, 700)                               # тап справа — дальше
        humanize.wait("tap")
    d.key("KEYCODE_BACK"); humanize.wait("tap")


def browse_explore(d: gl_device.Device, like_budget: list[int],
                   deadline: float) -> None:
    """Грид рекомендаций без ввода запроса — то, что подобрал алгоритм:
    фото, карусели и reels вперемешку, а не только видео."""
    d.tap(*NAV["search"]); humanize.wait("screen")
    for _ in range(random.randint(2, 6)):
        if time.time() >= deadline:
            return
        d.swipe(360, 1000, 360, random.randint(350, 550))
        humanize.wait("read")
    if time.time() < deadline and humanize.maybe(0.6):
        col = random.choice([120, 360, 600])
        row = random.choice([420, 620, 820, 1020])
        log("  зашёл в карточку из Explore")
        d.tap(col, row); humanize.wait("render")
        time.sleep(max(1.0, min(humanize.around(5.0, 3.0), remaining(deadline))))
        if like_budget[0] > 0 and humanize.maybe(0.35):
            d.sh(f"input tap {W // 2} 700"); time.sleep(0.12)
            d.sh(f"input tap {W // 2} 700")
            like_budget[0] -= 1
            log(f"  ↳ лайк карточки (осталось {like_budget[0]})")
            humanize.wait("tap")
        if humanize.maybe(0.3):
            d.swipe(360, 1000, 360, 400); humanize.wait("tap")
        d.key("KEYCODE_BACK"); humanize.wait("tap")
    d.key("KEYCODE_BACK")


def search_query(d: gl_device.Device, like_budget: list[int],
                 deadline: float) -> None:
    q = random.choice(QUERIES)
    log(f"  поиск: {q!r}")
    d.tap(*NAV["search"]); humanize.wait("screen")
    d.tap(360, 150); humanize.wait("tap")                 # строка поиска
    d.text(q); humanize.wait("tap")
    d.key("KEYCODE_ENTER"); humanize.wait("screen")
    for _ in range(random.randint(2, 5)):
        if time.time() >= deadline:
            break
        d.swipe(360, 1000, 360, 500); humanize.wait("read")
    # Из выдачи обычно открывают не один пост, а несколько подряд: посмотрел,
    # вернулся, открыл следующий. Один открытый пост за блок — это и было
    # причиной, по которой поисковые дни оставались почти без лайков.
    for _ in range(random.randint(1, 3)):
        if time.time() >= deadline or not humanize.maybe(0.65):
            break
        d.tap(random.choice([120, 360, 600]), random.choice([500, 800]))
        humanize.wait("render")
        time.sleep(max(1.0, min(humanize.around(6.0, 4.0), remaining(deadline))))
        # Пост открыт и досмотрен — здесь же его и лайкают. Без этой ветки дни
        # с настроением «искал по теме» давали ноль лайков при любом плане:
        # 04.09 так вышло у BR-03 и BR-08 (план по 2, факт 0) — их сеансы
        # состояли только из поиска и Explore.
        if like_budget[0] > 0 and humanize.maybe(0.45):
            d.sh(f"input tap {W // 2} 700"); time.sleep(0.12)
            d.sh(f"input tap {W // 2} 700")
            like_budget[0] -= 1
            log(f"  ↳ лайк из выдачи (осталось {like_budget[0]})")
            humanize.wait("tap")
        d.key("KEYCODE_BACK"); humanize.wait("tap")
    humanize.wait("tap")
    d.key("KEYCODE_BACK")


def visit_profile(d: gl_device.Device, like_budget: list[int], deadline: float) -> None:
    """Досмотрел ролик — заглянул к автору. Обычное поведение, которого не
    было в первой версии прогрева (тот крутился только вокруг своей ленты)."""
    watch_reels(d, like_budget, deadline, count=random.randint(1, 3))
    if time.time() >= deadline:
        return
    log("  зашёл в профиль автора")
    d.tap(*REEL_RAIL["author"]); humanize.wait("render")
    for _ in range(random.randint(1, 4)):
        if time.time() >= deadline:
            break
        d.swipe(360, 900, 360, random.randint(400, 600))
        humanize.wait("read")
    d.key("KEYCODE_BACK"); humanize.wait("tap")
    d.key("KEYCODE_BACK")


def follow_in_niche(d: gl_device.Device, query: str, deadline: float) -> bool:
    """Найти по теме аккаунт и подписаться.

    Подписка — самое «дорогое» действие в прогреве: она видна в профиле и
    остаётся надолго, поэтому ищем строго по нишевому запросу, а не жмём на
    кого попало. Кнопка ищется по тексту: на чужом профиле рядом лежат
    «Follow», «Message», «Following», и промах координатой стоил бы подписки
    не на того или отписки от уже нужного.

    ИЗВЕСТНАЯ ПРОБЛЕМА (08.09): у BR-01 и BR-08 живой прогон дважды не нашёл
    кнопку Follow. Причина — не промах координат: Instagram вместо результатов
    поиска показал капчу «Confirm you're human». Решать её отсюда нельзя и не
    нужно — при неудаче код и так тихо отступает. Но если капча не снята
    вручную, подписка на этом аккаунте не пройдёт ни разу, сколько ни пробуй.
    """
    log(f"  подписка: ищу «{query}»")
    d.tap(*NAV["search"]); humanize.wait("screen")
    d.tap(360, 150); humanize.wait("tap")
    d.text(query); humanize.wait("tap")
    d.key("KEYCODE_ENTER"); humanize.wait("screen")

    # Вкладка с аккаунтами, если она есть — в выдаче по умолчанию мешаются
    # посты и теги, а нам нужны именно профили.
    try:
        d.tap_text(text="Accounts", timeout=4)
        humanize.wait("render")
    except LookupError:
        pass

    if time.time() >= deadline:
        return False
    d.tap(360, random.choice([420, 520, 620]))     # один из первых результатов
    humanize.wait("heavy")

    try:
        pos = d.tap_text(text="Follow", timeout=6, exact=True)
    except LookupError:
        log("  кнопки Follow не нашёл — ухожу без подписки")
        d.key("KEYCODE_BACK"); humanize.wait("tap")
        d.key("KEYCODE_BACK")
        return False

    log(f"  подписался (кнопка была в {pos})")
    humanize.wait("read")
    # Полистать профиль после подписки — так делает человек, а не робот,
    # который жмёт кнопку и мгновенно исчезает.
    for _ in range(random.randint(1, 3)):
        if time.time() >= deadline:
            break
        d.swipe(360, 900, 360, random.randint(450, 650))
        humanize.wait("read")
    d.key("KEYCODE_BACK"); humanize.wait("tap")
    d.key("KEYCODE_BACK")
    return True


BLOCKS = {
    "reels":   (lambda d, lb, dl: watch_reels(d, lb, dl), 5),
    "feed":    (lambda d, lb, dl: scroll_feed(d, lb, dl), 3),
    "stories": (lambda d, lb, dl: view_stories(d, dl), 2),
    "explore": (lambda d, lb, dl: browse_explore(d, lb, dl), 2),
    "search":  (lambda d, lb, dl: search_query(d, lb, dl), 1.5),
    "profile": (lambda d, lb, dl: visit_profile(d, lb, dl), 1.5),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, help="ровно столько минут (иначе случайно из --range)")
    ap.add_argument("--range", dest="rng", default="1-5",
                    help="границы случайной длительности в минутах, например 2-8")
    ap.add_argument("--likes", type=int, help="потолок лайков (по умолчанию от длительности)")
    ap.add_argument("--phone", default=PHONE_ID)
    ap.add_argument("--plan", default=None,
                    help="JSON дневного плана из warmup_plan.py; задаёт длительность, "
                         "смесь блоков, лимиты лайков и подписок")
    a = ap.parse_args()

    plan = json.loads(a.plan) if a.plan else None

    if plan:
        minutes = plan["minutes"]
    elif a.minutes:
        minutes = a.minutes
    else:
        lo, _, hi = a.rng.partition("-")
        minutes = random.uniform(float(lo), float(hi or lo))

    if plan:
        likes = plan["likes"]
    elif a.likes is not None:
        likes = a.likes
    else:
        likes = max(1, int(minutes * random.uniform(0.4, 0.9)))
    follows_left = [plan["follows"]] if plan else [0]

    d = gl_device.Device(a.phone)
    if plan:
        log(f"телефон {d.addr}, {plan['phase']}, «{plan['mood']}» — "
            f"{minutes:.1f} мин, лайков до {likes}, подписок {plan['follows']}")
    else:
        log(f"телефон {d.addr}, прогрев {minutes:.1f} мин, лайков не больше {likes}")

    if d.current_app() != PKG:
        log("открываю Instagram")
        d.sh(f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
        humanize.wait("heavy")

    like_budget = [likes]
    deadline = time.time() + minutes * 60
    blocks = 0
    counts: dict[str, int] = {}

    while time.time() < deadline:
        left = remaining(deadline) / 60
        if plan:
            weights = {k: v for k, v in plan["weights"].items() if k in BLOCKS}
            if not plan.get("stories"):
                weights.pop("stories", None)     # на раннем этапе истории не трогаем
            name = humanize.weighted(weights or {"reels": 1})
        else:
            name = humanize.weighted({k: w for k, (_, w) in BLOCKS.items()})
        fn, _ = BLOCKS[name]
        blocks += 1
        counts[name] = counts.get(name, 0) + 1
        log(f"блок {blocks}: {name} (осталось {left:.1f} мин)")
        try:
            fn(d, like_budget, deadline)
        except LookupError as e:                         # ожидаемый элемент не нашёлся
            log(f"  не нашёл элемент, пропускаю блок: {e}")
        except Exception as e:                            # сеть моргнула — не роняем сеанс
            log(f"  сбой в блоке: {e}")
            d.connect()
        if follows_left[0] > 0 and time.time() < deadline and humanize.maybe(0.5):
            try:
                if follow_in_niche(d, plan["follow_query"], deadline):
                    follows_left[0] -= 1
            except LookupError as e:
                log(f"  подписка не вышла: {e}")
            except Exception as e:
                log(f"  подписка сорвалась: {e}")

        if time.time() < deadline:
            humanize.wait("screen")

    log("ухожу на главную и сворачиваю приложение")
    d.tap(*NAV["home"]); humanize.wait("tap")
    d.key("KEYCODE_HOME")
    mix = ", ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
    log(f"готово: {blocks} блоков ({mix}), лайков поставлено {likes - like_budget[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
