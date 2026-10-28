# Источники новостей (RSS). Нерабочие ленты бот просто пропускает и пишет в лог.
# region: ru / cis / world — влияет на приоритет (Россия важнее всего).
FEEDS = [
    # Россия
    {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml", "region": "ru"},
    {"name": "РИА Новости", "url": "https://ria.ru/export/rss2/archive/index.xml", "region": "ru"},
    {"name": "Интерфакс", "url": "https://www.interfax.ru/rss.asp", "region": "ru"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/news.xml", "region": "ru"},
    {"name": "РБК", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "region": "ru"},
    {"name": "Лента.ру", "url": "https://lenta.ru/rss/news", "region": "ru"},
    # СНГ (адреса лент проверьте: если не отвечают, замените на рабочие)
    {"name": "Kazinform", "url": "https://www.inform.kz/rss/rus.xml", "region": "cis"},
    {"name": "Tengrinews", "url": "https://tengrinews.kz/news.rss", "region": "cis"},
    {"name": "БелТА", "url": "https://www.belta.by/rss/all", "region": "cis"},
    # Мир (на английском, Gemini переведёт)
    {"name": "BBC", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "region": "world"},
    {"name": "NYT", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "region": "world"},
]

# Бонус к важности новости по региону
REGION_BONUS = {"ru": 1.0, "cis": 0.5, "world": 0.0}

# Новости с этими словами бот не публикует
STOP_WORDS = [
    "erid", "на правах рекламы", "реклама", "18+", "порно", "гороскоп",
    "суицид", "самоубийств", "изнасилован", "растлен",
]
