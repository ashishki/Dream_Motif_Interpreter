# Task Graph — Dream Motif Interpreter Phase 16

Version: 1.1
Last updated: 2026-04-25
Status: Active — source: Тест 4 (25.04.26)

## 1. Purpose

Phase 16 addresses defects and feature requests from Тест 4 (25.04.26).
Two priorities: (1) критичный баг — бот выдаёт несуществующие фрагменты снов;
(2) качество поиска — нерелевантная маршрутизация и слабый семантический recall.
Плюс пять UX-улучшений.

## 2. Defects

D1 (P0): Бот выдаёт несуществующие фрагменты снов.
  Root: Модель генерирует правдоподобный текст, не присутствующий в результатах
  инструментов. System prompt запрещает это, но запрет недостаточно строгий
  и модель его игнорирует при запросах "дай ещё" или при низкой релевантности.

D2 (P1): Поиск по "упоминается X" не находит семантически близкие результаты.
  Root: System prompt направляет запросы с "упоминается" к search_dreams_exact
  (точный SQL full-text). "Рождественское песнопение" не содержит слово
  "молитва" буквально — exact search даёт 0 результатов. Нужен семантический
  поиск или fallback.

D3 (P1): Поиск по мотиву ("религиозные сюжеты") пропускает очевидные сны.
  Root: Модель формулирует один поисковый запрос и не повторяет поиск с
  альтернативными формулировками при слабых результатах. Религиозный сон
  без слова "религия" не попадает в выдачу.

## 3. Feature Requests

F1 (P1): Сообщение об обработке голосового → на русский язык.
F2 (P1): Индикатор обработки для текстовых запросов.
F3 (P2): Уведомление о завершении синхронизации добавленного источника.
F4 (P2): Добавление заметок к записанным снам ("note: текст заметки").
F5 (P2): Emoji-реакции Telegram для качественной оценки ответов.
  Используем нативные MessageReactionUpdated (работает в приватном чате).
  Инфраструктура строится сейчас; семантика emoji — после получения
  списка от пользователя.

## 4. Honest Scope Assessment

D1 — prompt hardening. Нет архитектурных изменений. ✅ DONE 2026-04-25.

D2 — prompt routing fix + fallback в tools.py. ✅ DONE 2026-04-25.
  Fallback реализован: exact=0 → автоматический semantic search.

D3 — prompt: модель пробует 2-3 запроса при мотивном поиске. ✅ DONE 2026-04-25.
  НЕ снижать RETRIEVAL_THRESHOLD (0.20 уже низкий, снижение добавит шум).

F1, F2 — тривиальные изменения в telegram/__main__.py. 1 commit.

F3 — требует изменений в двух слоях: (1) при trigger_sync сохранять
  chat_id в Redis; (2) воркер после завершения ingest отправляет
  сообщение через Bot API. Средняя сложность, не касается основной логики.

F4 — требует миграции БД и нового инструмента. Принцип чистоты:
  НЕ добавлять поле notes к DreamEntry — это смешает источник с заметками.
  Создать отдельную модель DreamNote с FK на dream_id. Средняя сложность.

F5 — инфраструктура (модель + хендлер) независима от семантики emoji.
  Строим сейчас: MessageReaction в БД, хендлер MessageReactionUpdated в боте.
  Семантическую интерпретацию добавим когда пользователь предоставит список.

---

## WS-16.1: Жёсткий запрет на галлюцинации ✅ DONE 2026-04-25

Owner:      codex
Phase:      16
Type:       prompt
Priority:   P0

Objective:
  Модель никогда не должна цитировать или пересказывать текст снов,
  которого нет в полях chunk_text / quote / fragment_text результатов
  инструментов.

Delivered:
  - Новый раздел "## Search Grounding Rules" в SYSTEM_PROMPT.
  - Правило абсолютное: не нарушается даже при "дай ещё".
  - При отсутствии результатов: «Больше совпадений в архиве не найдено.»

Files changed:
  - app/assistant/prompts.py

---

## WS-16.2: Фикс маршрутизации поиска + fallback ✅ DONE 2026-04-25

Owner:      codex
Phase:      16
Type:       prompt + tools
Priority:   P1

Objective:
  "упоминается X" → semantic search, не exact.
  search_dreams_exact только для буквальных цитат.
  Fallback: exact=0 → автоматический semantic search.

Delivered:
  - prompts.py: routing rule переписан — exact только для verbatim-цитат,
    semantic для всего остального включая "упоминается".
  - tools.py: если exact вернул 0 → вызывается search_dreams,
    результат помечен "Exact match not found. Semantic search results:".

Files changed:
  - app/assistant/prompts.py
  - app/assistant/tools.py

---

## WS-16.3: Поиск по мотиву — многозапросная стратегия ✅ DONE 2026-04-25

Owner:      codex
Phase:      16
Type:       prompt
Priority:   P1

Objective:
  При широком мотивном запросе — минимум 2-3 вызова search_dreams
  с разными формулировками, объединить по dream_id.

Delivered:
  - prompts.py: правило обязывает делать 2-3 вызова search_dreams
    с разными ключевыми словами для мотивных/тематических запросов.
  - Пример для "религиозные сюжеты" включён прямо в промпт.

Files changed:
  - app/assistant/prompts.py

---

## WS-16.4: Русский язык для сообщений обработки ✅ DONE 2026-04-25

Owner:      codex
Phase:      16
Type:       telegram bot
Priority:   P1
Effort:     XS (< 30 минут)

Objective:
  Все processing-сообщения в Telegram боте на русском.
  Добавить typing-индикатор для текстовых запросов.

Acceptance-Criteria:
  - AC-1: Голосовое сообщение: "Обрабатываю голосовое сообщение..."
  - AC-2: Текстовый запрос: sendChatAction(action="typing") перед отправкой в LLM.
  - AC-3: typing повторяется каждые 4 сек пока идёт обработка.

Files:
  - app/telegram/__main__.py

---

## WS-16.5: Уведомление о завершении синхронизации ✅ DONE 2026-04-25

Owner:      codex
Phase:      16
Type:       telegram bot + worker
Priority:   P2
Effort:     M (4-6 часов)

Objective:
  Бот пишет в чат когда синхронизация нового источника завершена.

Design:
  1. При trigger_sync: сохранить в Redis sync_notify:{job_id} = chat_id, TTL 1 час.
  2. В app/workers/ingest.py после завершения: читать Redis,
     если есть chat_id → Bot API sendMessage.

Acceptance-Criteria:
  - AC-1: "Синхронизация завершена: [название]. Добавлено N записей."
  - AC-2: Уведомление приходит один раз, ключ Redis удаляется.
  - AC-3: Ошибка sync → "Синхронизация не удалась: [причина]."
  - AC-4: Нет chat_id → молча пропустить.

Files:
  - app/assistant/tools.py
  - app/assistant/facade.py
  - app/workers/ingest.py
  - app/shared/redis.py (хелпер sync-notify)

---

## WS-16.6: Заметки к записанным снам ✅ DONE 2026-04-25

Owner:      codex
Phase:      16
Type:       model + migration + tool
Priority:   P2
Effort:     M (4-6 часов)

Objective:
  Пользователь добавляет заметку к сну командой "note: текст".
  Хранится отдельно от raw_text — DreamEntry immutable.

Design:
  DreamNote schema:
    id: UUID PK
    dream_id: UUID FK → dream_entries.id
    text: str
    source: str (default "telegram")
    created_at: datetime

  В Google Doc: "[Note дд.мм.гг]: текст заметки" под записью сна.

Acceptance-Criteria:
  - AC-1: Инструмент add_dream_note(dream_id?, note_text).
  - AC-2: Заметка в БД (таблица dream_notes).
  - AC-3: Заметка в Google Doc под сном.
  - AC-4: get_dream возвращает notes в DreamDetail.
  - AC-5: Миграция alembic.
  - AC-6: Паттерн "note: текст" автоматически вызывает инструмент.

Files (новые):
  - app/models/note.py
  - alembic/versions/XXX_add_dream_notes.py

Files (изменённые):
  - app/assistant/facade.py
  - app/assistant/tools.py
  - app/services/gdocs_client.py
  - app/assistant/prompts.py

---

## WS-16.7: Emoji-реакции — инфраструктура ✅ DONE 2026-04-25

Owner:      codex
Phase:      16
Type:       model + migration + telegram bot
Priority:   P2
Effort:     S (2-3 часа)

Objective:
  Принимать нативные Telegram-реакции (MessageReactionUpdated) на сообщения
  бота и сохранять в БД. Семантика emoji добавляется позже.

  Решение: нативные реакции Telegram.
  Обоснование: приватный чат с ботом — MessageReactionUpdated работает
  без прав администратора. Самый natural UX для Telegram.
  Ограничение: Telegram разрешает реакции только из своего набора (~50 emoji).
  Пользователь выбирает emoji из этого набора — будет передан список.

Design:
  MessageReaction schema:
    id: UUID PK
    message_id: int (Telegram message_id бота)
    chat_id: int
    emoji: str (unicode emoji)
    created_at: datetime

  Хендлер: bot.add_handler(MessageReactionHandler(handle_reaction)).
  Бот должен иметь allowed_updates=["message", "message_reaction"].

  Семантическая интерпретация (emoji → качественная оценка):
    Добавляется как отдельный модуль после получения списка от пользователя.
    До тех пор — хранить сырые реакции без интерпретации.

Acceptance-Criteria:
  - AC-1: Миграция создаёт таблицу message_reactions.
  - AC-2: MessageReactionUpdated (новая реакция) → запись в БД.
  - AC-3: MessageReactionUpdated (снятая реакция) → запись удаляется или
    помечается removed_at.
  - AC-4: allowed_updates в боте включает "message_reaction".
  - AC-5: Нет интерпретации emoji — только raw storage.

Blocker: пользователь должен выбрать emoji из списка Telegram-реакций.
  До получения списка — инфраструктура готова, интерпретация пустая.

Files (новые):
  - app/models/reaction.py (MessageReaction SQLAlchemy model)
  - alembic/versions/XXX_add_message_reactions.py

Files (изменённые):
  - app/telegram/__main__.py (хендлер + allowed_updates)

---

## 5. Dependency Graph

✅ WS-16.1, WS-16.2, WS-16.3 — выполнены 2026-04-25.
WS-16.4 независим — следующий в очереди.
WS-16.5 зависит от понимания воркеров — после 16.4.
WS-16.6 независим, трудоёмкий — последним.
WS-16.7 независим — можно параллельно с 16.4.

Рекомендуемый порядок:
  1. ✅ WS-16.1 + 16.2 + 16.3 (prompt + tools, done)
  2. WS-16.4 + WS-16.7 (telegram bot, можно вместе)
  3. WS-16.5 (pipeline notification)
  4. WS-16.6 (dream notes, новая модель)

---

## 6. Phase Gate

- [x] Бот никогда не цитирует текст снов не из tool results (WS-16.1)
- [x] "найди где упоминается X" → семантический поиск + fallback (WS-16.2)
- [x] "найди все сны с религиозными сюжетами" → множественные запросы (WS-16.3)
- [x] Все processing-сообщения на русском (WS-16.4)
- [x] Бот присылает уведомление о завершении sync (WS-16.5)
- [x] Команда "note: ..." добавляет заметку к последнему сну (WS-16.6)
- [x] Emoji-реакции сохраняются в БД (WS-16.7)

## 7. Not In Scope

- Снижение RETRIEVAL_THRESHOLD ниже 0.20 — добавит шум, не решит проблему.
- Изменение embedding model — избыточно для текущих проблем.
- Семантика emoji-реакций — ждём список от пользователя (Nikolai).
- Редактирование существующих dream entries — immutable records policy сохраняется.
