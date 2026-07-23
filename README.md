# EvaTeam Task Reminder Bot

Бот напоминает сотрудникам об их задачах из таск-трекера [EvaTeam](https://docs.evateam.ru).

## Что делает (MVP)

1. **Онбординг** — сотрудник запускает бота (`/start`), вводит свой EvaTeam email или логин и
   подтверждает, что это он. Привязка `chat_id ↔ пользователь EvaTeam` сохраняется.
2. **Утренний дайджест** — каждое утро бот присылает «план дня»: задачи в работе и ожидающие.
3. **Напоминание о просрочке** — отдельно уведомляет, когда у задачи истёк срок (`deadline`).

## Архитектура

Логика отделена от мессенджера через **транспортный фасад** — сейчас Telegram, в будущем MAX
добавляется новым адаптером без изменения ядра.

```
evateam_bot/
  core/         доменная логика (без I/O): модели, дайджест, дедлайны, форматирование
  evateam/      JSON-RPC клиент EvaTeam (сервисный токен) + запросы задач/людей
  transports/   абстракция BotTransport + адаптеры (telegram/, потом max/)
  storage/      SQLite (SQLAlchemy): привязки пользователей, дедуп напоминаний
  scheduler/    APScheduler: утренний дайджест и проверка дедлайнов
  service.py    оркестрация: связывает transport + evateam + storage + core
  app.py        сборка зависимостей
  main.py       точка входа
```

Подробнее — см. [CLAUDE.md](CLAUDE.md).

## Запуск

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows; на *nix: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # заполнить токены и URL
python -m evateam_bot.main
```

### Ручной запуск заданий (для проверки)

```bash
python -m evateam_bot.scheduler.jobs --run digest
python -m evateam_bot.scheduler.jobs --run deadlines
```

### Проверка подключения к EvaTeam

```bash
python -m evateam_bot.evateam.smoke --person user@example.ru
```

## Тесты

```bash
pytest
```

## Ветки

- `main` — стабильные релизы
- `dev` — интеграционная ветка
- `feature/*` — разработка фич
