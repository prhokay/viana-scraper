# Events Scraper — Viana do Castelo

Python-модуль для збору подій у регіоні Viana do Castelo (Португалія).
Призначений для інтеграції в **OpenClaw Bot** як окремий provider подій.

---

## Зміст

1. [Архітектура](#1-архітектура)
2. [Структура проекту](#2-структура-проекту)
3. [Встановлення](#3-встановлення)
4. [Запуск](#4-запуск)
5. [Інтеграція в OpenClaw Bot](#5-інтеграція-в-openclaw-bot)
6. [Приклади використання](#6-приклади-використання)
7. [Приклад JSON output](#7-приклад-json-output)
8. [Ризики та слабкі місця](#8-ризики-та-слабкі-місця)
9. [Рекомендації](#9-рекомендації)

---

## 1. Архітектура

### Загальна схема

```
[scrapers]  →  [normalizer]  →  [deduplicator]  →  [storage]
    ↑                                                    ↓
[event_service]  ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
    ↓
[openclaw_adapter]  →  [Telegram Bot / CLI / cron / HTTP API]
```

### Рівні

| Рівень | Відповідальність |
|--------|-----------------|
| `scrapers/` | Збір даних з конкретного джерела. Повертають `List[Event]`. Незалежні одне від одного. |
| `normalizer.py` | Очистка тексту, авто-категоризація, нормалізація полів. |
| `deduplicator.py` | Hard dedup (по id), soft dedup (схожа назва + дата). |
| `storage.py` | SQLite або JSON. Upsert, фільтрація, експорт. |
| `services/event_service.py` | Оркестрація всього вище. Публічний API для бота. |
| `integrations/openclaw_adapter.py` | Адаптер між EventService і Telegram-ботом. |

### Інтеграція в OpenClaw Bot — три патерни

**Патерн A — Бібліотека** (рекомендований для MVP):
```
OpenClaw Bot
  └── from integrations.openclaw_adapter import EventsAdapter
       └── EventsAdapter.handle_command("/events")
```
- Модуль живе всередині бота (один процес)
- Простіше деплоїти, немає мережевих залежностей
- Мінус: якщо scraper зависне, бот теж підвисне (вирішується через threading/asyncio)

**Патерн B — Мікросервіс** (для production):
```
OpenClaw Bot  →  HTTP GET /events  →  Events Service (FastAPI)
                                          └── DB (SQLite/Postgres)
```
- Окремий Docker-контейнер або процес
- Бот не залежить від часу збору даних
- Запустити: `python main.py --serve`

**Патерн C — CLI + cron**:
```
cron: python main.py --run-scrapers (кожні 6 годин)
Bot: читає з DB через EventsAdapter(auto_refresh=False)
```
- Найпростіший для production: cron оновлює, бот лише читає

---

## 2. Структура проекту

```
events_scraper/
├── main.py                     # CLI entry point
├── config.py                   # Settings (pydantic-settings + .env)
├── models.py                   # Event dataclass (Pydantic)
├── normalizer.py               # Очистка та категоризація
├── deduplicator.py             # Дедублікація
├── storage.py                  # SQLite / JSON storage
├── .env.example                # Приклад конфігурації
├── requirements.txt
│
├── scrapers/
│   ├── base.py                 # BaseScraper: retry, timeout, logging
│   ├── viralagenda.py          # HTML scraper
│   ├── aquiha.py               # HTML scraper
│   ├── eventbrite.py           # REST API (потрібен API key)
│   └── bandsintown.py          # REST API (безкоштовно)
│
├── services/
│   └── event_service.py        # Оркестрація, публічний API
│
├── integrations/
│   └── openclaw_adapter.py     # Telegram bot adapter + FastAPI stub
│
└── utils/
    ├── dates.py                # Парсинг дат (dateparser + PT fallback)
    ├── logger.py               # Логування (console + file)
    └── text.py                 # Очистка тексту, ціни, URL
```

---

## 3. Встановлення

```bash
# 1. Клонуємо або копіюємо папку
cd events_scraper

# 2. Створюємо venv
python -m venv .venv
source .venv/bin/activate       # Linux/Mac
.venv\Scripts\activate          # Windows

# 3. Встановлюємо залежності
pip install -r requirements.txt

# 4. Налаштовуємо .env
cp .env.example .env
# відредагуйте .env — мінімум нічого не треба, Eventbrite опціонально
```

---

## 4. Запуск

### Локально (один раз)
```bash
# Запустити всі scrapers, зберегти в DB, показати summary
python main.py

# Або явно
python main.py --run-scrapers

# Показати події на 7 днів
python main.py --events --days 7

# Тільки концерти
python main.py --events --category concert

# Тільки бігові події на 90 днів
python main.py --events --category running --days 90

# Тільки нові (не збережені раніше)
python main.py --new

# Отримати результат як JSON
python main.py --events --json > events.json

# Експортувати DB → JSON файл
python main.py --export output.json

# Видалити старі події (старше 90 днів)
python main.py --clean-old --days 90
```

### По cron (Linux)
```bash
# Оновлення кожні 6 годин
0 */6 * * * cd /home/user/events_scraper && /home/user/events_scraper/.venv/bin/python main.py --run-scrapers

# Щоранку о 8:00 — очищення старих подій
0 8 * * * cd /home/user/events_scraper && /home/user/events_scraper/.venv/bin/python main.py --clean-old --days 90
```

### HTTP API (мікросервіс)
```bash
pip install fastapi uvicorn
# Розкоментуй app = _create_fastapi_app() в openclaw_adapter.py
python main.py --serve
# або
uvicorn integrations.openclaw_adapter:app --host 0.0.0.0 --port 8000
```

---

## 5. Інтеграція в OpenClaw Bot

### Крок за кроком

**1. Скопіювати модуль у проект бота:**
```
openclaw_bot/
  ├── bot.py
  ├── events/           ← скопіювати весь цей модуль сюди
  │   ├── main.py
  │   ├── config.py
  │   └── ...
```

**2. Встановити залежності:**
```bash
pip install -r events/requirements.txt
```

**3. Додати в .env бота:**
```
EVENTBRITE_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_channel_id
```

**4. Підключити в bot.py (telebot / pyTelegramBotAPI):**
```python
import sys
sys.path.insert(0, "events")

from integrations.openclaw_adapter import EventsAdapter

adapter = EventsAdapter(auto_refresh=False)  # cron оновлює, бот читає

@bot.message_handler(commands=["events", "concerts", "running", "weekend"])
def handle_events(message):
    command = message.text.split()[0]        # /events, /concerts, etc.
    args = message.text[len(command):].strip()
    events = adapter.handle_command(command, args=args)
    text = adapter.format_for_telegram(events)
    bot.send_message(message.chat.id, text, parse_mode="MarkdownV2")
```

**5. Підключити в bot.py (aiogram 3.x):**
```python
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from integrations.openclaw_adapter import EventsAdapter

router = Router()
adapter = EventsAdapter()

@router.message(Command("events", "concerts", "running", "weekend", "new"))
async def handle_events(message: Message):
    events = adapter.handle_command(message.text.split()[0])
    text = adapter.format_for_telegram(events)
    await message.answer(text, parse_mode="MarkdownV2")
```

**6. Планувальник для Telegram-розсилки (APScheduler):**
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("interval", hours=6)
async def refresh_and_notify():
    await adapter.notify_new_events_async(bot, chat_id=CHAT_ID)

scheduler.start()
```

---

## 6. Приклади використання

```python
from services.event_service import EventService

service = EventService()

# Отримати всі події на 7 днів (з DB)
events = service.get_events(days=7)

# Отримати тільки концерти на 30 днів
concerts = service.get_concerts(days=30)

# Отримати тільки бігові події на 90 днів
running = service.get_running_events(days=90)

# Тільки нові події (відносно попереднього запуску)
new_events = service.get_new_events()

# Запустити всі scrapers і зберегти
all_events = service.run_all_scrapers(save=True)

# Фільтрація in-memory
filtered = service.filter_events(
    all_events,
    days=14,
    category="festival",
    city="Viana do Castelo",
)

# Вихідні (цю суботу-неділю)
weekend = service.get_weekend_events()

# Зберегти та отримати JSON
service.save_events(events)
service.export_json("output.json")

# Отримати як JSON рядок
import json
json_str = json.dumps([e.to_dict() for e in events], ensure_ascii=False, indent=2)
```

---

## 7. Приклад JSON output

```json
[
  {
    "id": "a3f8c21b9d4e7f01",
    "title": "Trail das Neves — Corrida de Montanha",
    "date": "2025-03-22",
    "time": "09:00",
    "datetime_iso": "2025-03-22T09:00:00",
    "city": "Viana do Castelo",
    "region": "Viana do Castelo",
    "venue": "Parque Natural do Gerês",
    "address": "EN 308, Arcos de Valdevez",
    "category": "running",
    "tags": ["trail", "montanha", "corrida"],
    "short_description": "Trail de 25km pelas serras do Alto Minho. Inscrições abertas.",
    "full_description": null,
    "source_name": "viralagenda",
    "source_url": "https://www.viragenda.pt/evento/trail-das-neves-2025",
    "image_url": "https://www.viragenda.pt/images/trail-das-neves.jpg",
    "price": 15.0,
    "currency": "EUR",
    "event_type": "physical",
    "scraped_at": "2025-03-17T08:00:00"
  },
  {
    "id": "b9e1d43a27c56f89",
    "title": "Noite de Fado — Casa do Fado",
    "date": "2025-03-21",
    "time": "21:30",
    "datetime_iso": "2025-03-21T21:30:00",
    "city": "Viana do Castelo",
    "region": "Viana do Castelo",
    "venue": "Casa do Fado de Viana",
    "address": "Rua da Bandeira 123, Viana do Castelo",
    "category": "concert",
    "tags": ["fado", "musica", "ao vivo"],
    "short_description": "Noite de fado com Ana Moura e convidados especiais.",
    "full_description": null,
    "source_name": "eventbrite",
    "source_url": "https://www.eventbrite.pt/e/noite-de-fado-123456",
    "image_url": "https://img.evbuc.com/fado-viana.jpg",
    "price": 12.5,
    "currency": "EUR",
    "event_type": "physical",
    "scraped_at": "2025-03-17T08:00:00"
  }
]
```

---

## 8. Ризики та слабкі місця

### ViralAgenda і AquiHá — HTML scrapers

| Ризик | Вірогідність | Вплив | Вирішення |
|-------|-------------|-------|-----------|
| Зміна HTML-структури | Висока | Scraper повертає 0 подій | Моніторинг, сповіщення, оновлення селекторів |
| Антибот-захист (rate limit, CAPTCHA) | Середня | HTTP 429 / блокування IP | Збільшити delay, ротація User-Agent, проксі |
| JavaScript-рендеринг | Середня | Порожній HTML | Перейти на Playwright для конкретного сайту |
| Нестабільні дати (без року) | Висока | Неправильний рік | dateparser + `PREFER_DATES_FROM: future` |
| Неповні поля (немає venue, ціни) | Висока | null у моделі | Всі поля Optional, graceful handling |
| Пагінація (не всі події з 1 сторінки) | Середня | Пропущені події | Цикл по сторінках (реалізовано, max 5) |

### Eventbrite API

| Ризик | Вірогідність | Вплив | Вирішення |
|-------|-------------|-------|-----------|
| Зміна API / deprecation | Низька | Scraper відключається | Офіційне API, стежити за changelog |
| Ліміт запитів (free tier ~1000/day) | Середня | HTTP 429 | Кешування, рідше оновлення |
| Мало подій для маленького міста | Висока | Мало результатів | Збільшити radius, шукати по регіону |

### Bandsintown API

| Ризик | Вірогідність | Вплив | Вирішення |
|-------|-------------|-------|-----------|
| Undocumented API, може зникнути | Середня | Scraper відключається | Graceful fallback (повертає []) |
| Тільки концерти, не загальні події | — | Обмежений scope | Використовувати разом з іншими |
| Sparse data для малих міст | Висока | Мало результатів | Пошук по найближчих містах |

### Загальні ризики

| Ризик | Вирішення |
|-------|-----------|
| Дублікати між джерелами | Hard + soft dedup (реалізовано) |
| Нові події = старі але оновлені | ID-based dedup стабільний, бо базується на URL |
| Зберігання застарілих подій | `delete_old_events(days=90)` |
| Неправильна категорія | Keyword matching покриває ~80% випадків; можна доповнити ML |

---

## 9. Рекомендації

### MVP (один вечір)

Мінімальний варіант, який працює завтра:

1. Запустити тільки **Bandsintown** (не потребує API key) і **Eventbrite** (з key)
2. Зберігати в JSON (без SQLite)
3. Підключити в бот як бібліотеку (Патерн A)
4. Telegram-команди: `/events`, `/concerts`, `/running`
5. Cron кожні 12 годин

```python
# MVP bot handler (telebot)
from integrations.openclaw_adapter import EventsAdapter
adapter = EventsAdapter()

@bot.message_handler(commands=["events"])
def cmd_events(msg):
    events = adapter.handle_command("/events", args="7")
    bot.send_message(msg.chat.id, adapter.format_for_telegram(events), parse_mode="MarkdownV2")
```

### Production

- [ ] Перейти на **SQLite → Postgres** (тільки замінити драйвер у `storage.py`)
- [ ] Додати **Playwright** для ViralAgenda/AquiHá якщо є JS-рендеринг
- [ ] **Моніторинг**: якщо scraper повернув 0 подій — alert в Telegram admin-чат
- [ ] **Кеш**: `functools.lru_cache` або Redis для `get_events()` (TTL 1 год)
- [ ] **Tests**: pytest для `normalizer`, `deduplicator`, `storage`
- [ ] **Docker**: окремий контейнер для scraper-сервісу

### Telegram notifications для нових забігів

```python
# Тільки нові бігові події:
from services.event_service import EventService
from models import EventCategory

service = EventService()
known_ids = service.storage.get_known_ids()
fresh = service.run_all_scrapers(save=False)

new_running = [
    e for e in fresh
    if e.id not in known_ids and e.category == EventCategory.RUNNING
]

if new_running:
    service.save_events(new_running)
    # відправити в Telegram...
```

### Кеш (простий варіант)

```python
import functools
import time

_cache = {}

def get_events_cached(days=7, ttl=3600):
    key = f"events_{days}"
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < ttl:
            return data
    result = service.get_events(days=days)
    _cache[key] = (result, time.time())
    return result
```

### Розширення на інші міста Португалії

```python
# config.py — додати:
EVENTBRITE_LOCATION = "Braga, Portugal"  # або Porto, Lisboa

# scrapers/viralagenda.py — параметризувати:
SEARCH_URL = f"https://www.viragenda.pt/agenda/{city_slug}"

# EventService — додати параметр city:
service.get_events(days=7, city="Braga")
```

Архітектура вже підтримує мультиміський пошук через поле `city` в Event і фільтрацію в `filter_events()`.
