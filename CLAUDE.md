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

## EvaTeam API — что известно

- **Протокол:** JSON-RPC 2.0, `POST {base}/pub/pub_api?m=<Class>.<method>`.
  Тело: `{"jsonrpc":"2.0","method":"Class.method","params":{...},"callid":"<uuid>"}`.
  Ответ: `{"jsonrpc":"2.0","result":...}` или `{"error":{"code","message"}}`.
- **Аутентификация:** API-токен (`CmfAccessToken`, создаётся в разделе «Безопасность»).
  Способ передачи токена управляется `EVATEAM_AUTH_MODE` (см. `.env.example`) — **уточняется
  эмпирически** через `evateam/smoke.py`.
- **Модель задачи `CmfTask`** (поля подтверждены из метаданных модели):
  `responsible`, `executors`, `cmf_owner`, `waiting_for`, `deadline`, `status`
  (через `CmfStatus`/`CmfStatusCode`), `activity`, `priority`, `code`, `parent_task`, `tags`,
  `status_closed_at`.
- **Люди:** `CmfPerson` (есть `public_get_current_user`).
- **Фильтры:** UBQL/BQL (`CmfBqlFilter`, `CmfTaskFilter`).

### ⚠️ Что подтвердить на живом инстансе (Open items)

Точные имена методов и синтаксис фильтра централизованы в `evateam/tasks.py` (константы вверху
файла). Если запросы не работают против реального инстанса — правьте там. Помогает `evateam/smoke.py`.

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
