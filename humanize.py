"""Человечные паузы — общий модуль для publish.py и warmup.py.

Одинаковый ритм между действиями — самый простой признак, по которому
автоматизацию отличают от человека: живой человек никогда не листает ленту
или не подтверждает диалоги с одинаковым интервалом. Поэтому здесь не одна
пауза "от и до", а профили по типу действия, и внутри профиля повторный вызов
намеренно избегает значения, близкого к прошлому разу для этого же типа.
"""
from __future__ import annotations

import random
import time

# (мин, макс) секунд. Это не тайминги под конкретный шаг сценария, а форма
# распределения — какой вообще бывает пауза такого рода.
PROFILES: dict[str, tuple[float, float]] = {
    "tap":    (0.35, 1.3),    # между тапом и следующим действием на том же экране
    "render": (1.2, 3.2),     # экран доигрывает анимацию/подгружает список
    "screen": (2.5, 6.0),     # переход на новый полноценный экран
    "heavy":  (5.0, 11.0),    # тяжёлый переход: каталог музыки, применение эффекта
    "read":   (2.0, 7.0),     # "прочитать" список/подпись перед выбором
    "think":  (4.0, 15.0),    # решение — какой трек, какая обложка, что дальше
    "type":   (0.04, 0.11),   # между вводом фрагментов текста
}

_last: dict[str, float] = {}


def wait(kind: str, *, hesitate: float = 0.12) -> float:
    """Пауза по профилю `kind`. Возвращает фактическую длительность (для логов).

    Если выпавшее значение почти совпадает с прошлым для этого же типа —
    перебрасывается: сосед по времени не должен быть похож на соседа по
    прошлому вызову того же действия.
    """
    a, b = PROFILES[kind]
    span = b - a
    v = random.uniform(a, b)
    for _ in range(4):
        prev = _last.get(kind)
        if prev is None or abs(v - prev) > span * 0.18:
            break
        v = random.uniform(a, b)
    if random.random() < hesitate:                      # человек отвлёкся/задумался
        v += random.uniform(span * 0.6, span * 1.8)
    _last[kind] = v
    v = round(v, 2)
    time.sleep(v)
    return v


def maybe(prob: float) -> bool:
    return random.random() < prob


def weighted(options: dict[str, float]) -> str:
    """options: {метка: вес}."""
    keys = list(options.keys())
    weights = list(options.values())
    return random.choices(keys, weights=weights)[0]


def around(value: float, spread: float) -> float:
    """Число рядом с `value` в пределах ±spread — для громкости, длительности
    и прочего, что не должно быть одной и той же константой каждый раз."""
    return value + random.uniform(-spread, spread)
