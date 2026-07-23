# CLAUDE.md — гид по проекту

Ориентир для Claude Code (и людей) при работе над этим репозиторием.

## Назначение

Бот-напоминалка о задачах из таск-трекера **EvaTeam**. Три сценария MVP:
1. Онбординг: сотрудник привязывает свой Telegram к пользователю EvaTeam (по email/логину).
2. Утренний дайджест: задачи «в работе» и «ожидают».
3. Напоминание о просрочке дедлайна.

## Ключевые архитектурные решения

- **Транспортный фасад.** Мессенджер отделён от логики. Сейчас Telegram (`transports/telegram`),
  в будущем MAX. Ядро (`core/`) и `service.py` работают с абстракцией
  `transports.base.BotTransport` и нейтральными сообщениями `OutgoingMessage`/`Button`.
  **Правило: `core/` не импортирует `aiogram` и ничего про конкретный мессенджер.**
- **Один сервисный токен.** Бот ходит в EvaTeam под одним сервис-аккаунтом и читает задачи всех
  сотрудников. Привязка «кто есть кто» — в SQLite.
- **Слои:**
  - `core/` — чистая логика и модели, без сети и БД. Легко тестируется.
  - `evateam/` — всё про API EvaTeam (JSON-RPC).
  - `storage/` — БД.
  - `transports/` — мессенджеры.
  - `service.py` — оркестратор (application layer), склеивает всё вместе.

## EvaTeam API — протокол (подтверждён на живом инстансе)

- **Эндпоинт:** `POST {base}/api/` (с завершающим слэшем!). Протокол `jsonrpc: "2.2"`.
- **Аутентификация:** `Authorization: Bearer <token>` (`CmfAccessToken`, раздел «Безопасность»).
- **Тело запроса:**
  ```json
  {"jsonrpc":"2.2","callid":"<uuid>","method":"CmfTask.list",
   "kwargs":{"filter":[["field","op",value],...],"fields":[...],"order_by":[...]},
   "flags":{"admin_mode":true}}
  ```
  Ответ: `{"result": <объект|список>}` или `{"error":{"code","message"}}`.
- **Методы:** `<Model>.list` (список) и `<Model>.get` (один объект). Используем `CmfTask.list`,
  `CmfPerson.list`.
- **filter:** список условий (И-логика). Операторы: `== != < > <= >= LIKE ("%текст%") EXISTS`.
  Связь-одиночка: `["responsible.id","==",id]`; множественная: `["executors.id","==",id]`
  (у самой связи без `.id` оператор `==` падает).
- **fields:** плоские и вложенные (`"responsible.name"`, `"executors.name"`). null-поля в ответе
  опускаются. `["**"]` — все поля.
- **flags.admin_mode=true:** сервис-аккаунт (в группе **Admins**) видит объекты всех сотрудников.
  Без него — только свои/публичные. Управляется `EVATEAM_ADMIN_MODE`.
- **Статус задачи:** поле `cache_status_type` ∈ {`OPEN`,`IN_PROGRESS`,`IN_REVIEW`,`CLOSED`}.
  Маппинг в `evateam/dto.py`: IN_PROGRESS→в работе, IN_REVIEW→ожидают, OPEN→предстоит, CLOSED→done.
- **Идентификация людей:** у реальных сотрудников `login` = email (напр. `user@example.ru`);
  у демо-пользователей `login=null`, но `email` заполнен. `find_person` ищет по login→email→name.

Все имена методов/полей централизованы в `evateam/tasks.py`. Диагностика — `evateam/smoke.py`.
Внимание: `/pub/pub_api` — это ОТДЕЛЬНЫЙ публичный шлюз (всегда анонимный), НЕ использовать.

## Запуск и проверка

- Прод: `python -m evateam_bot.main`
- Задания вручную: `python -m evateam_bot.scheduler.jobs --run digest|deadlines`
- Smoke API: `python -m evateam_bot.evateam.smoke --person <email>`
- Тесты: `pytest`

## Конвенции

- Python 3.11+, async везде, где есть I/O.
- Тексты сообщений пользователю — на русском.
- Секреты только через `.env` (не коммитить).
- Ветки: `main` (релизы) ← `dev` (интеграция) ← `feature/*`.
