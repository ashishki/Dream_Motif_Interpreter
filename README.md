# Dream Motif Interpreter

Приватная система анализа сновидений для одного пользователя.

Принимает записи снов из Google Docs, хранит и курирует темы, поддерживает семантический поиск, индуцирует абстрактные мотивы, обогащает их внешними культурными параллелями и предоставляет Telegram-интерфейс с голосовым вводом и обратной связью.

**Статус: Phases 1–11 complete · Phase 6 (universal ingestion) complete · 305 tests passing**

---

## Возможности

### Ядро архива (Phases 1–5)
- FastAPI API: синхронизация, просмотр снов, поиск, курирование тем, паттерны, откат
- PostgreSQL 16 + pgvector как система истины
- Redis для очередей и координации воркеров
- Ingestion из Google Docs
- LLM-assisted: извлечение тем, grounding, метафорный поиск
- Append-only annotation versioning (история всех мутаций)

### Telegram-интерфейс (Phases 6–7)
- Приватный бот с allowlist по `chat_id`
- Текстовый разговорный интерфейс (Claude, ограниченный tool loop)
- Голосовые сообщения → async транскрипция (OpenAI Whisper)
- Персистентные chat-сессии через перезапуски (`bot_sessions`)
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
- Идемпотентность по `external_id + content_hash`; embedding не запускается для не прошедших валидацию документов
- Operator controls: явное назначение профиля на источник/клиента через env config; low-confidence warnings; folder intake

### Цикл обратной связи (Phase 11)
- Reply на сообщение бота с `"4"` или `"5 Отлично"` → оценка + комментарий сохраняются
- Fallback: одиночная цифра `1–5` без Telegram-reply тоже принимается
- Последние 20 комментариев и низких оценок (≤2) инжектируются в system prompt перед каждым ответом — ассистент адаптирует стиль и глубину
- `GET /feedback` — просмотр рейтингов с пагинацией
- Хранится в `assistant_feedback`, изолировано от RAG-пайплайна

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
  workers/       background jobs (ingest, indexing, transcription, cleanup)

alembic/         schema migrations (001–012)
docs/            architecture, planning, runbooks, ADRs, user guide
tests/           unit + integration (305 passed, 9 skipped)
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
| `API_KEY` | Backend REST auth | — |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Путь к service-account JSON для Google Docs | `""` |
| `AUTO_SYNC_ENABLED` | Включить лёгкий metadata-ping и автосинк из Google Docs | `false` |
| `AUTO_SYNC_INTERVAL_SECONDS` | Интервал metadata-ping перед автосинком | `300` |
| `MOTIF_INDUCTION_ENABLED` | Мотивная индукция | `false` |
| `RESEARCH_AUGMENTATION_ENABLED` | Внешний поиск параллелей | `false` |
| `RESEARCH_API_KEY` | Ключ внешнего поиска | `""` |

Полный список: [ENVIRONMENT.md](docs/ENVIRONMENT.md)

**Запуск:**

```bash
alembic upgrade head
python3 -m app.telegram
python3 -m app.auto_sync
```

**Локальный запуск в фоне:**

```bash
./scripts/start_local_stack.sh
./scripts/status_local_stack.sh
./scripts/stop_local_stack.sh
```

**Docker Compose:**

```bash
docker compose up
```

## Local Checkpoint

По состоянию на 2026-04-20/21 локальная установка доведена до рабочего чекпоинта:

- `.venv` создан, зависимости установлены
- PostgreSQL доступен на `127.0.0.1:5433`, Redis на `127.0.0.1:6379`
- БД `dream_motif` создана, `alembic upgrade head` проходит
- `GET /health` возвращал `{"status":"ok","index_last_updated":null}`
- Google Docs auth в коде поддерживает и OAuth env flow, и service-account file через `GOOGLE_SERVICE_ACCOUNT_FILE`

Локальный тестовый чекпоинт:

- подтвержденно проходят `tests/unit/test_config.py` (`8 passed`) и `tests/unit/test_gdocs_client.py` (`7 passed`)
- `.venv/bin/pytest --collect-only -q` теперь успешно собирает `295` тестов

Следующий практический шаг:

- задать реальный `GOOGLE_DOC_ID`
- проверить живой `GDocsClient.fetch_document()`
- после живой проверки Google Docs перейти к полному `pytest` прогону внутри `.venv`

---

## Документация

| Документ | Назначение |
|---|---|
| [**Гайд пользователя (RU)**](docs/USER_GUIDE_RU.md) | Что умеет бот и как им пользоваться |
| [Architecture](docs/ARCHITECTURE.md) | Форма системы, границы выполнения |
| [Feature Spec](docs/spec.md) | Scope backend и интерфейса |
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
