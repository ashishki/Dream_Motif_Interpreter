# Task Graph — Dream Motif Interpreter Phase 15

Version: 1.0
Last updated: 2026-04-24
Status: Active — source: Тест 3 (24.04.26)

## 1. Purpose

Phase 15 fixes defects found in Тест 3 (24.04.26) — all related to the create_dream
/ Google Docs write flow shipped in Phase 14.

## 2. Defects

D1 (P0): Triple date in Google Doc heading.
  Root: _resolve_dream_title adds date to stored title ("21.04.26 - title").
  append_dream_entry then adds date again ("21.04.26 - 21.04.26 - title").
  If model also passed date in title param → third date.

D2 (P0): Bot asks user for today's date when user says "сегодняшним числом".
  Root: system prompt has no current date; model cannot resolve relative dates.

D3 (P0): Bot duplicates old dreams from conversation history.
  Root: model re-creates old dream text (from history) via create_dream;
  content_hash guard misses if phrasing differs; Google Doc gets duplicate.

D4 (P1): Auto-resolve "сегодня/вчера/позавчера" without asking the user.
  Root: same as D2 — no date in prompt.

## 3. Dependency Graph

WS-15.1, WS-15.2, WS-15.3 are independent and can be done in parallel.
WS-15.4 is blocked on WS-15.2 (date must be in prompt first).

---

## WS-15.1: Убрать дату из stored title; очищать дату из title param

Owner:      codex
Phase:      15
Type:       facade + services
Priority:   P0

Objective:
  _resolve_dream_title не должен добавлять дату к stored title.
  Дата — это отдельное поле dream.date; заголовок в Google Doc строится
  из date + title в append_dream_entry, а не хранится в title.
  Дополнительно: если модель передала дату внутри title param —
  append_dream_entry должен её очистить перед форматированием.

Acceptance-Criteria:
  - AC-1: _resolve_dream_title возвращает title.strip() без date-prefix.
  - AC-2: append_dream_entry стрипает leading date-pattern из title
    (regex: ^\d{2}\.\d{2}\.\d{2,4}[\s\-,]+).
  - AC-3: Stored title в БД = чистое название без даты.
  - AC-4: Heading в Google Doc = "дд.мм.гг - Название" (одна дата).

Files:
  - app/assistant/facade.py (_resolve_dream_title)
  - app/services/gdocs_client.py (append_dream_entry)

---

## WS-15.2: Инъекция текущей даты в system prompt

Owner:      codex
Phase:      15
Type:       chat / prompt
Priority:   P0

Objective:
  Модель должна знать сегодняшнюю дату при каждом запросе.
  Добавить текущую дату в system prompt в chat.py перед отправкой
  в API. Это также позволяет модели разрешать "сегодня/вчера/позавчера".

Acceptance-Criteria:
  - AC-1: В начало system_prompt добавляется строка
    "Сегодня: дд.мм.гг (YYYY-MM-DD)." перед каждым API-вызовом.
  - AC-2: При запросе "запиши сон сегодняшним числом" модель
    подставляет дату без вопроса к пользователю.
  - AC-3: "вчера" и "позавчера" разрешаются корректно.

Files:
  - app/assistant/chat.py (инъекция даты перед API-вызовом)

---

## WS-15.3: Защита от дублирования снов из истории

Owner:      codex
Phase:      15
Type:       prompt + tools
Priority:   P0

Objective:
  Модель не должна вызывать create_dream с текстом снов из истории
  переписки. Когда пользователь просит "записать сон" — он имеет в виду
  текст, который пишет прямо сейчас, а не ранее записанные сны.
  Также: вывод инструмента при created=False должен явно сообщать
  "already existed — not written to Google Doc again", чтобы модель
  не интерпретировала это как сбой и не пыталась повторить запись.

Acceptance-Criteria:
  - AC-1: SYSTEM_PROMPT содержит явный запрет использовать текст
    снов из истории переписки как аргумент raw_text для create_dream.
  - AC-2: Вывод инструмента при created=False: "Запись уже существует
    в архиве (id=...). В Google Doc повторно не записывается."
  - AC-3: При попытке создать дубль — модель сообщает об этом
    пользователю, не пишет в Google Doc повторно.

Files:
  - app/assistant/prompts.py (SYSTEM_PROMPT)
  - app/assistant/tools.py (вывод create_dream при created=False)

---

## 4. Phase Gate

- [ ] Heading в Google Doc содержит дату ровно один раз (WS-15.1)
- [ ] Stored title в БД не содержит дату (WS-15.1)
- [ ] Бот подставляет дату сам при "сегодняшним числом" (WS-15.2)
- [ ] "вчера" и "позавчера" работают без вопроса (WS-15.2)
- [ ] Дубли снов из истории не попадают в Google Doc (WS-15.3)
- [ ] created=False даёт чёткий вывод без повторной записи (WS-15.3)

## 5. Status: IN PROGRESS — 2026-04-24
