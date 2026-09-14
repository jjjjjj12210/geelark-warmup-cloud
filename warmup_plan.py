"""План прогрева: что именно аккаунт делает сегодня.

Зачем отдельным модулем. Прежний прогрев был честным, но однообразным: каждый
заход — та же смесь блоков со случайной длительностью. У живого человека не
так. Он не открывает приложение ровно каждый день, в первые дни после
регистрации ведёт себя осторожнее, чем через две недели, и в разные дни делает
разное: то залипает в рилсах, то листает истории, то ищет что-то по теме.

Здесь три источника непохожести:

1. **Возраст аккаунта.** Новый аккаунт, который в первый же день лайкает
   двадцать постов и на кого-то подписывается, выглядит хуже, чем тот, что
   неделю просто смотрел. Поэтому действия открываются постепенно.
2. **Настроение дня.** Каждый день аккаунту выпадает своя манера: «залип в
   рилсах», «зашёл на минуту», «искал по теме» и так далее.
3. **Расхождение между аккаунтами.** Зерно случайности собирается из имени
   аккаунта и даты, поэтому в один и тот же день девять аккаунтов ведут себя
   по-разному — но повторный запуск в тот же день даёт тот же план, и случайно
   «прогреть дважды» не выйдет.

День недели скрипт берёт из системных часов машины — помнить его не требуется.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date

# Тематика проекта — Procreate и цифровой рисунок. Всё, что аккаунт ищет,
# смотрит и на кого подписывается, должно лежать вокруг неё: аккаунт про кисти,
# внезапно листающий рецепты, выглядит собранным наспех.
QUERIES = [
    "procreate brushes", "procreate tutorial", "digital art", "ipad lettering",
    "sketchbook art", "procreate tips", "brush pack procreate", "digital painting",
    "character design", "line art procreate", "procreate art", "ipad drawing",
]

# Запросы, по которым ищем, на кого подписаться. Уже, чем QUERIES: подписка
# должна попадать в нишу точнее, чем просто просмотр.
FOLLOW_QUERIES = [
    "procreate artist", "procreate brushes", "digital artist", "procreate tutorial",
    "ipad art", "brush designer",
]

PHASES = [
    # (до какого дня, название, что открыто)
    (3,  "осматривается", dict(likes=(0, 1), follows=0, stories=False, saves=False)),
    (8,  "осваивается",   dict(likes=(1, 3), follows=0, stories=True,  saves=True)),
    (14, "обживается",    dict(likes=(2, 4), follows=1, stories=True,  saves=True)),
    (999, "живёт",        dict(likes=(3, 6), follows=1, stories=True,  saves=True)),
]

# Настроения дня: набор блоков и их веса. Ключи совпадают с блоками warmup.py.
MOODS = {
    "залип в рилсах":   {"reels": 8, "profile": 2, "feed": 1},
    "полистал ленту":   {"feed": 6, "reels": 3, "stories": 2},
    "смотрел истории":  {"stories": 6, "feed": 3, "reels": 2},
    "искал по теме":    {"search": 5, "explore": 4, "profile": 2},
    "зашёл на минуту":  {"reels": 5, "feed": 3},
}


def _rng(account: str, day: date) -> random.Random:
    """Свой генератор на пару «аккаунт + день»: аккаунты расходятся между собой,
    а повторный запуск в тот же день даёт тот же план."""
    seed = hashlib.sha256(f"{account}|{day.isoformat()}".encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def phase_for(age_days: int) -> tuple[str, dict]:
    for limit, name, rules in PHASES:
        if age_days <= limit:
            return name, rules
    return PHASES[-1][1], PHASES[-1][2]


def plan_for(account: str, age_days: int, day: date | None = None) -> dict:
    """Что аккаунт делает сегодня. Возвращает готовый набор параметров сеанса
    либо `skip=True`, если сегодня он в приложение не заходит."""
    day = day or date.today()
    r = _rng(account, day)
    phase_name, rules = phase_for(age_days)

    # Живой человек не открывает приложение каждый божий день. По выходным
    # заходит охотнее, в будни чаще пропускает.
    weekend = day.weekday() >= 5
    skip_chance = 0.18 if weekend else 0.28
    if r.random() < skip_chance:
        return {"skip": True, "phase": phase_name, "reason": "сегодня не заходит"}

    mood = r.choice(list(MOODS))
    if mood == "зашёл на минуту":
        minutes = round(r.uniform(0.7, 1.6), 1)
    else:
        minutes = round(r.uniform(1.5, 4.5) * (1.25 if weekend else 1.0), 1)

    lo, hi = rules["likes"]
    likes = r.randint(lo, hi)
    # Потолок лайков привязан к длительности: за минуту человек физически не
    # успеет осмысленно лайкнуть пятерых. Без этого короткие заходы «зашёл на
    # минуту» получали полный дневной лимит и выглядели как автомат.
    likes = min(likes, max(1, int(minutes * 1.2)))
    # Подписка — событие редкое даже когда она «разрешена»: человек не
    # подписывается каждый день.
    follows = 1 if (rules["follows"] and r.random() < 0.35) else 0

    return {
        "skip": False,
        "phase": phase_name,
        "mood": mood,
        "minutes": minutes,
        "likes": likes,
        "follows": follows,
        "stories": rules["stories"],
        "saves": rules["saves"],
        "weights": MOODS[mood],
        "query": r.choice(QUERIES),
        "follow_query": r.choice(FOLLOW_QUERIES),
    }


def week_preview(account: str, age_days: int, start: date | None = None) -> list[dict]:
    """План на неделю вперёд — чтобы посмотреть глазами, что получится."""
    start = start or date.today()
    out = []
    for i in range(7):
        d = date.fromordinal(start.toordinal() + i)
        p = plan_for(account, age_days + i, d)
        p["date"] = d
        out.append(p)
    return out


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="demo")
    ap.add_argument("--age", type=int, default=1, help="возраст прогрева в днях")
    ap.add_argument("--week", action="store_true", help="показать неделю вперёд")
    a = ap.parse_args()
    if a.week:
        RU = ["пн","вт","ср","чт","пт","сб","вс"]
        for p in week_preview(a.account, a.age):
            d = p.pop("date")
            if p["skip"]:
                print(f"  {RU[d.weekday()]} {d.strftime('%d.%m')}  —  не заходит")
            else:
                print(f"  {RU[d.weekday()]} {d.strftime('%d.%m')}  {p['minutes']:>4} мин  "
                      f"{p['mood']:<18} лайков {p['likes']}, подписок {p['follows']}  [{p['phase']}]")
    else:
        print(json.dumps(plan_for(a.account, a.age), ensure_ascii=False, indent=2, default=str))
