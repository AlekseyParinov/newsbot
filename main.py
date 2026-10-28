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
    "meta-llama/llama-3.3-70b-instruct:free,mistralai/mistral-small-3.1-24b-instruct:free,google/gemma-4-31b-it:free",
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


def llm(prompt):
    attempts = 2 if PROVIDER == "openrouter" else 3
    for attempt in range(attempts):
        spend()
        if PROVIDER == "openrouter":
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OR_KEY}"},
                json={"models": OR_MODELS, "temperature": 0.8,
                      "messages": [{"role": "user", "content":
                                    prompt + "\n\nОтвечай ТОЛЬКО одним JSON-объектом, без пояснений и без ```."}]},
                timeout=120)
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
            r = requests.post(
                url, headers={"x-goog-api-key": GEMINI_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"}},
                timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        try:
            data = r.json()
            if PROVIDER == "openrouter":
                txt = data["choices"][0]["message"]["content"]
            else:
                txt = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        return parse_json(txt)
    raise QuotaError("LLM: лимит или сбой")


def sources_block(cluster):
    parts = []
    for i in cluster["items"][:4]:
        parts.append(f"[{i['source']}] {i['title']}. {i['summary']}")
    return "\n".join(parts)


WRITE_PROMPT = """Ты редактор новостного Telegram-канала для подростков и молодёжи (14-25 лет). Стиль: дерзкий, живой, как в каналах «Рифмы и Панчи».

Вот сообщения об одном событии из разных источников:
{src}

Задача: напиши пост на русском языке (если источник на другом языке, переведи).

ЖЁСТКИЕ ПРАВИЛА:
1. Используй ТОЛЬКО факты из источников. Не выдумывай цифры, имена, цитаты, причины.
2. Заголовок: до 90 символов, громкий, с одним эмодзи в начале, можно рифму или панч. Но он не должен обещать то, чего нет в тексте.
3. Текст: 2-3 коротких предложения простым языком, лёгкий сленг можно, мат нельзя. Если уместно, добавь одну фразу «что это значит для тебя».
4. Если тема тяжёлая (война, теракты, гибель людей, катастрофы, преступления, болезни): tone="serious", никаких шуток, сленга и панчей, нейтральный тон, эмодзи только нейтральный (например ⚠️ или 📰).
5. В политике не занимай сторону и не оценивай, только факты.
6. skip=true, если новость скучная, мелкая локальная, рекламная или про насилие над детьми и сексуальные преступления.
7. Названия источников в текст не вставляй.

Верни JSON: {{"skip": bool, "tone": "fun" или "serious", "headline": str, "text": str}}"""

VERIFY_PROMPT = """Ты строгий фактчекер. Источники:
{src}

Пост:
{headline}
{text}

Проверь: 1) каждый факт поста подтверждается источниками, нет выдуманных цифр, имён, причин; 2) заголовок не вводит в заблуждение; 3) если тема тяжёлая (смерти, война, теракты, катастрофы), в посте нет шуток и панчей.
Верни JSON: {{"ok": bool, "problem": str}}"""


def write_post(cluster):
    post = llm(WRITE_PROMPT.format(src=sources_block(cluster)))
    if not post or post.get("skip") or not post.get("headline") or not post.get("text"):
        return None
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
    src = cluster["items"][0]
    return (f"<b>{esc(post['headline'])}</b>\n\n{esc(post['text'])}\n\n"
            f"<i>Источник: <a href=\"{esc(src['link'])}\">{esc(src['source'])}</a></i>")


# ---------- главный цикл ----------
def run():
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
