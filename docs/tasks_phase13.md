# Task Graph — Dream Motif Interpreter Phase 13

Version: 1.0
Last updated: 2026-04-24
Status: Planning — source: Тест 2 (23.04.26)

## 1. Purpose

This file is the implementation task graph for Phase 13 of Dream Motif Interpreter.

It captures defects and gaps identified in the second real-use test session (Тест 2, 23.04.26).
Phase 13 covers multi-source Google Docs support, search recall improvements, quote extraction,
and UX polish fixes. No schema changes are required.

Phase 14 (Write to Google Docs) is kept separate because it requires a major infrastructure
prerequisite (OAuth2/service account write credentials) that blocks all its workstreams.

## 2. How To Use This File

- use this file as the active implementation authority for Phase 13 work
- read `Context-Refs` before touching a file
- do not change database schema without updating `alembic/versions/` and this file
- do not start coding without reading the relevant source file first

Reference documents:

- `app/assistant/prompts.py`
- `app/assistant/tools.py`
- `app/assistant/facade.py`
- `app/retrieval/query.py`
- `app/shared/config.py`
- `app/telegram/handlers.py`

## 3. Dependency Graph

```
WS-13.1 (multi-source settings)
    └──► WS-13.2 (manage_archive_source multi-doc)

WS-13.5 (search_dreams_exact tool) ──► WS-13.6 (quote extraction)

WS-13.7 (multi-fragment per dream) ─────┐
WS-13.5 ────────────────────────────────┴──► WS-13.8 (prompt updates)

WS-13.3 (terminology) — independent
WS-13.4 (rating prompt) — independent
```

---

## WS-13.1: Multi-source Google Docs в Settings и sync pipeline

Owner:      codex
Phase:      13
Type:       config + workers
Depends-On: none
Priority:   P0 — блокирует поиск по второму Google Doc

Objective: |
  Пользователь добавил второй Google Doc. Текущий Settings содержит единственное поле
  GOOGLE_DOC_ID: str. Инструмент manage_archive_source в WS-12.8 реализовал только замену
  (set) одного doc_id, не добавление второго. В результате второй документ не синхронизируется
  и не попадает в поиск.

  Нужно расширить Settings для хранения списка doc_id, обеспечить обратную совместимость
  с существующим GOOGLE_DOC_ID и обновить sync pipeline для обхода всех источников.

Acceptance-Criteria:
  - id: AC-1
    description: "Settings содержит поле GOOGLE_DOC_IDS: list[str] (default: []), инициализируемое из переменной окружения GOOGLE_DOC_IDS (comma-separated строка)."
  - id: AC-2
    description: "get_all_doc_ids() — вспомогательная функция или метод Settings — возвращает объединённый список: [GOOGLE_DOC_ID] + GOOGLE_DOC_IDS (дедупликация, GOOGLE_DOC_ID — первый). Обратная совместимость: если GOOGLE_DOC_IDS пуст, работает как раньше."
  - id: AC-3
    description: "ingest_document в workers/ingest.py принимает doc_id как параметр (уже есть) — никаких изменений в сигнатуре не нужно."
  - id: AC-4
    description: "trigger_sync в AssistantFacade запускает ingest_document для каждого doc_id из get_all_doc_ids() последовательно."
  - id: AC-5
    description: "Юнит-тест проверяет get_all_doc_ids() при GOOGLE_DOC_ID='A', GOOGLE_DOC_IDS='B,C' → ['A','B','C']; при дублировании — дедупликация."

Files:
  - app/shared/config.py     (Settings: GOOGLE_DOC_IDS, get_all_doc_ids)
  - app/assistant/facade.py  (trigger_sync: обход всех doc_ids)

Context-Refs:
  - app/shared/config.py:13–47 (Settings)
  - app/services/gdocs_client.py:62–96 (GOOGLE_DOC_ID usage)
  - app/assistant/facade.py (trigger_sync метод)

Notes: |
  Минимальное изменение в config.py: добавить
    GOOGLE_DOC_IDS: list[str] = Field(default_factory=list)
  с кастомным validator для parses comma-separated строки.
  trigger_sync в facade: перебрать get_all_doc_ids(), запустить ingest_document для каждого.
  Порядок: сначала primary (GOOGLE_DOC_ID), потом дополнительные.

---

## WS-13.2: manage_archive_source — расширить до multi-doc

Owner:      codex
Phase:      13
Type:       tools + facade
Depends-On: WS-13.1
Priority:   P0

Objective: |
  Текущий manage_archive_source поддерживает только action='get' и action='set'.
  'set' заменяет единственный doc_id, а не добавляет новый. Пользователь хочет:
  - посмотреть все подключённые Google Docs
  - добавить новый Google Doc не теряя существующий
  - удалить один из Google Docs

Acceptance-Criteria:
  - id: AC-1
    description: "action='list' возвращает нумерованный список всех подключённых doc_ids (primary первый)."
  - id: AC-2
    description: "action='add' с doc_id добавляет новый doc_id в GOOGLE_DOC_IDS runtime override. Не дублирует. Возвращает подтверждение с обновлённым списком."
  - id: AC-3
    description: "action='remove' с doc_id убирает doc_id из GOOGLE_DOC_IDS runtime override (нельзя удалить primary GOOGLE_DOC_ID). Возвращает обновлённый список."
  - id: AC-4
    description: "action='get' и action='set' сохраняют обратную совместимость (set = установить primary doc_id)."
  - id: AC-5
    description: "Инструмент description в tools.py обновлён: упоминает actions 'list', 'add', 'remove' дополнительно к 'get'/'set'."
  - id: AC-6
    description: "Юнит-тест покрывает action='list', 'add' (дедупликация), 'remove'."

Files:
  - app/assistant/tools.py   (manage_archive_source tool schema + execute_tool block)
  - app/assistant/facade.py  (методы get_archive_source, set_archive_source, list_archive_sources, add_archive_source, remove_archive_source)
  - app/shared/config.py     (runtime override для GOOGLE_DOC_IDS)

Context-Refs:
  - app/assistant/tools.py:141–170 (manage_archive_source schema)
  - app/assistant/tools.py:362–373 (execute_tool manage_archive_source)

Notes: |
  Runtime override: хранить overridden_doc_ids: list[str] | None в глобальной переменной
  в config.py (аналогично WS-12.8 для primary doc_id override).
  get_all_doc_ids() из WS-13.1 должен учитывать оба override (primary и список).

---

## WS-13.3: Нормализация терминологии в SYSTEM_PROMPT

Owner:      codex
Phase:      13
Type:       prompt
Depends-On: none
Priority:   P1

Objective: |
  Пользователь использует слова «архив», «хранилище», «база» имея в виду Google Docs.
  Бот понимает эти слова как внутренний архив (БД). Это вводит в заблуждение.

  Нужно добавить в SYSTEM_PROMPT инструкцию: слова «архив», «база», «хранилище» от пользователя
  означают Google Docs (источники). Внутренняя БД — деталь реализации, упоминать только
  когда Google Docs недоступны.

Acceptance-Criteria:
  - id: AC-1
    description: "SYSTEM_PROMPT содержит раздел '## Terminology Rules' с инструкцией: «архив», «база», «хранилище» в сообщениях пользователя = Google Docs."
  - id: AC-2
    description: "Инструкция запрещает упоминать внутреннюю БД / векторный индекс / embeddings в ответах пользователю, если только соединение с Google Docs невозможно."
  - id: AC-3
    description: "manage_archive_source и trigger_sync описаны в prompts.py как операции с 'Google Docs', не с 'архивом'."
  - id: AC-4
    description: "Когда пользователь говорит «добавь в архив» — это воспринимается как create_dream (запись нового сна), а не как управление источниками."

Files:
  - app/assistant/prompts.py  (SYSTEM_PROMPT — новый раздел Terminology Rules)

Context-Refs:
  - app/assistant/prompts.py:5–77

Notes: |
  Добавить раздел после ## Response Formatting Rules.
  Формулировка: «Когда пользователь говорит "архив", "база" или "хранилище" —
  он имеет в виду Google Docs (источники данных). Не упоминай внутренний индекс
  или векторную базу данных в ответах пользователю. Управление источниками —
  это управление Google Doc ID через manage_archive_source.»

---

## WS-13.4: Локализация подсказки для оценки ответа

Owner:      codex
Phase:      13
Type:       telegram
Depends-On: none
Priority:   P1

Objective: |
  Подсказка для оценки ответа (Phase 11) отправляется на английском языке:
  "Reply to this message to rate (1–5), or add a comment after the digit."
  Это нарушает языковой контекст: всё остальное на русском, подсказка на английском.

Acceptance-Criteria:
  - id: AC-1
    description: "FEEDBACK_PROMPT в handlers.py изменён на: «Оцените ответ от 1 до 5 или добавьте комментарий после цифры.»"
  - id: AC-2
    description: "Текст подсказки отделён от ответа бота одной пустой строкой."
  - id: AC-3
    description: "Юнит-тест или snapshot-тест обновлён под новый текст."

Files:
  - app/telegram/handlers.py  (FEEDBACK_PROMPT константа, строка 21)

Context-Refs:
  - app/telegram/handlers.py:21

Notes: |
  Минимальное однострочное изменение. Проверить, что тест, ссылающийся на старый
  текст подсказки, также обновлён.

---

## WS-13.5: Новый инструмент search_dreams_exact — точный поиск по тексту

Owner:      codex
Phase:      13
Type:       retrieval + facade + tools
Depends-On: none
Priority:   P0

Objective: |
  Текущий search_dreams использует комбинацию семантического поиска + FTS с порогом
  релевантности и лимитом в 5 результатов. При запросе по конкретному образу («церковь»)
  бот не находит все сны, содержащие это слово или его словоформы, потому что:
  1. Второй Google Doc не синхронизирован (фиксируется в WS-13.1).
  2. Порог релевантности и лимит отсекают валидные совпадения.

  Нужен отдельный инструмент search_dreams_exact для точного поиска по слову/фразе:
  - pure FTS (PostgreSQL to_tsvector / websearch_to_tsquery, Russian morphology)
  - без порога релевантности (если слово в тексте — возвращать)
  - лимит результатов: 20 (вместо 5)
  - возвращает ВСЕ чанки, содержащие искомое слово/фразу, сгруппированные по снам

Acceptance-Criteria:
  - id: AC-1
    description: "Новый метод exact_search в RagQueryService: pure FTS без threshold, limit=20."
  - id: AC-2
    description: "SQL использует to_tsvector('russian', chunk_text) @@ websearch_to_tsquery('russian', :query) без GREATEST threshold WHERE clause."
  - id: AC-3
    description: "Новый метод search_dreams_exact в AssistantFacade вызывает RagQueryService.exact_search."
  - id: AC-4
    description: "Новый инструмент search_dreams_exact в _BASE_TOOLS: принимает query: str, описание: «Exact text/word search across all dream entries. Use when the user searches for a specific word, phrase, or image name that appears verbatim in dream text.»"
  - id: AC-5
    description: "execute_tool routing добавлен для search_dreams_exact."
  - id: AC-6
    description: "SYSTEM_PROMPT содержит инструкцию: использовать search_dreams_exact при запросе по конкретному образу/слову (например, «найди сны со словом X», «найди сны, где упоминается X»)."
  - id: AC-7
    description: "Юнит-тест проверяет exact_search: возвращает все чанки, содержащие искомое слово; не применяет threshold."

Files:
  - app/retrieval/query.py   (метод exact_search в RagQueryService)
  - app/assistant/facade.py  (search_dreams_exact)
  - app/assistant/tools.py   (search_dreams_exact tool schema + routing)
  - app/assistant/prompts.py (SYSTEM_PROMPT — инструкция по выбору инструмента)

Context-Refs:
  - app/retrieval/query.py:22–25 (RESULT_LIMIT = 5, constants)
  - app/retrieval/query.py:173–304 (_search SQL)
  - app/assistant/facade.py:373–387 (_search_result_item)
  - app/assistant/tools.py:9–27 (search_dreams tool)

Notes: |
  SQL для exact_search:
    SELECT dc.dream_id, de.date, de.title, dc.chunk_text
    FROM dream_chunks dc
    JOIN dream_entries de ON de.id = dc.dream_id
    WHERE to_tsvector('russian', dc.chunk_text) @@ websearch_to_tsquery('russian', :query)
    ORDER BY de.date DESC
    LIMIT 20
  Никакого embeddings-вызова — это pure FTS, дешевле и быстрее.
  В facade: возвращать список SearchResultItem. Не нужна InsufficientEvidence —
  просто пустой список если ничего не найдено.

---

## WS-13.6: Извлечение точной цитаты в результатах поиска

Owner:      codex
Phase:      13
Type:       facade + tools + prompt
Depends-On: WS-13.5
Priority:   P1

Objective: |
  При поиске по конкретному образу пользователь ожидает увидеть прямую цитату из текста сна,
  в которой упоминается искомый образ. Ожидаемый формат:

    30.07.22 Путешествие 1: о подъеме на верх часовни: "Мы зашли с ним в высокую часовню
    или в узкую церковь, встроенную в здание"

  Нужно:
  1. Извлекать из chunk_text предложение/фразу, содержащую поисковый запрос.
  2. Возвращать его как поле quote в SearchResultItem.
  3. Инструктировать Claude форматировать вывод с цитатой.

Acceptance-Criteria:
  - id: AC-1
    description: "SearchResultItem содержит поле quote: str | None — предложение из chunk_text, содержащее слова из query."
  - id: AC-2
    description: "Вспомогательная функция _extract_quote(chunk_text: str, query: str) -> str | None: сплит по '.!?\n', находит первое предложение, содержащее хотя бы одно слово из query (нижний регистр). Если не найдено — None."
  - id: AC-3
    description: "_extract_quote вызывается в facade._search_result_item при формировании SearchResultItem для search_dreams_exact (и опционально для search_dreams)."
  - id: AC-4
    description: "Вывод инструмента search_dreams_exact включает quote для каждого результата: 'Quote: \"<цитата>\"' или 'Quote: (not extracted)' если None."
  - id: AC-5
    description: "SYSTEM_PROMPT содержит инструкцию по формату вывода с цитатой: «дд.мм.гг, Название: краткая характеристика: \"цитата\"»."
  - id: AC-6
    description: "Юнит-тест проверяет _extract_quote на типичном русском тексте: находит нужное предложение."

Files:
  - app/assistant/facade.py  (SearchResultItem.quote, _search_result_item, _extract_quote)
  - app/assistant/tools.py   (вывод search_dreams_exact включает quote)
  - app/assistant/prompts.py (SYSTEM_PROMPT — формат с цитатой)

Context-Refs:
  - app/assistant/facade.py:27–38 (SearchResultItem)
  - app/assistant/facade.py:373–387 (_search_result_item)

Notes: |
  _extract_quote реализация:
    import re
    def _extract_quote(chunk_text: str, query: str) -> str | None:
        words = set(re.sub(r'[^\w\s]', '', query.lower()).split())
        for sentence in re.split(r'[.!?\n]+', chunk_text):
            s = sentence.strip()
            if not s:
                continue
            s_lower = s.lower()
            if any(w in s_lower for w in words):
                return s
        return None
  Добавить quote в search_dreams тоже — пользователю полезно в обоих случаях.

---

## WS-13.7: Все совпадающие фрагменты — убрать ограничение на 5 результатов

Owner:      codex
Phase:      13
Type:       retrieval + tools + prompt
Depends-On: none
Priority:   P1

Objective: |
  При поиске мотива (например, «вертикальный подъём или спуск») бот находит одни сны
  но пропускает отдельные фрагменты из уже найденных снов. Причина:
  - RESULT_LIMIT = 5 ограничивает общее число чанков
  - Если один сон даёт 2 чанка, другой — 2 чанка, пятый слот достаётся только одному сну
  - Когда пользователь просит найти ВСЕ примеры мотива — нужно показать все фрагменты

  Нужно:
  1. Увеличить RESULT_LIMIT с 5 до 20.
  2. В выводе инструмента search_dreams группировать чанки по сну и показывать все фрагменты.
  3. В SYSTEM_PROMPT: при запросе «найди все» — перечислить все фрагменты из всех снов,
     даже если это несколько фрагментов одного сна.

Acceptance-Criteria:
  - id: AC-1
    description: "RESULT_LIMIT в query.py изменён с 5 на 20."
  - id: AC-2
    description: "Вывод инструмента search_dreams для каждого результата явно указывает dream_id и порядковый номер фрагмента. Формат: 'dream_id=<uuid> | date=<date> | title=<title> | fragment_N | score=<score>\n<chunk_text>'."
  - id: AC-3
    description: "SYSTEM_PROMPT содержит инструкцию: если для одного сна несколько фрагментов — показывать все под одной записью о сне, не объединять в одну строку."
  - id: AC-4
    description: "Формат ответа при нескольких фрагментах одного сна: «дд.мм.гг, Название: (несколько фрагментов)\\n  1. фрагмент А\\n  2. фрагмент Б»."
  - id: AC-5
    description: "Юнит-тест: при поиске, возвращающем 2 чанка одного сна, оба присутствуют в выводе инструмента."

Files:
  - app/retrieval/query.py   (RESULT_LIMIT = 20)
  - app/assistant/tools.py   (форматирование вывода search_dreams с group-by-dream)
  - app/assistant/prompts.py (SYSTEM_PROMPT — инструкция по нескольким фрагментам)

Context-Refs:
  - app/retrieval/query.py:22–25 (RESULT_LIMIT константа)
  - app/assistant/tools.py:210–225 (execute_tool search_dreams)

Notes: |
  Группировка по dream_id в tools.py: сортировать результаты по dream_id + score,
  добавить счётчик fragment_N для каждой группы.
  Порядок снов в группированном выводе: по убыванию max(score) в группе.

---

## WS-13.8: Обновление SYSTEM_PROMPT под новые инструменты

Owner:      codex
Phase:      13
Type:       prompt
Depends-On: WS-13.5, WS-13.7
Priority:   P1

Objective: |
  После добавления search_dreams_exact (WS-13.5), quote (WS-13.6) и изменения форматирования
  search_dreams (WS-13.7), SYSTEM_PROMPT требует обновлённых инструкций:
  - когда использовать search_dreams vs search_dreams_exact
  - как форматировать результаты с цитатами
  - как форматировать результаты с несколькими фрагментами одного сна

Acceptance-Criteria:
  - id: AC-1
    description: "SYSTEM_PROMPT содержит правило выбора инструмента: search_dreams_exact — для конкретного слова/образа/словосочетания из текста сна; search_dreams — для тематических/мотивных запросов."
  - id: AC-2
    description: "SYSTEM_PROMPT содержит формат с цитатой: «N. дд.мм.гг, Название: краткая характеристика: \"цитата\"»."
  - id: AC-3
    description: "SYSTEM_PROMPT содержит инструкцию для search_dreams: несколько фрагментов одного сна показывать под одним заголовком сна с отступом."
  - id: AC-4
    description: "Инструкция явно запрещает обрезать список фрагментов с «и другие» или «см. также» — показывать все."

Files:
  - app/assistant/prompts.py  (SYSTEM_PROMPT)

Context-Refs:
  - app/assistant/prompts.py:59–77

---

## 4. Phase Gate

Phase 13 считается завершённой когда:

- [ ] Второй Google Doc синхронизируется через trigger_sync (WS-13.1 + WS-13.2)
- [ ] manage_archive_source поддерживает action='list', 'add', 'remove' (WS-13.2)
- [ ] Терминология: «архив/база» = Google Docs в ответах бота (WS-13.3)
- [ ] Подсказка оценки на русском языке (WS-13.4)
- [ ] search_dreams_exact находит все сны с конкретным словом, включая словоформы (WS-13.5)
- [ ] Результаты содержат точную цитату из текста сна (WS-13.6)
- [ ] search_dreams возвращает до 20 чанков; несколько фрагментов одного сна видны (WS-13.7)
- [ ] SYSTEM_PROMPT содержит актуальные инструкции по выбору инструмента и форматированию (WS-13.8)

## 5. Continuity Notes

- `docs/tasks_phase12.md` — историческая запись Phase 12 (завершена)
- источник: Тест 2 (23.04.26), обратная связь пользователя
- Phase 14 (запись снов в Google Doc) хранится в отдельном файле — требует dev-инфраструктуры
