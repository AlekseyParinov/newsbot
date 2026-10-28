import os, re, json, time, html, sys, hashlib, traceback
from datetime import datetime, timezone, timedelta

import feedparser
import requests

from config import FEEDS, REGION_BONUS, STOP_WORDS

STATE_FILE = "state.json"
UA = "Mozilla/5.0 (compatible; NewsBot/1.0)"


def env(name, default=""):
    return os.getenv(name) or default


TG_TOKEN = env("TG_BOT_TOKEN")
TG_CHAT = env("TG_CHANNEL")
TG_ADMIN = env("TG_ADMIN_ID")
PROVIDER = env("LLM_PROVIDER", "openrouter")  # openrouter | gemini
GEMINI_KEY = env("GEMINI_API_KEY")
MODEL = env("GEMINI_MODEL", "gemini-2.5-flash")
OR_KEY = env("OPENROUTER_API_KEY")
OR_MODELS = [m.strip() for m in env(
    "OPENROUTER_MODELS",
    "nvidia/nemotron-3-super-120b-a12b:free,nvidia/nemotron-3.5-lightning:free,nvidia/nemotron-3-ultra-550b-a55b:free,openrouter/free,google/gemma-4-31b-it:free",
).split(",") if m.strip()]
# дневной лимит запросов к модели (у бесплатного OpenRouter без пополнения: 50 в сутки)
DAILY_LIMIT = int(env("DAILY_LIMIT", "45" if PROVIDER == "openrouter" else "0"))
MAX_POSTS = int(env("MAX_POSTS_PER_RUN", "2"))
MAX_AGE_H = int(env("MAX_AGE_HOURS", "4"))
MIN_SOURCES = int(env("MIN_SOURCES", "1"))
SIM_THRESHOLD = 0.45
DRY_RUN = env("DRY_RUN") == "1"


class QuotaError(Exception):
    pass


# ---------- утилиты ----------
def clean(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def stems(title):
    # грубая «стемизация»: первые 5 букв слова, чтобы склеивать разные падежи
    return {w[:5] for w in re.findall(r"\w+", title.lower()) if len(w) > 3}


def sim(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def h(s):
    return hashlib.md5(s.encode()).hexdigest()[:12]


# ---------- состояние ----------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": [], "titles": []}


def save_state(state):
    state["seen"] = state["seen"][-3000:]
    state["titles"] = state["titles"][-200:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


# ---------- сбор новостей ----------
def fetch_items():
    items, now = [], datetime.now(timezone.utc)
    for feed in FEEDS:
        try:
            r = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=20)
            r.raise_for_status()
            d = feedparser.parse(r.content)
        except Exception as e:
            print(f"[warn] {feed['name']}: {e}")
            continue
        if not d.entries:
            print(f"[warn] {feed['name']}: пусто")
            continue
        for e in d.entries[:40]:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            link = e.get("link", "")
            title = clean(e.get("title"))
            if not ts or not link or not title:
                continue
            dt = datetime(*ts[:6], tzinfo=timezone.utc)
            if now - dt > timedelta(hours=MAX_AGE_H):
                continue
            items.append({
                "source": feed["name"], "region": feed["region"], "dt": dt,
                "title": title, "summary": clean(e.get("summary", ""))[:700],
                "link": link, "stems": stems(title), "id": h(link),
            })
    print(f"[info] свежих новостей: {len(items)}")
    return items


def build_clusters(items):
    clusters = []
    for it in sorted(items, key=lambda x: x["dt"], reverse=True):
        for c in clusters:
            if sim(it["stems"], c["stems"]) >= SIM_THRESHOLD:
                c["items"].append(it)
                break
        else:
            clusters.append({"stems": it["stems"], "items": [it]})
    for c in clusters:
        names = {i["source"] for i in c["items"]}
        c["n"] = len(names)
        c["score"] = c["n"] + REGION_BONUS.get(c["items"][0]["region"], 0)
        c["newest"] = max(i["dt"] for i in c["items"])
    return sorted(clusters, key=lambda c: (c["score"], c["newest"]), reverse=True)


# ---------- LLM (OpenRouter или Gemini) ----------
_budget = {"day": "", "n": 0}


def budget_init(state):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    b = state.get("budget", {})
    if b.get("day") != today:
        b = {"day": today, "n": 0}
    _budget.update(b)
    state["budget"] = _budget


def spend():
    if DAILY_LIMIT and _budget["n"] >= DAILY_LIMIT:
        raise QuotaError("дневной лимит запросов исчерпан")
    _budget["n"] += 1


def parse_json(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def _extract(data):
    if PROVIDER == "openrouter":
        return data["choices"][0]["message"]["content"]
    return data["candidates"][0]["content"]["parts"][0]["text"]


def llm_openrouter(prompt):
    """Пробуем модели по одной: если одна перегружена, берём следующую."""
    msg = prompt + "\n\nОтвечай ТОЛЬКО одним JSON-объектом, без пояснений и без ```."
    for model in OR_MODELS:
        spend()
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}"},
            json={"model": model, "temperature": 0.8,
                  "messages": [{"role": "user", "content": msg}]},
            timeout=120)
        if r.status_code in (401, 402, 403):
            print(f"[llm] {model}: HTTP {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
        if r.status_code != 200:
            print(f"[llm] {model}: HTTP {r.status_code}: {r.text[:200]}")
            time.sleep(3)
            continue
        try:
            data = r.json()
            post = parse_json(_extract(data))
        except (KeyError, IndexError, TypeError, ValueError):
            print(f"[llm] {model}: странный ответ, беру следующую")
            continue
        if post is None:
            print(f"[llm] {model}: не JSON, беру следующую")
            continue
        print(f"[llm] ответила модель: {data.get('model', model)}")
        return post
    raise QuotaError("ни одна бесплатная модель не ответила")


def llm(prompt):
    if PROVIDER == "openrouter":
        return llm_openrouter(prompt)
    for attempt in range(3):
        spend()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        r = requests.post(
            url, headers={"x-goog-api-key": GEMINI_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"}},
            timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            print(f"[llm] HTTP {r.status_code}: {r.text[:300]}")
            time.sleep(25 * (attempt + 1))
            continue
        r.raise_for_status()
        try:
            return parse_json(_extract(r.json()))
        except (KeyError, IndexError, TypeError, ValueError):
            return None
    raise QuotaError("Gemini: лимит или сбой")


def sources_block(cluster):
    parts = []
    for i in cluster["items"][:4]:
        parts.append(f"[{i['source']}] {i['title']}. {i['summary']}")
    return "\n".join(parts)


WRITE_PROMPT = """Ты редактор Telegram-канала срочных новостей. Стиль: короткие сообщения информагентства, как у каналов вроде Ateo Breaking.

Вот сообщения об одном событии из разных источников:
{src}

Напиши короткий пост на русском языке (если источник на другом языке, переведи).

ПРАВИЛА:
1. Только факты из источников. Не выдумывай цифры, имена, цитаты, причины и подробности. Без выводов, оценок и прогнозов от себя.
2. "headline": одно ёмкое законченное предложение с главным фактом, до 160 символов.
   "text": 0-2 коротких законченных предложения с важной деталью из источников. Если добавить нечего, оставь пустую строку. Весь пост не длиннее 350 символов.
3. Стиль: сухой, чёткий, как у информагентства. Без эмодзи, без сленга, без восклицаний, без вопросов, без обращения к читателю, без кликбейта. Пиши своими словами, не копируй формулировки источников.
4. Если это заявление, слух или данные одного СМИ или человека, скажи это прямо в тексте: «по данным ...», «заявил ...». Названия СМИ упоминай только так, отдельной строки «Источник» не делай и ссылок не ставь.
5. В политике не занимай сторону, только факты. О трагедиях пиши сдержанно.
6. skip=true, если новость скучная, мелкая локальная, рекламная или про сексуальное насилие и насилие над детьми.

Верни JSON: {{"skip": bool, "headline": str, "text": str}}"""

VERIFY_PROMPT = """Ты строгий фактчекер. Источники:
{src}

Пост:
{headline}
{text}

Проверь: 1) каждый факт поста подтверждается источниками, нет выдуманных цифр, имён, причин; 2) пост не искажает смысл и не вводит в заблуждение; 3) слух или заявление не поданы как установленный факт.
Верни JSON: {{"ok": bool, "problem": str}}"""


def write_post(cluster):
    post = llm(WRITE_PROMPT.format(src=sources_block(cluster)))
    if not post or post.get("skip") or not post.get("headline"):
        return None
    post["text"] = (post.get("text") or "").strip()
    time.sleep(6)
    check = llm(VERIFY_PROMPT.format(
        src=sources_block(cluster), headline=post["headline"], text=post["text"]))
    time.sleep(6)
    if not check or not check.get("ok"):
        print(f"[reject] {post['headline']} :: {(check or {}).get('problem')}")
        return None
    return post


# ---------- Telegram ----------
def esc(s):
    return html.escape(s, quote=True)


def tg_send(chat, text):
    if DRY_RUN:
        print("---- DRY RUN ----\n" + text + "\n-----------------")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": chat, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=30)
    r.raise_for_status()


def format_post(post, cluster):
    head = esc(post["headline"].strip())
    body = esc(post["text"])
    return f"<b>{head}</b>\n\n{body}" if body else head


# ---------- главный цикл ----------
def run():
    print(f"[info] провайдер: {PROVIDER}; модели: {OR_MODELS if PROVIDER == 'openrouter' else MODEL}")
    state = load_state()
    budget_init(state)
    seen = set(state["seen"])
    published_titles = [set(t) for t in state["titles"]]
    posted = 0

    clusters = build_clusters(fetch_items())
    for c in clusters:
        if posted >= MAX_POSTS:
            break
        ids = [i["id"] for i in c["items"]]
        if any(i in seen for i in ids):
            continue
        if c["n"] < MIN_SOURCES:
            continue
        if any(sim(c["stems"], t) >= SIM_THRESHOLD for t in published_titles):
            state["seen"] += ids
            continue
        text_all = " ".join(i["title"] + " " + i["summary"] for i in c["items"]).lower()
        if any(w in text_all for w in STOP_WORDS):
            state["seen"] += ids
            continue

        try:
            post = write_post(c)
        except QuotaError as e:
            print(f"[quota] {e}, останавливаюсь до следующего запуска")
            break

        state["seen"] += ids  # чтобы не пытаться снова
        if not post:
            continue
        tg_send(TG_CHAT, format_post(post, c))
        state["titles"].append(sorted(c["stems"]))
        published_titles.append(c["stems"])
        posted += 1
        print(f"[ok] {post['headline']}")

    save_state(state)
    print(f"[done] опубликовано: {posted}")


if __name__ == "__main__":
    if env("PAUSED") == "1":
        print("Пауза (PAUSED=1)")
        sys.exit(0)
    llm_key = OR_KEY if PROVIDER == "openrouter" else GEMINI_KEY
    if not (TG_TOKEN and TG_CHAT and llm_key) and not DRY_RUN:
        sys.exit("Не заданы TG_BOT_TOKEN / TG_CHANNEL / ключ нейросети (OPENROUTER_API_KEY или GEMINI_API_KEY)")
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        print(err)
        if TG_ADMIN and not DRY_RUN:
            try:
                tg_send(TG_ADMIN, "⚠️ Ошибка бота:\n" + err[-1500:])
            except Exception:
                pass
        sys.exit(1)
            
