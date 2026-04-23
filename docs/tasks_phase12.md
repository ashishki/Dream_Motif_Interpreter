# Task Graph — Dream Motif Interpreter Phase 12

Version: 1.0
Last updated: 2026-04-23
Status: Complete — 2026-04-23

## 1. Purpose

This file is the implementation task graph for Phase 12 of Dream Motif Interpreter.

It captures the fix backlog from the first real-use test session (Тест 1, 22.04.26) conducted by the user.
All items are UX-level defects or behaviour mismatches — no schema changes required for most tasks.

Phase 12 exists separately from Phase 11 so that Phase 11 (Feedback Loop) history stays clean.

## 2. How To Use This File

- use this file as the active implementation authority for Phase 12 work
- read `Context-Refs` before touching a file
- do not change database schema without updating `alembic/versions/` and this file
- do not start coding without reading the relevant source file first

Reference documents:

- `docs/TELEGRAM_INTERACTION_MODEL.md §12–14`
- `app/assistant/prompts.py`
- `app/assistant/tools.py`
- `app/assistant/facade.py`
- `app/retrieval/query.py`

## 3. Dependency Graph

```
WS-12.1 (мотив UUID)  ──────────────────┐
                                         ▼
WS-12.9 (параллели — упрощение) ─── depends on WS-12.1

WS-12.2 (no markdown) ─ independent

WS-12.4 (title в search) ─ independent ──┐
WS-12.3 (preview в list) ─ independent ──┴──► WS-12.10 (образ — формат)

WS-12.5 (strip * < в get_dream) ─ independent

WS-12.6 (запись — тригеры) ─ independent
WS-12.7 (запись — заголовок) ─ independent

WS-12.8 (управление источником) ─ independent
```

---

## WS-12.1: Добавить UUID мотива в вывод get_dream_motifs

Owner:      codex
Phase:      12
Type:       tools
Depends-On: none
Priority:   P0 — блокирует research_motif_parallels

Objective: |
  Инструмент get_dream_motifs возвращает мотивы без UUID.
  Когда Claude затем вызывает research_motif_parallels, он не знает motif_id
  и не может передать его в инструмент. В результате поиск параллелей никогда
  не работает.

  Нужно добавить UUID каждого мотива в строку вывода инструмента.

Acceptance-Criteria:
  - id: AC-1
    description: "Каждая строка в выводе get_dream_motifs содержит UUID мотива в формате [id=<uuid>]."
  - id: AC-2
    description: "Существующий формат строки сохраняется: [confidence] label (status) [id=uuid] / Rationale: ..."
  - id: AC-3
    description: "Юнит-тест проверяет, что UUID присутствует в выводе."

Files:
  - app/assistant/tools.py  (блок `if tool_name == "get_dream_motifs"`)

Context-Refs:
  - app/assistant/tools.py:325–346
  - app/assistant/facade.py:MotifInductionItem (поле id)

Notes: |
  Минимальное изменение. Добавить f" [id={motif.id}]" в конец основной строки мотива.

---

## WS-12.2: Запретить markdown в ответах ассистента

Owner:      codex
Phase:      12
Type:       prompt
Depends-On: none
Priority:   P0 — видно пользователю в каждом ответе

Objective: |
  Claude использует **жирный** текст (двойные звёздочки) в ответах, несмотря на то
  что интерфейс — Telegram с plain text. Нужно явно запретить markdown в system prompt.

Acceptance-Criteria:
  - id: AC-1
    description: "SYSTEM_PROMPT содержит явный запрет использовать **, *, __, [] markdown-разметку в ответах."
  - id: AC-2
    description: "Для списков предписывается нумерованный формат: 1. 2. 3."
  - id: AC-3
    description: "Даты в ответах пользователю форматируются как дд.мм.гг (например: 22.04.26)."
  - id: AC-4
    description: "Безымянный сон обозначается как «без названия»."

Files:
  - app/assistant/prompts.py  (SYSTEM_PROMPT)

Context-Refs:
  - app/assistant/prompts.py:5–48

Notes: |
  Добавить раздел «## Response Formatting Rules» в SYSTEM_PROMPT.
  Пример запрещённой фразы: «**Русалка (славянская мифология)**»
  Пример правильного: «1. Русалка (славянская мифология)»

---

## WS-12.3: Добавить preview и темы в DreamSummary для list_recent_dreams

Owner:      codex
Phase:      12
Type:       facade + tools
Depends-On: none
Priority:   P1

Objective: |
  Текущий вывод list_recent_dreams даёт Claude только UUID, дату, название, количество слов.
  Этого недостаточно, чтобы сформировать краткое описание «о чём сон».

  Нужно:
  1. Добавить поля raw_text_preview (str, первые 400 символов) и theme_names (list[str])
     в DreamSummary.
  2. Обновить list_recent_dreams в facade, чтобы подгружать темы вместе со снами.
  3. Изменить формат вывода инструмента: убрать UUID и word_count, добавить preview и темы.
  4. Добавить инструкцию в system prompt: Claude формирует краткое описание на русском
     по preview и темам, в формате «о <сюжет1>, <сюжет2>».

Acceptance-Criteria:
  - id: AC-1
    description: "DreamSummary содержит поля raw_text_preview: str и theme_names: list[str]."
  - id: AC-2
    description: "list_recent_dreams выполняет JOIN с dream_themes + theme_categories для каждой записи."
  - id: AC-3
    description: "Вывод инструмента НЕ содержит UUID и word_count. Содержит дату, название, preview, темы."
  - id: AC-4
    description: "Дата в выводе инструмента: ISO (YYYY-MM-DD). Claude конвертирует в dd.mm.yy при ответе пользователю."
  - id: AC-5
    description: "SYSTEM_PROMPT содержит инструкцию по формату списка снов: «дд.мм.гг, [название/без названия]: о <описание>»."
  - id: AC-6
    description: "Юнит-тест проверяет новые поля DreamSummary."

Files:
  - app/assistant/facade.py  (DreamSummary, list_recent_dreams, _dream_summary_item)
  - app/assistant/tools.py   (блок `if tool_name == "list_recent_dreams"`)
  - app/assistant/prompts.py (SYSTEM_PROMPT — инструкция по форматированию)

Context-Refs:
  - app/assistant/facade.py:66–76 (DreamSummary)
  - app/assistant/facade.py:203–218 (list_recent_dreams)
  - app/assistant/tools.py:273–284 (execute_tool list_recent_dreams)

Notes: |
  JOIN можно сделать через отдельный SELECT с WHERE dream_id IN (...) после получения снов,
  чтобы не усложнять основной запрос. Группировать по dream_id при маппинге.
  raw_text_preview = raw_text[:400].

---

## WS-12.4: Добавить title в результаты search_dreams

Owner:      codex
Phase:      12
Type:       retrieval + facade + tools
Depends-On: none
Priority:   P1

Objective: |
  Текущий вывод search_dreams показывает chunk_text и числовой score.
  Пользователь видит обрывки текста без названия сна.

  Нужно добавить title (или null) к каждому результату поиска, чтобы Claude
  мог составить строку вида «дд.мм.гг, Название: описание (сильная связь)».

Acceptance-Criteria:
  - id: AC-1
    description: "SQL-запрос в RagQueryService._search возвращает поле title из dream_entries."
  - id: AC-2
    description: "EvidenceBlock содержит поле title: str | None."
  - id: AC-3
    description: "SearchResultItem содержит поле title: str | None."
  - id: AC-4
    description: "Вывод инструмента включает title для каждого результата."
  - id: AC-5
    description: "Числовой score НЕ выводится пользователю — только в tool output для Claude."
  - id: AC-6
    description: "SYSTEM_PROMPT содержит маппинг score → вербальная сила связи: ≥0.7 — сильная, 0.4–0.69 — умеренная, <0.4 — слабая."
  - id: AC-7
    description: "Юнит-тест проверяет наличие поля title в EvidenceBlock."

Files:
  - app/retrieval/query.py   (EvidenceBlock, _search SQL SELECT)
  - app/assistant/facade.py  (SearchResultItem, _search_result_item)
  - app/assistant/tools.py   (блок `if tool_name == "search_dreams"`)
  - app/assistant/prompts.py (SYSTEM_PROMPT — маппинг score и формат)

Context-Refs:
  - app/retrieval/query.py:34–47 (EvidenceBlock)
  - app/retrieval/query.py:171–298 (_search, SQL)
  - app/assistant/facade.py:27–38 (SearchResultItem)
  - app/assistant/facade.py:373–387 (_search_result_item)
  - app/assistant/tools.py:210–225 (execute_tool search_dreams)

Notes: |
  В SQL: добавить `de.title` в SELECT cosine_candidates и fts_candidates, пробросить через fused.
  EvidenceBlock уже импортирует date из dream_entries — title рядом.

---

## WS-12.5: Убрать * и < из текста сна в get_dream

Owner:      codex
Phase:      12
Type:       tools
Depends-On: none
Priority:   P1

Objective: |
  Сырой текст снов из Google Docs содержит символы `*` и `<` (артефакты форматирования
  и служебных тегов Google Docs). Они попадают в ответ пользователю через get_dream.

  Нужно убрать эти символы из raw_text перед включением в вывод инструмента.

Acceptance-Criteria:
  - id: AC-1
    description: "В блоке get_dream символы * и < удаляются из detail.raw_text перед включением в строку."
  - id: AC-2
    description: "Остальные поля (дата, название, темы) не изменяются."
  - id: AC-3
    description: "Усечение текста остаётся (первые 500 символов для tool output), но может быть увеличено до 2000 для развёрнутого сна."

Files:
  - app/assistant/tools.py  (блок `if tool_name == "get_dream"`)

Context-Refs:
  - app/assistant/tools.py:254–271

Notes: |
  raw_text_clean = detail.raw_text.replace("*", "").replace("<", "")
  Рассмотреть увеличение лимита с 500 до 2000 символов — пользователь запросил
  полный текст сна при расшифровке.

---

## WS-12.6: Расширить список триггерных фраз для create_dream

Owner:      codex
Phase:      12
Type:       tools
Depends-On: none
Priority:   P1

Objective: |
  Функция _is_explicit_create_request содержит фиксированный список русских фраз-триггеров.
  Судя по тест-сессии, ассистент не вызывает create_dream при естественных формулировках,
  которые пользователь реально использует. В результате сон не сохраняется в базу.

Acceptance-Criteria:
  - id: AC-1
    description: "Список фраз расширен: добавлены «сохрани этот сон», «запишите», «запиши это», «добавь в архив», «сохрани в архив», «сохранить в архив», «занести в архив», «занеси в архив»."
  - id: AC-2
    description: "SYSTEM_PROMPT содержит явную инструкцию: при просьбе записать/сохранить/добавить сон — вызвать create_dream, а не просто подтвердить текстом."
  - id: AC-3
    description: "Юнит-тест покрывает новые фразы."

Files:
  - app/assistant/tools.py  (_is_explicit_create_request)
  - app/assistant/prompts.py (SYSTEM_PROMPT — инструкция по записи)

Context-Refs:
  - app/assistant/tools.py:377–397

---

## WS-12.7: Исправить формат заголовка при записи сна

Owner:      codex
Phase:      12
Type:       facade
Depends-On: none
Priority:   P1

Objective: |
  Текущая _resolve_dream_title использует первую строку текста как заголовок,
  если явный title не передан. Пользователь ожидает другой формат:

  - дата + название → «дд.мм.гг - Название»
  - дата без названия → «дд.мм.гг, без названия»
  - название без даты → использовать название как есть
  - ничего → «дд.мм.гг, без названия» (дата сохранения)

Acceptance-Criteria:
  - id: AC-1
    description: "Если title=None и dream_date=None — заголовок: «<сегодня dd.mm.yy>, без названия»."
  - id: AC-2
    description: "Если title=None и dream_date задан — заголовок: «<dream_date dd.mm.yy>, без названия»."
  - id: AC-3
    description: "Если title задан и dream_date задан — заголовок: «<dream_date dd.mm.yy> - <title>»."
  - id: AC-4
    description: "Если title задан и dream_date=None — заголовок: title (без изменений)."
  - id: AC-5
    description: "Формат даты в заголовке: дд.мм.гг."
  - id: AC-6
    description: "Юнит-тест покрывает все четыре ветки."

Files:
  - app/assistant/facade.py  (_resolve_dream_title)

Context-Refs:
  - app/assistant/facade.py:438–443
  - app/assistant/facade.py:230–302 (create_dream — как передаётся dream_date)

Notes: |
  _resolve_dream_title нужно принять dream_date как дополнительный параметр.
  Вызов из create_dream: _resolve_dream_title(normalized_text, title=title, dream_date=dream_date).

---

## WS-12.8: Управление источником архива из чата

Owner:      codex
Phase:      12
Type:       tools + facade
Depends-On: none
Priority:   P2

Objective: |
  Пользователь хочет менять путь к базе/Google Doc прямо из Telegram-чата,
  не заходя на сервер. Нужен инструмент manage_archive_source.

Acceptance-Criteria:
  - id: AC-1
    description: "Новый инструмент manage_archive_source принимает action: «get» | «set», и опциональный doc_id (для set)."
  - id: AC-2
    description: "action=get возвращает текущий GOOGLE_DOC_ID из Settings."
  - id: AC-3
    description: "action=set обновляет GOOGLE_DOC_ID в runtime (через переменную окружения или конфигурируемый override в Settings) и подтверждает изменение."
  - id: AC-4
    description: "Изменение doc_id не требует перезапуска бота — работает для следующего trigger_sync."
  - id: AC-5
    description: "Инструмент доступен только авторизованному пользователю (защита уже есть на уровне chat_guard)."
  - id: AC-6
    description: "Юнит-тест покрывает action=get и action=set."

Files:
  - app/assistant/tools.py   (новый блок manage_archive_source)
  - app/assistant/facade.py  (новый метод get_archive_source / set_archive_source)
  - app/shared/config.py     (если нужен mutable override)

Context-Refs:
  - app/shared/config.py  (Settings, get_settings)
  - app/assistant/tools.py:318–323  (trigger_sync — смежный инструмент)

Notes: |
  Простейший вариант: хранить override в глобальной переменной в config.py,
  которую set обновляет в runtime. Персистентность при перезапуске — P3,
  не нужна в этой итерации.

---

## WS-12.9: Упростить поток мифологических параллелей

Owner:      codex
Phase:      12
Type:       prompt
Depends-On: WS-12.1
Priority:   P1

Objective: |
  Текущий поток параллелей слишком техничен и содержит лишние шаги:
  1. Claude выводит длинный технический текст с подтверждением
  2. Пользователь подтверждает
  3. Claude снова показывает те же мотивы и говорит об отсутствии UUID
  4. Поиск не выполняется (UUID bug из WS-12.1)

  После фикса UUID (WS-12.1) нужно также упростить сам сценарий в system prompt:
  - Не нужен длинный технический преамбул
  - Вместо подтверждения — предложить выбрать мотивы
  - Не использовать слова «архетип», «паттерн» (если пользователь сам не употребил)
  - Не добавлять оценочные слова («глубокий», «интересный»)
  - Не добавлять обобщение в конце («Общий архетип: ...»)
  - Если UUID не получен через инструмент — не останавливаться, искать по доступным данным

Acceptance-Criteria:
  - id: AC-1
    description: "Research Augmentation Rules в SYSTEM_PROMPT: после get_dream_motifs предлагать «Выберите, по каким мотивам провести поиск» (без длинного пояснения)."
  - id: AC-2
    description: "Запрещено использовать слова «архетип», «паттерн» если пользователь не использовал их первым."
  - id: AC-3
    description: "Запрещены оценочные прилагательные в результатах («глубокий», «интересный», «мощный»)."
  - id: AC-4
    description: "Запрещено добавлять обобщение паттерна в конце списка параллелей."
  - id: AC-5
    description: "Если research_motif_parallels возвращает пустой результат — вернуть то, что есть из get_dream_motifs, без остановки на техническом барьере."

Files:
  - app/assistant/prompts.py  (Research Augmentation Rules в SYSTEM_PROMPT)

Context-Refs:
  - app/assistant/prompts.py:40–48
  - docs/TELEGRAM_INTERACTION_MODEL.md §13

---

## WS-12.10: Формат подборки снов по образу (search_dreams)

Owner:      codex
Phase:      12
Type:       prompt
Depends-On: WS-12.4
Priority:   P1

Objective: |
  Текущий вывод search_dreams группирует сны по силе связи (сильная/умеренная/слабая),
  вместо единого нумерованного списка. Пользователь хочет единый список с уровнем
  связи внутри строки.

  После WS-12.4 (title в результатах) обновить инструкцию в system prompt.

Acceptance-Criteria:
  - id: AC-1
    description: "SYSTEM_PROMPT содержит инструкцию: результаты search_dreams — единый нумерованный список без групп по силе связи."
  - id: AC-2
    description: "Каждая строка: «N. дд.мм.гг, [название/без названия]: описание (сильная/умеренная/слабая связь)»."
  - id: AC-3
    description: "Описание формируется из chunk_text или тем сна — 1 строка."
  - id: AC-4
    description: "Сортировка: по убыванию score (порядок из инструмента сохраняется)."

Files:
  - app/assistant/prompts.py  (SYSTEM_PROMPT — инструкция по search_dreams)

Context-Refs:
  - app/assistant/prompts.py
  - WS-12.4 (title добавлен в search results)

---

## 4. Phase Gate

Phase 12 считается завершённой когда:

- [x] Поиск мифологических параллелей работает end-to-end (WS-12.1 + WS-12.9)
- [x] Ответы не содержат markdown-разметки (WS-12.2)
- [x] list_recent_dreams показывает описание вместо UUID/word_count (WS-12.3)
- [x] search_dreams показывает название сна и вербальную силу связи (WS-12.4)
- [x] Текст сна в get_dream не содержит * и < (WS-12.5)
- [x] create_dream срабатывает на естественные русские фразы (WS-12.6)
- [x] Заголовок сна при сохранении в формате «дд.мм.гг, без названия» (WS-12.7)
- [x] manage_archive_source: смена источника архива из чата (WS-12.8)
- [x] Единый нумерованный список search_dreams с уровнем связи внутри строки (WS-12.10)

**Phase 12 завершена. Дата: 2026-04-23.**

## 5. Continuity Notes

- `docs/tasks_phase11.md` — историческая запись Phase 11 (завершена)
- `docs/tasks_phase12.md` — этот файл, активный граф Phase 12
- источник тестовых данных: Тест 1 от 22.04.26, обратная связь пользователя
