"""Тонкий клиент GeeLark Open API: подпись, POST, разбор ответа."""
import hashlib, json, os, sys, time, uuid, requests
from pathlib import Path

# .env ищем рядом со скриптом, а не по прибитому домашнему пути: так же
# работает и на Mac, и в облачном чек-ауте. В облаке файла не будет вовсе —
# секреты туда приходят через настоящие переменные окружения
# claude.ai, поэтому отсутствие файла не должно быть фатальным.
ENV = Path(__file__).parent / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BASE = "https://openapi.geelark.com"
try:
    APP_ID  = os.environ["GEELARK_APP_ID"]
    API_KEY = os.environ["GEELARK_API_KEY"]
except KeyError as e:
    sys.exit(f"нет переменной окружения {e} — ни в .env, ни в окружении процесса")

def headers():
    trace = str(uuid.uuid4())
    ts    = str(int(time.time() * 1000))
    nonce = trace[:6]
    sign  = hashlib.sha256((APP_ID + trace + ts + nonce + API_KEY).encode()).hexdigest().upper()
    return {"appId": APP_ID, "traceId": trace, "ts": ts, "nonce": nonce,
            "sign": sign, "Content-Type": "application/json"}

def post(path, body=None, retries=3):
    """POST с повтором при обрыве связи.

    Без повторов одна моргнувшая сеть роняет весь прогон. Хуже того, если
    оборвётся вызов остановки телефона, тот останется работать и будет жечь
    минуты: 2026-08-31 так сгорело около 330 минут на BR-05 — прогон упал на
    `Connection reset by peer` ровно в момент остановки.
    """
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(BASE + path, headers=headers(), json=body or {}, timeout=60)
            try:
                return r.json()
            except Exception:
                return {"_httpStatus": r.status_code, "_raw": r.text[:500]}
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            if attempt < retries:
                time.sleep(2 * attempt)          # 2с, 4с — короткие обрывы переживаем
    raise last

if __name__ == "__main__":
    path = sys.argv[1]
    body = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(post(path, body), ensure_ascii=False, indent=2))


def get(path, body=None):
    """Алиас для читаемости в скриптах — API везде POST."""
    return post(path, body)
