# Task Graph — Dream Motif Interpreter Phase 14

Version: 1.0
Last updated: 2026-04-24
Status: Planning — source: Тест 2 (23.04.26)

## 1. Purpose

This file is the implementation task graph for Phase 14 of Dream Motif Interpreter.

Phase 14 implements bidirectional synchronization with Google Docs: the ability to **write**
a newly recorded dream from the bot directly into the user's Google Doc, so that the journal
in Google Docs stays up to date without manual copy-paste.

This phase is kept separate from Phase 13 because it requires a developer-level infrastructure
prerequisite (Google OAuth2 / service account with write scope) that blocks all workstreams
and cannot be resolved through chat. All workstreams in this phase are sequential.

## 2. Why this phase exists

- Phase 11 added `create_dream` (records a dream in the internal DB via chat)
- Тест 2 confirmed: the user expects the bot to also append the dream to Google Docs
- The bot correctly explained the limitation — it can only read Google Docs, not write
- Read access uses a service account; write access requires an additional credential scope
- Without write access, the user must manually copy entries from the bot into Google Docs

## 3. How To Use This File

- read WS-14.1 first — it is a developer prerequisite, not a coding task
- do not start WS-14.2 without the credentials from WS-14.1 being in place in `.env`
- do not change database schema — no schema changes are planned in this phase

Reference documents:

- `app/services/gdocs_client.py`
- `app/assistant/facade.py`
- `app/assistant/tools.py`
- `app/shared/config.py`
- `docs/ENVIRONMENT.md`
- `docs/DEPLOY.md`

## 4. Dependency Graph

```
WS-14.1 (dev: credentials + env) ──► WS-14.2 (write client) ──► WS-14.3 (facade) ──► WS-14.4 (create_dream integration) ──► WS-14.5 (prompt)
```

All workstreams are sequential. WS-14.1 is a blocking prerequisite.

---

## WS-14.1: Настройка учётных данных для записи в Google Docs [Dev Task]

Owner:      разработчик (не codex)
Phase:      14
Type:       infrastructure / credentials
Depends-On: none
Priority:   P0 — блокирует все остальные WS

Objective: |
  Google Docs API поддерживает запись только при наличии соответствующих OAuth2 scope.
  Текущая аутентификация (GOOGLE_SERVICE_ACCOUNT_FILE или OAuth refresh token) настроена
  только на чтение (scope: .../auth/documents.readonly).

  Разработчику необходимо расширить права доступа до полного scope и обновить учётные данные.

Acceptance-Criteria:
  - id: AC-1
    description: "Service account или OAuth2 credentials имеют scope https://www.googleapis.com/auth/documents (read+write), а не .readonly."
  - id: AC-2
    description: "Новые credentials сохранены в GOOGLE_SERVICE_ACCOUNT_FILE (или обновлены GOOGLE_REFRESH_TOKEN / GOOGLE_CLIENT_SECRET) в production .env."
  - id: AC-3
    description: "Ручная проверка: GDocsClient может вызвать documents().batchUpdate() без ошибки 403."
  - id: AC-4
    description: "ENVIRONMENT.md обновлён: описаны необходимые Google API scopes; разграничены read-only и read-write сценарии."
  - id: AC-5
    description: "Если используется service account — документирован процесс расшаривания Google Doc на service account email (Write permission)."

Files:
  - docs/ENVIRONMENT.md   (описание scopes + процедура setup)
  - .env (production, не в репо)

Context-Refs:
  - app/services/gdocs_client.py (GDocsClient — текущий клиент)
  - docs/ENVIRONMENT.md

Notes: |
  Два варианта:
  1. Service account: скачать ключ с scope=documents (не documents.readonly);
     дать права Editor на Google Doc (Share → service account email → Editor).
  2. OAuth2 refresh token: при получении refresh token указать полный scope.
  Вариант 1 предпочтителен для unattended server-side write.

---

## WS-14.2: Метод записи в Google Docs в GDocsClient

Owner:      codex
Phase:      14
Type:       services
Depends-On: WS-14.1
Priority:   P0

Objective: |
  GDocsClient умеет только читать документы (fetch_document). Нужен метод
  append_text(doc_id, text) — добавляет форматированный текст в конец документа
  через Google Docs API batchUpdate (insertText request).

Acceptance-Criteria:
  - id: AC-1
    description: "GDocsClient содержит метод append_text(doc_id: str, text: str) -> None."
  - id: AC-2
    description: "Метод использует documents().batchUpdate() с insertText в конец документа (endOfSegmentLocation)."
  - id: AC-3
    description: "Перед вставкой добавляется разделитель: две пустые строки, затем текст."
  - id: AC-4
    description: "При ошибке (403, 404, quota) — поднимается GDocsWriteError с понятным сообщением."
  - id: AC-5
    description: "Новый класс исключения GDocsWriteError определён в gdocs_client.py рядом с GDocsAuthError."
  - id: AC-6
    description: "Юнит-тест с mock HTTP: append_text вызывает batchUpdate с корректным payload."

Files:
  - app/services/gdocs_client.py  (append_text, GDocsWriteError)

Context-Refs:
  - app/services/gdocs_client.py:1–96
  - https://developers.google.com/docs/api/reference/rest/v1/documents/batchUpdate

Notes: |
  Google Docs batchUpdate insertText payload:
    {
      "requests": [{
        "insertText": {
          "location": {"index": 1},  // начало документа не подходит
          "text": "..."
        }
      }]
    }
  Для вставки в конец — получить endIndex из getDocument() или использовать
  "endOfSegmentLocation": {"segmentId": ""}.
  Наиболее надёжный вариант: сначала get() для получения endIndex последнего элемента,
  затем insertText по этому индексу.

---

## WS-14.3: write_dream_to_google_doc в AssistantFacade

Owner:      codex
Phase:      14
Type:       facade
Depends-On: WS-14.2
Priority:   P0

Objective: |
  AssistantFacade нужен метод write_dream_to_google_doc, который форматирует запись сна
  и записывает её в указанный Google Doc через GDocsClient.append_text.

Acceptance-Criteria:
  - id: AC-1
    description: "write_dream_to_google_doc(dream_id: uuid.UUID, doc_id: str | None) -> bool принимает UUID сна, загружает запись из БД, форматирует и записывает в Google Doc."
  - id: AC-2
    description: "Если doc_id=None — использует primary Google Doc (GOOGLE_DOC_ID из settings, с учётом runtime override из WS-13.1)."
  - id: AC-3
    description: "Формат записи в Google Doc: '<дд.мм.гг> - <Название>\\n\\n<полный текст сна>\\n'."
  - id: AC-4
    description: "При GDocsWriteError — метод возвращает False и логирует ошибку (не поднимает исключение наружу)."
  - id: AC-5
    description: "При успехе — возвращает True."
  - id: AC-6
    description: "Юнит-тест: при успешном append_text метод возвращает True; при GDocsWriteError — False."

Files:
  - app/assistant/facade.py  (write_dream_to_google_doc)

Context-Refs:
  - app/assistant/facade.py (create_dream — смежный метод)
  - app/services/gdocs_client.py (GDocsClient.append_text из WS-14.2)

Notes: |
  Получить raw_text из DreamEntry по dream_id. Загрузить запись через
  session_factory SELECT по id. Форматировать согласно AC-3.
  Не обновлять source_doc_id в БД — запись уже создана в create_dream.

---

## WS-14.4: Интеграция write_dream_to_google_doc в create_dream flow

Owner:      codex
Phase:      14
Type:       facade + tools
Depends-On: WS-14.3
Priority:   P0

Objective: |
  После создания записи сна в БД через create_dream бот должен автоматически
  записывать её в Google Doc. Если запись в Google Doc не удалась — пользователь
  должен быть об этом уведомлён явно.

Acceptance-Criteria:
  - id: AC-1
    description: "create_dream в facade после успешного INSERT вызывает write_dream_to_google_doc(dream_id, doc_id=None)."
  - id: AC-2
    description: "CreatedDreamItem содержит поле written_to_google_doc: bool."
  - id: AC-3
    description: "Вывод инструмента create_dream: если written_to_google_doc=True — 'Запись создана и добавлена в Google Doc.'; если False — 'Запись создана в локальной базе, но добавить в Google Doc не удалось. Проверьте подключение к Google Docs.'."
  - id: AC-4
    description: "Сбой записи в Google Doc НЕ откатывает создание записи в БД — это разные транзакции."
  - id: AC-5
    description: "Юнит-тест: при успехе write_dream_to_google_doc → written_to_google_doc=True в выводе; при ошибке → False с предупреждением."

Files:
  - app/assistant/facade.py  (create_dream, CreatedDreamItem)
  - app/assistant/tools.py   (вывод инструмента create_dream)

Context-Refs:
  - app/assistant/facade.py:230–317 (create_dream)
  - app/assistant/facade.py:83 (CreatedDreamItem)
  - app/assistant/tools.py:228–254 (execute_tool create_dream)

Notes: |
  Порядок операций в create_dream:
  1. INSERT в dream_entries (существующая логика)
  2. write_dream_to_google_doc(created_id) — после commit
  3. Вернуть CreatedDreamItem с written_to_google_doc
  Шаги 1 и 2 в разных try-except блоках.

---

## WS-14.5: Обновление SYSTEM_PROMPT для двусторонней синхронизации

Owner:      codex
Phase:      14
Type:       prompt
Depends-On: WS-14.4
Priority:   P1

Objective: |
  После реализации записи в Google Doc нужно обновить SYSTEM_PROMPT, чтобы:
  - бот корректно описывал возможности (двусторонняя синхронизация)
  - при неудаче записи в Google Doc — давал чёткое объяснение и что делать дальше
  - не упоминал «требуется разработчик» когда write уже реализован

Acceptance-Criteria:
  - id: AC-1
    description: "Archive Mutation Rules в SYSTEM_PROMPT обновлены: create_dream создаёт запись в БД и добавляет её в Google Doc."
  - id: AC-2
    description: "Инструкция при сбое записи в Google Doc: сообщить пользователю, что запись сохранена в системе, но в Google Doc не добавлена; предложить trigger_sync или попробовать позже."
  - id: AC-3
    description: "Удалена/обновлена любая инструкция об ограничении write-доступа к Google Docs (эти ограничения сняты в Phase 14)."

Files:
  - app/assistant/prompts.py  (SYSTEM_PROMPT — Archive Mutation Rules)

Context-Refs:
  - app/assistant/prompts.py:13–21

---

## 5. Phase Gate

Phase 14 считается завершённой когда:

- [ ] [Dev] Service account / OAuth2 credentials настроены на scope=documents write (WS-14.1)
- [ ] GDocsClient.append_text записывает текст в конец Google Doc без ошибок (WS-14.2)
- [ ] write_dream_to_google_doc возвращает True после успешной записи (WS-14.3)
- [ ] create_dream автоматически пишет в Google Doc; результат виден в выводе инструмента (WS-14.4)
- [ ] SYSTEM_PROMPT корректно описывает двустороннюю синхронизацию (WS-14.5)
- [ ] Сбой write НЕ откатывает создание записи в БД; пользователь уведомлён явно (WS-14.4 AC-4)

## 6. Continuity Notes

- Phase 14 разблокируется после выполнения WS-14.1 разработчиком
- Пока WS-14.1 не выполнен — codex может реализовать WS-14.2–14.5 с mock credentials,
  но полное E2E-тестирование невозможно без реальных write-credentials
- Источник: Тест 2 (23.04.26), ответ бота о необходимости developer action
