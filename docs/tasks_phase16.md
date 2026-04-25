# Task Graph — Dream Motif Interpreter Phase 16

Version: 1.0
Last updated: 2026-04-25
Status: Planning — source: Тест 4 (25.04.26)

## 1. Purpose

Phase 16 addresses defects and feature requests from Тест 4 (25.04.26).
Two priorities: (1) критичный баг — бот выдаёт несуществующие фрагменты снов;
(2) качество поиска — нерелевантная маршрутизация и слабый семантический recall.
Плюс четыре UX-улучшения.

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
F5 (P4): Оценка ответов через emoji-реакции Telegram. ОТЛОЖЕНО —
  пользователь предоставит список emoji и расшифровку в отдельной задаче.

## 4. Honest Scope Assessment

D1 — prompt hardening. Нет архитектурных изменений. Средний риск —
  требует тщательного тестирования чтобы не сломать нормальные ответы.

D2 — prompt routing fix + fallback в tools.py. Лёгкий. Fallback:
  если exact search вернул 0 результатов → автоматически попробовать
  semantic search с тем же запросом.

D3 — prompt: модель должна пробовать несколько поисковых запросов
  при поиске по мотивам. Инструмент оставить без изменений.
  НЕ снижать RETRIEVAL_THRESHOLD (0.20 уже низкий, снижение добавит шум).

F1, F2 — тривиальные изменения в telegram/__main__.py. 1 commit.

F3 — требует изменений в двух слоях: (1) при trigger_sync сохранять
  chat_id в Redis; (2) воркер после завершения ingest отправляет
  сообщение через Bot API. Средняя сложность, не касается основной логики.

F4 — требует миграции БД и нового инструмента. Принцип чистоты:
  НЕ добавлять поле notes к DreamEntry — это смешает источник с заметками.
  Создать отдельную модель DreamNote с FK на dream_id. Средняя сложность.

F5 — отложено. Нет смысла строить систему без спецификации emoji.

---

## WS-16.1: Жёсткий запрет на галлюцинации

Owner:      codex
Phase:      16
Type:       prompt
Priority:   P0
Effort:     S (< 1 час)

Objective:
  Модель никогда не должна цитировать или пересказывать текст снов,
  которого нет в полях chunk_text / quote / fragment_text результатов
  инструментов. Если доказательств недостаточно — сказать прямо.
  Это правило абсолютно: не нарушается даже если пользователь
  просит "ещё результаты" или "расскажи подробнее".

Acceptance-Criteria:
  - AC-1: SYSTEM_PROMPT содержит явный запрет:
    "You may ONLY present dream text that appears verbatim in tool
    result fields (chunk_text, quote, fragment_text). Never generate,
    paraphrase, or infer dream content. If there is no more evidence,
    say so directly."
  - AC-2: Запрет распространяется на ответы "дай ещё" —
    если в инструменте нет больше результатов, сказать "больше нет".
  - AC-3: Unit-тест: вызов search_dreams с пустым результатом →
    ответ модели не содержит текста снов.

Files:
  - app/assistant/prompts.py (SYSTEM_PROMPT — раздел Archive Mutation Rules
    или новый раздел Search Grounding Rules)

---

## WS-16.2: Фикс маршрутизации поиска + fallback

Owner:      codex
Phase:      16
Type:       prompt + tools
Priority:   P1
Effort:     S (< 2 часа)

Objective:
  Запросы с "упоминается X", "где встречается X", "найди сны с X"
  должны по умолчанию идти в search_dreams (семантический), а не
  search_dreams_exact (буквальный).
  search_dreams_exact — только для "найди буквально слово X" или
  цитирования конкретной фразы.
  Добавить в execute_tool автоматический fallback: если
  search_dreams_exact вернул 0 результатов → повторить с
  search_dreams тем же запросом и вернуть объединённый результат
  с пометкой "поиск по смыслу".

Acceptance-Criteria:
  - AC-1: System prompt разграничивает: exact — для verbatim-цитат;
    semantic — для концепций, образов, мотивов, явлений.
  - AC-2: Если exact вернул 0 и fallback-semantic нашёл результаты —
    вернуть semantic-результаты с пометкой в тексте инструмента.
  - AC-3: Тест: запрос "упоминается молитва" при отсутствии слова
    "молитва" в архиве → fallback возвращает семантически близкие
    результаты вместо пустой выдачи.

Files:
  - app/assistant/prompts.py (правило маршрутизации search_dreams vs exact)
  - app/assistant/tools.py (fallback в execute_tool search_dreams_exact)

---

## WS-16.3: Поиск по мотиву — многозапросная стратегия

Owner:      codex
Phase:      16
Type:       prompt
Priority:   P1
Effort:     S (< 1 час)

Objective:
  При поиске по широкому мотиву ("религиозные сюжеты", "темы воды",
  "образы смерти") модель должна запускать несколько поисковых запросов
  с разными формулировками прежде чем давать итоговый ответ.
  Инструмент search_dreams не изменяется — логика на уровне промпта.

Acceptance-Criteria:
  - AC-1: System prompt содержит правило: при поиске по мотиву/теме
    выполнить search_dreams минимум 2-3 раза с разными ключевыми
    словами/образами, объединить результаты, дедублировать по dream_id.
  - AC-2: Примеры альтернативных запросов для "религиозные сюжеты":
    "церковь молитва бог", "рождество крест икона", "богослужение
    песнопение священник" — каждый отдельным вызовом.
  - AC-3: Финальный ответ формируется из объединённой выборки,
    sorted by relevance_score desc.

Files:
  - app/assistant/prompts.py (новое правило в разделе поиска)

---

## WS-16.4: Русский язык для сообщений обработки

Owner:      codex
Phase:      16
Type:       telegram bot
Priority:   P1
Effort:     XS (< 30 минут)

Objective:
  Все processing-сообщения в Telegram боте на русском.
  Добавить аналогичное сообщение для текстовых запросов.

Acceptance-Criteria:
  - AC-1: Голосовое сообщение: "Обрабатываю голосовое сообщение..."
    (было на английском или отсутствовало на русском).
  - AC-2: Текстовый запрос: перед отправкой в LLM бот отправляет
    "Обрабатываю..." (или использует sendChatAction typing).
  - AC-3: Сообщение "Обрабатываю..." убирается/заменяется итоговым
    ответом — не оставлять висеть в чате.

Implementation note:
  Предпочтительно sendChatAction(action="typing") — не засоряет чат
  лишними сообщениями. Повторять каждые 4 сек пока идёт обработка
  (Telegram показывает typing 5 сек, потом гасит).
  Для голоса — редактировать существующее промежуточное сообщение.

Files:
  - app/telegram/__main__.py

---

## WS-16.5: Уведомление о завершении синхронизации

Owner:      codex
Phase:      16
Type:       telegram bot + worker
Priority:   P2
Effort:     M (4-6 часов)

Objective:
  Когда пользователь добавляет новый источник и запускается sync,
  бот должен написать в чат когда синхронизация завершена.

Design (не усложнять пайплайн):
  1. В trigger_sync (facade) / tools.py manage_archive_source:
     сохранить в Redis ключ sync_notify:{job_id} = chat_id с TTL 1 час.
  2. В app/workers/ingest.py (или где заканчивается ingest-job):
     после успешного завершения проверить Redis на sync_notify:{job_id};
     если есть — послать Telegram Bot API sendMessage в chat_id.
  3. chat_id доступен из контекста — передаётся через инструмент.

Acceptance-Criteria:
  - AC-1: После завершения sync бот присылает:
    "Синхронизация завершена: [название документа]. Добавлено N записей."
  - AC-2: Уведомление приходит только один раз (ключ в Redis удаляется).
  - AC-3: Если sync завершился ошибкой — "Синхронизация не удалась: [причина]."
  - AC-4: Если chat_id неизвестен (sync запущен не из бота) — молча пропустить.

Blocker: нужно убедиться что chat_id доступен в контексте вызова trigger_sync.
  Сейчас tools.py получает chat_id через параметр execute_tool — передать дальше.

Files:
  - app/assistant/tools.py (передать chat_id при trigger_sync)
  - app/assistant/facade.py (trigger_sync принимает notify_chat_id=None)
  - app/workers/ingest.py (отправить уведомление по завершении)
  - app/shared/redis.py или utils (хелпер для sync-notify ключей)

---

## WS-16.6: Заметки к записанным снам

Owner:      codex
Phase:      16
Type:       model + migration + tool
Priority:   P2
Effort:     M (4-6 часов)

Objective:
  Пользователь может добавить заметку к уже записанному сну.
  Пример: "note: сегодня вспомнил что в этом сне была ещё одна сцена".
  Заметка хранится отдельно от raw_text (не перезаписывает оригинал).

Design:
  Отдельная модель DreamNote — НЕ добавлять поле к DreamEntry.
  DreamEntry — это ingested record из Google Doc, он immutable.
  DreamNote — это human annotation layer поверх записи.

  DreamNote schema:
    id: UUID PK
    dream_id: UUID FK → dream_entries.id
    text: str  (текст заметки без префикса "note:")
    source: str  (default "telegram")
    created_at: datetime

  В Google Doc заметка добавляется как отступ под записью:
    "[Note дд.мм.гг]: текст заметки"

Acceptance-Criteria:
  - AC-1: Новый инструмент add_dream_note(dream_id, note_text).
    dream_id опционален — если не указан, применяется к последнему сну.
  - AC-2: Заметка сохраняется в БД в таблице dream_notes.
  - AC-3: Заметка добавляется в Google Doc под соответствующим сном
    (append_note_to_entry в GDocsClient).
  - AC-4: get_dream возвращает notes в составе DreamDetail.
  - AC-5: Миграция alembic создаёт таблицу dream_notes.
  - AC-6: Бот распознаёт паттерн "note: текст" в сообщении и
    автоматически вызывает add_dream_note для последнего сна.

Files (новые):
  - app/models/note.py (DreamNote SQLAlchemy model)
  - alembic/versions/XXX_add_dream_notes.py

Files (изменённые):
  - app/assistant/facade.py (add_dream_note, DreamDetail.notes)
  - app/assistant/tools.py (новый инструмент add_dream_note)
  - app/services/gdocs_client.py (append_note_to_entry)
  - app/assistant/prompts.py (правило для паттерна "note:")

---

## 5. Dependency Graph

WS-16.1, WS-16.2, WS-16.3 независимы, можно параллельно.
WS-16.4 независим.
WS-16.5 зависит от понимания архитектуры воркеров — делать после 16.1-16.4.
WS-16.6 независим, но самый трудоёмкий — делать последним.

Рекомендуемый порядок:
  1. WS-16.1 (P0, быстро)
  2. WS-16.2 + WS-16.3 (P1, prompt, можно в одном коммите)
  3. WS-16.4 (P1, тривиально)
  4. WS-16.5 (P2, pipeline)
  5. WS-16.6 (P2, новая модель)

---

## 6. Phase Gate

- [ ] Бот никогда не цитирует текст снов не из tool results (WS-16.1)
- [ ] "найди где упоминается X" → семантический поиск, не буквальный (WS-16.2)
- [ ] "найди все сны с религиозными сюжетами" → множественные запросы (WS-16.3)
- [ ] Все processing-сообщения на русском (WS-16.4)
- [ ] Бот присылает уведомление о завершении sync (WS-16.5)
- [ ] Команда "note: ..." добавляет заметку к последнему сну (WS-16.6)

## 7. Not In Scope

- Снижение RETRIEVAL_THRESHOLD ниже 0.20 — добавит шум, не решит проблему.
  Проблема в маршрутизации и количестве запросов, а не в пороге.
- Изменение embedding model — избыточно для текущих проблем.
- Emoji reactions (F5) — отложено до получения спецификации от пользователя.
- Редактирование существующих dream entries — вне скоупа,
  существующая политика immutable records сохраняется.
