# Dream Motif Interpreter

Локальный single-operator прототип для работы с приватным архивом записей.

Принимает записи снов из Google Docs, хранит и курирует темы, поддерживает семантический поиск, индуцирует абстрактные мотивы, обогащает их внешними культурными параллелями и предоставляет Telegram-интерфейс с голосовым вводом, записью снов, контекстными заметками и кнопками полного текста.

**Статус: case-study prototype, не product release.** Репозиторий содержит реализованные
компоненты и детерминированный synthetic eval, но не доказывает hosted/production operation,
внешних пользователей, longitudinal value или качество на произвольных документах.

Приватный корпус, Telegram-сообщения, credentials и live outputs не входят в публичный
репозиторий. Исторические документы с пометками «Тест» описывают только private operator
review и не являются external validation. Boundary: reflective journaling, not psychological
diagnosis; система не предназначена для психологической или клинической диагностики.

Dream Memory Map остаётся design/prototype direction, а не заявленной готовой
пользовательской поверхностью: `docs/DREAM_MEMORY_MAP.md`.

## Public reviewer path

Privacy-safe evidence можно воспроизвести без private data, PostgreSQL, provider keys или
сетевых вызовов:

```bash
python3 scripts/eval_public_fixture.py \
  --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json
python3 -m pytest tests/unit/test_public_fixture_eval.py -q
```

Набор содержит 6 handcrafted-synthetic документов и 8 retrieval cases. Tracked report
проверяет ranking/abstention, expected-source recall, точность source attribution и дословные
character-offset citations. Все gates этого ограниченного replay проходят; это не результат
live hybrid retrieval и не оценка интерпретаций. См. [data card](evals/privacy_safe_retrieval_v1/DATA_CARD.md)
и [content-addressed report](reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json).

## Public contribution boundary

The public maintainer surface accepts only bounded adapter/test defects or
proposals that can be reproduced with authored-synthetic fixtures. Read the
[public-fixture privacy policy](docs/PUBLIC_FIXTURE_PRIVACY.md), then use the
[bounded adapter/test form](https://github.com/ashishki/Dream_Motif_Interpreter/issues/new?template=bounded-adapter-test.yml).
It is not a request for private archives, Telegram exports, credentials, live
provider output, psychological interpretation, or a general product roadmap.
Suspected vulnerabilities or private-data exposure follow
[SECURITY.md](SECURITY.md), not the public form.


---

## Возможности

### Ядро архива (Phases 1–5)
- FastAPI API: синхронизация, просмотр снов, поиск, курирование тем, паттерны, откат
- PostgreSQL 16 + pgvector как система истины, включая durable outbox/receipts
- Redis для sync-state и короткоживущего Telegram-контекста с TTL
- Ingestion из Google Docs
- LLM-assisted: извлечение тем, grounding, метафорный поиск
- Append-only annotation versioning (история всех мутаций)

### Telegram-интерфейс (Phases 6–7)
- Приватный бот с allowlist по `chat_id`
- Текстовый разговорный интерфейс (Claude, ограниченный tool loop)
- Голосовые сообщения → async транскрипция (OpenAI Whisper)
- Персистентные chat-сессии через перезапуски (`bot_sessions`)
- Контекстные заметки к одному сну через Telegram reply, к последнему явно показанному сну
  и к нескольким снам из последней подборки с preview-подтверждением
- Кнопки полного текста для снов, реально показанных в поисковой выдаче или списке
- Отслеживание жизненного цикла медиафайлов + авточистка

### Операционный harden (Phase 8)
- Структурированные логи (structlog JSON, PII-redaction, event ID)
- OTel tracing (готово к Jaeger/OTLP)
- Runbook'и для бота и голосового пайплайна

### Мотивный слой (Phase 9)
- Open-vocabulary induction: `ImageryExtractor` → `MotifInductor` → `MotifGrounder`
- Мотивы в `motif_inductions` — изолировано от `dream_themes`
- REST: `GET /dreams/{id}/motifs`, `PATCH /dreams/{id}/motifs/{motif_id}`
- Инструмент ассистента `get_dream_motifs` (при `MOTIF_INDUCTION_ENABLED=true`)

### Исследовательское обогащение (Phase 10)
- `ResearchRetriever`: внешний поиск (provider-agnostic, reference: Tavily)
- `ResearchSynthesizer`: LLM-извлечение культурных/мифологических параллелей
- Уровень доверия: только `speculative | plausible | uncertain`
- REST: `GET /motifs/{id}/research`, `POST /motifs/{id}/research`
- Инструмент `research_motif_parallels` с обязательным подтверждением (при `RESEARCH_AUGMENTATION_ENABLED=true`)

### Универсальный source intake (tasks.md Phase 6)
- Source connector abstraction: `SourceDocument`, `SourceDocumentRef`, `GoogleDocsSourceConnector`
- `NormalizedDocument` contract — сегментация принимает только нормализованный вход, не сырые SDK-ответы
- Parser profiles: `default`, `dated_entries`, `heading_based` с авто-определением и явным override
- Канонический staged pipeline: source connector → normalized document → parser profile → dream entry candidates → validated dream entries → embeddings/indexing
- Идемпотентность по устойчивому ключу позиции записи внутри источника; `content_hash` служит
  проверкой изменений, а не глобальной идентичностью записи. Embedding не запускается для не
  прошедших валидацию документов
- Ручные правки заголовка/даты в Google Docs обновляют ту же запись; изменение тела обнаруживается как конфликт и не создаёт тихий дубль
- Operator controls: явное назначение профиля на источник/клиента через env config; low-confidence warnings; folder intake

### Цикл обратной связи (Phase 11)
- Numeric feedback в Telegram feature-gated и по умолчанию выключен, чтобы цифры `1–5`
  не конфликтовали с выбором вариантов в обычном диалоге
- Emoji reactions могут сохраняться как сырой сигнал, если включена обработка реакций
- Сохранённый feedback изолирован от RAG-пайплайна и не меняет архив снов
- `GET /feedback` — просмотр рейтингов с пагинацией
- Хранится в `assistant_feedback`

### UX-исправления по итогам первого private operator review (Phase 12)

Исторический backlog из первого private operator review (Тест 1, 22.04.26):

- `get_dream_motifs` теперь возвращает UUID мотива — поиск параллелей разблокирован
- Запрет markdown в ответах: никаких `**`, даты в формате `дд.мм.гг`, списки нумерованные
- `list_recent_dreams` показывает превью текста и темы вместо UUID и счётчика слов
- `search_dreams` возвращает название сна и доказательный фрагмент без user-facing score/strength
- `get_dream` очищает `*` и `<` из текста Google Docs; лимит текста увеличен до 2000 символов
- `create_dream` срабатывает на «занеси в архив», «запиши это», «сохрани этот сон» и др.
- Заголовок при сохранении сна: «дд.мм.гг - Название» или «дд.мм.гг, без названия»
- Поток параллелей упрощён: без длинного преамбула, без «архетип», без итогового обобщения
- Новый инструмент `manage_archive_source`: смена `GOOGLE_DOC_ID` из чата без перезапуска

Подробнее: [docs/PHASE12_RELEASE_NOTES.md](docs/PHASE12_RELEASE_NOTES.md)
### Мультисурс, точный поиск, группировка фрагментов (Phase 13)

Исторический backlog из второго private operator review (Тест 2, 23.04.26):

- Поддержка нескольких Google Docs: `GOOGLE_DOC_IDS` (список через запятую); `trigger_sync` синхронизирует все
- `manage_archive_source`: добавлены действия `list`, `add`, `remove` — управление источниками из чата
- Терминология: «архив», «база», «хранилище» в ответах бота означает Google Docs, не внутреннюю БД
- Подсказка оценки ответа переведена на русский язык
- Новый инструмент `search_dreams_exact`: точный FTS-поиск без порога и без семантики, русская морфология, до 20 результатов
- Извлечение цитаты: `search_dreams_exact` показывает точную фразу из текста сна, содержащую искомое слово
- `RESULT_LIMIT` увеличен с 5 до 20; несколько фрагментов одного сна группируются под одним заголовком
- `SYSTEM_PROMPT`: правило выбора инструмента, формат с цитатой, запрет обрезки «и другие»


### Надёжная запись снов и Google Docs mirror (Phase 14+)

Реализована запись новых снов из бота напрямую в Google Doc:

- `create_dream` одной транзакцией сохраняет `DreamEntry` и durable jobs, поэтому ответ пользователю не зависит от LLM, embeddings или Google API
- повторная доставка одного Telegram-сообщения определяется по стабильному event key и не
  создаёт дубль; новое сообщение с тем же текстом считается отдельной допустимой записью
- индексирование, анализ, мотивы и Google Docs выполняются независимо и повторяются после временных сбоев/рестарта
- `GDocsClient` записывает форматированную запись («дд.мм.гг - Название\n\nтекст») через Google Docs API batchUpdate
- DB receipt и document-side named range делают повторную доставку идемпотентной
- активный Google Doc для записи сохраняется в runtime-конфиге и не откатывается к `.env` после рестарта
- Сбой любого post-capture этапа не откатывает каноническую запись в PostgreSQL; статус остаётся честно видимым как pending/retryable/failed
- заметка и её задания `index`/`gdocs` также фиксируются транзакционно; подтверждение в Telegram
  означает «сохранено и принято в очередь», а не уже завершённую доставку во внешние системы
- `GDocsWriteError` — новый класс ошибки для всех write-сценариев (403, 404, quota, auth)

Примечание: Google Docs mirror требует OAuth credentials или service account с правами записи (scope=documents). Сам сон уже сохранён до сетевой попытки.

### Telegram UX hardening (Phases 25–27)

Свежие private-operator fixes вокруг Telegram-поведения:

- после save-card `✅ Сон сохранён` бот запоминает связанный `dream_id`, поэтому
  Telegram reply на это сообщение может добавить заметку именно к сохранённому сну
- если пользователь написал `Добавь заметку к этому сну: ...`, но цель неясна, текст заметки
  временно сохраняется; затем можно ответить `к этому` на сообщение с одним конкретным сном
- короткое `К этому` не отправляется в LLM как новый сон и не должно случайно создавать запись
- вставка заметок в Google Doc сначала ищет точный heading, затем допустимый похожий heading с
  той же датой, чтобы ручная правка/усечение названия не блокировали заметку
- семантический поиск остаётся поведением по умолчанию; буквальный word/FTS-поиск вызывается
  только отдельным точным запросом
- кнопки `Полный текст` / `Текст N` строятся по видимым снам в ответе, а не по скрытому
  количеству retrieval-кандидатов

---

## Repository Map

```text
app/
  api/           FastAPI routes (sync, dreams, search, themes, patterns, versioning,
                 motifs, research, feedback)
  assistant/     bounded facade, chat loop, session persistence, voice media
  llm/           model wrappers and prompts
  models/        SQLAlchemy models (dreams, themes, sessions, voice events,
                 motif_inductions, research_results, assistant_feedback)
  research/      ResearchRetriever + ResearchSynthesizer
  retrieval/     chunking, embedding, pgvector ingestion and query
  services/      domain services (analysis, patterns, segmentation, taxonomy,
                 versioning, imagery, motif_inductor, motif_grounder,
                 motif_service, research_service, feedback_service)
  shared/        config, tracing, DB session factory
  telegram/      bot runtime, handlers, voice download
  workers/       durable post-capture/voice recovery, ingest, indexing and cleanup

alembic/         schema migrations
docs/            architecture, planning, runbooks, ADRs, user guide
evals/           public synthetic fixtures and data cards
reports/         tracked bounded evidence artifacts
tests/           unit + integration checks
```

---

## Setup

**Требования:**
- Python 3.10+ (`ruff` target: py311; 3.11 preferred for new local environments)
- PostgreSQL 16 с `pgvector`
- Redis

**Переменные окружения:**

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `ANTHROPIC_API_KEY` | Chat loop (Claude) | — |
| `OPENAI_API_KEY` | Whisper + embeddings | — |
| `TELEGRAM_BOT_TOKEN` | Telegram bot | — |
| `TELEGRAM_ALLOWED_CHAT_ID` | Allowlist chat_id | — |
| `TELEGRAM_MINI_APP_URL` | URL для кнопки `/map`, открывающей Dream Memory Map как Telegram Web App | `""` |
| `TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS` | TTL для Telegram WebApp initData auth | `86400` |
| `SECRET_KEY` | Backend REST auth; use a random value of at least 32 bytes | — |
| `BUILD_SHA` | Deployed Git commit shown by `GET /health` | `unknown` |
| `APP_IMAGE_REPOSITORY` | Compose image repository for release-tagged app services | `dream-motif-interpreter` |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Путь к service-account JSON, видимый процессу | `""` |
| `GOOGLE_SERVICE_ACCOUNT_HOST_FILE` | Host path для opt-in read-only Compose mount | `""` |
| `GOOGLE_API_TIMEOUT_SECONDS` | Верхняя граница одного сетевого вызова Google API | `60` |
| `AUTO_SYNC_ENABLED` | Включить лёгкий metadata-ping и автосинк из Google Docs | `false` |
| `AUTO_SYNC_INTERVAL_SECONDS` | Интервал metadata-ping перед автосинком | `300` |
| `MOTIF_INDUCTION_ENABLED` | Мотивная индукция | `true` |
| `RESEARCH_AUGMENTATION_ENABLED` | Внешний поиск параллелей | `false` |
| `RESEARCH_API_KEY` | Ключ внешнего поиска | `""` |

Полный список: [ENVIRONMENT.md](docs/ENVIRONMENT.md)

**Запуск:**

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/pip install --no-deps -e .
alembic upgrade head
python3 -m app.telegram
python3 -m app.auto_sync
```

`uv.lock`, `requirements.lock` и `requirements-dev.lock` фиксируют один проверяемый граф
зависимостей. После осознанного изменения `pyproject.toml` обновите их через `uv lock`, затем
`uv export --frozen --no-dev --no-emit-project --no-annotate -o requirements.lock` и
`uv export --frozen --extra dev --no-emit-project --no-annotate -o requirements-dev.lock`.

**Локальный запуск в фоне:**

```bash
./scripts/start_local_stack.sh
./scripts/status_local_stack.sh
./scripts/stop_local_stack.sh
```

**Docker Compose:**

```bash
cp .env.example .env
# заполните секреты; для проверяемого deploy задайте точный commit
export BUILD_SHA="$(git rev-parse HEAD)"
./scripts/deploy_compose.sh
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Скрипт обязателен и для первого запуска, и для upgrade: он сначала останавливает `api`,
`telegram-bot` и `auto-sync`, затем поднимает инфраструктуру, применяет Alembic без активных
писателей и только после успеха запускает процессы приложения. Не заменяйте его прямым
`docker compose up` при обновлении кода или схемы.
Скрипт откажется собирать незакоммиченное дерево или маркировать образ SHA, отличным от текущего
`HEAD`, чтобы `/health` не подтверждал ложную версию.

Базовый Compose не монтирует credential-файлы и работает с OAuth-переменными либо без
Google-интеграции. Для service account укажите существующий защищённый JSON только на хосте и
явно подключите overlay:

```bash
GOOGLE_SERVICE_ACCOUNT_HOST_FILE=/absolute/path/google-service-account.json \
  BUILD_SHA="$(git rev-parse HEAD)" \
  ./scripts/deploy_compose.sh --google-service-account
```

Overlay монтирует файл read-only в `/run/secrets/google-service-account.json`; JSON не попадает
в image или named volume. Не подключайте overlay без существующего файла.

Auto-sync вынесен в optional profile и запускается только при `AUTO_SYNC_ENABLED=true`. Чтобы
включить его в тот же quiesced rollout:

```bash
BUILD_SHA="$(git rev-parse HEAD)" ./scripts/deploy_compose.sh --with-auto-sync
```

`POSTGRES_PASSWORD` обязателен: у Compose нет fallback-пароля. PostgreSQL, Redis и API по
умолчанию публикуются только на `127.0.0.1`; изменение bind-address — отдельное операторское
решение, которое требует firewall/reverse proxy и аутентификации. Секреты храните вне
репозитория. В production `health.build_sha` не должен быть `unknown`.

## Verification boundary

CI выполняет Ruff, полный pytest suite с disposable PostgreSQL/pgvector, существующий seeded
database retrieval eval и отдельный privacy-safe public replay. Placeholder credentials в CI не
дают доступ к Google Docs, Telegram или model providers. Поэтому зелёный CI подтверждает
детерминированные code/eval contracts, но не live integrations или operator outcomes.

Локальный эквивалент перед push:

```bash
.venv/bin/ruff check app/ scripts/ tests/
.venv/bin/ruff format --check app/ scripts/ tests/
.venv/bin/pytest tests/ -q --tb=short
.venv/bin/python scripts/eval_public_fixture.py \
  --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json
ENV=test TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dmi_eval \
  .venv/bin/python scripts/eval.py --task-id CI --no-write-markdown --confirm-reset
```

Для этих проверок используйте test/placeholder env, как в `.github/workflows/ci.yml`. Live
Google Docs, Telegram и provider quota проверяются отдельными smoke-тестами на operator deploy.
`scripts/eval.py` полностью пересоздаёт `public` schema, поэтому он принимает только
`TEST_DATABASE_URL` с именем базы, оканчивающимся на `_test`, `_tests`, `_eval` или
`_evaluation`, и требует `ENV=test|testing|eval|evaluation|ci`; обычный `DATABASE_URL`
скрипт намеренно игнорирует.

---

## Документация

| Документ | Назначение |
|---|---|
| [**Гайд пользователя (RU)**](docs/USER_GUIDE_RU.md) | Что умеет бот и как им пользоваться |
| [**Phase 12 Release Notes**](docs/PHASE12_RELEASE_NOTES.md) | UX-исправления по итогам первого теста |
| [Public fixture data card](evals/privacy_safe_retrieval_v1/DATA_CARD.md) | Privacy и scope публичного retrieval/citation replay |
| [Public fixture privacy policy](docs/PUBLIC_FIXTURE_PRIVACY.md) | Что допустимо в публичных fixtures/issues и как воспроизводить bounded contribution |
| [Retrieval Evaluation](docs/retrieval_eval.md) | Исторические и публичные retrieval-eval boundaries |
| [Architecture](docs/ARCHITECTURE.md) | Форма системы, границы выполнения |
| [Feature Spec](docs/spec.md) | Scope backend и интерфейса |
| [Dream Memory Map](docs/DREAM_MEMORY_MAP.md) | Phase 26 Telegram mini app / motif graph product spec |
| [Phase Plan](docs/PHASE_PLAN.md) | Декомпозиция фаз 1–11 |
| [Environment](docs/ENVIRONMENT.md) | Runtime-переменные |
| [Deployment](docs/DEPLOY.md) | Топология деплоя |
| [Telegram Interaction Model](docs/TELEGRAM_INTERACTION_MODEL.md) | Поведение бота, tool catalog |
| [Motif Abstraction](docs/MOTIF_ABSTRACTION.md) | Дизайн мотивной индукции |
| [Research Augmentation](docs/RESEARCH_AUGMENTATION.md) | Доверительная модель внешнего поиска |
| [Feedback Loop](docs/FEEDBACK_LOOP.md) | Механизм рейтинга ответов |
| [Voice Pipeline](docs/VOICE_PIPELINE.md) | Голосовой ingestion |
| [Auth and Security](docs/AUTH_SECURITY.md) | Модель доступа |
| [Decision Log](docs/DECISION_LOG.md) | Индекс архитектурных решений |
| [ADRs](docs/adr/) | Записи решений |
| [Telegram Bot Runbook](docs/RUNBOOK_TELEGRAM_BOT.md) | Операции бота |
| [Voice Pipeline Runbook](docs/RUNBOOK_VOICE_PIPELINE.md) | Операции голосового пайплайна |
