# Источники новостей (RSS). Нерабочие ленты бот просто пропускает и пишет в лог.
# region: ru / cis / world — влияет на приоритет (Россия важнее всего).
FEEDS = [
    # Российские деловые и общественно-политические СМИ с разными редакционными подходами.
    {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml", "region": "ru", "source_group": "state"},
    {"name": "РИА Новости", "url": "https://ria.ru/export/rss2/archive/index.xml", "region": "ru", "source_group": "state"},
    {"name": "Интерфакс", "url": "https://www.interfax.ru/rss.asp", "region": "ru", "source_group": "commercial"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/news.xml", "region": "ru", "source_group": "commercial"},
    {"name": "РБК", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "region": "ru", "source_group": "commercial"},
    {"name": "Лента.ру", "url": "https://lenta.ru/rss", "region": "ru", "source_group": "commercial"},
    # Независимые русскоязычные редакции. Ленты могут быть недоступны в отдельных сетях.
    {"name": "Медуза", "url": "https://meduza.io/rss/all", "region": "ru", "source_group": "independent"},
    {"name": "Медиазона", "url": "https://zona.media/rss", "region": "ru", "source_group": "independent"},
    {"name": "The Insider", "url": "https://theins.ru/feed", "region": "ru", "source_group": "independent"},
    {"name": "BBC News Русская служба", "url": "https://feeds.bbci.co.uk/russian/rss.xml", "region": "ru", "source_group": "international"},
    {"name": "DW на русском", "url": "https://rss.dw.com/rdf/rss-ru-top", "region": "ru", "source_group": "international"},
    {"name": "Новая газета Европа", "url": "https://novayagazeta.eu/feed/rss", "region": "ru", "source_group": "independent"},
    {"name": "The Moscow Times", "url": "https://www.themoscowtimes.com/rss/news", "region": "ru", "source_group": "independent"},
    # СНГ — отдельный региональный приоритет.
    {"name": "Kazinform", "url": "https://www.inform.kz/rss/rus.xml", "region": "cis", "source_group": "regional"},
    {"name": "Tengrinews", "url": "https://tengrinews.kz/news.rss", "region": "cis", "source_group": "regional"},
    {"name": "БелТА", "url": "https://www.belta.by/rss/all", "region": "cis", "source_group": "state"},
    # Международные источники для важных мировых событий и сопоставления сообщений о России.
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "region": "world", "source_group": "international"},
    {"name": "The New York Times World", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "region": "world", "source_group": "international"},
]

# Редакционный фокус. Это правила отбора, а не указание модели поддерживать чью-либо версию событий.
EDITORIAL_POLICY = """
Главный фокус канала — события в России и события за рубежом, напрямую влияющие на жителей России.
Приоритетные темы: решения властей и их последствия, экономика и цены, права человека и суды,
регионы, общество, коррупция, свобода слова, мобилизация, армия и война России против Украины,
потери и последствия войны для людей, бюджеты и социальная политика.
Международные события без заметной связи с Россией отбирай только при высокой мировой значимости.
Не считай государственное заявление доказанным фактом только из-за статуса источника.
Сопоставляй официальные сообщения с независимыми редакциями и международными источниками, когда
они доступны. Учитывай происхождение сведений и прямо атрибутируй заявления, оценки и спорные данные.
Не уравнивай автоматически хорошо подтверждённые факты и неподтверждённые утверждения.
Антивоенная редакционная позиция означает внимание к человеческим, общественным, правовым и
экономическим последствиям войны и критическую проверку официальных заявлений; она не разрешает
выдумывать факты, скрывать значимые контраргументы или выдавать мнение за установленный факт.
""".strip()


# Бонус к важности новости по региону
REGION_BONUS = {"ru": 2.0, "cis": 0.5, "world": 0.0}

# Новости с этими словами бот не публикует
STOP_WORDS = [
    "erid", "на правах рекламы", "реклама", "18+", "порно", "гороскоп",
    "суицид", "самоубийств", "изнасилован", "растлен",
]
