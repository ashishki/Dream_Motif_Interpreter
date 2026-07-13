# Public fixture privacy policy

Status reviewed: 2026-07-13

## Purpose and boundary

Dream Motif Interpreter is a single-operator, private-archive prototype. Public
issues, pull requests, tests, and evidence must be reproducible without access
to the operator's Google Docs, Telegram messages, database, prompts, model
outputs, voice files, credentials, or local paths.

The default and preferred public fixture is authored from scratch. Synthetic
records must not paraphrase or lightly redact a private dream, conversation, or
interpretation. Removing a name is not sufficient when imagery, chronology,
relationships, or rare details can still identify a person or source record.

Never place any of the following in Git, an issue, a pull request, CI output, or
a public evidence pack:

- private dream/journal text, annotations, interpretations, feedback, or motif
  history;
- Telegram chat IDs, usernames, exports, messages, voice/audio, or WebApp
  initialization data;
- Google document IDs, service-account files, OAuth material, provider prompts
  or outputs, API keys, tokens, `.env` files, database dumps, or backups;
- names, contacts, account identifiers, precise dates/locations, private URLs,
  local absolute paths, or stable source-system IDs;
- psychological or clinical labels presented as facts about a person.

If private material or a credential is exposed, stop publication. Remove it
from the proposed change, rotate or revoke the credential through its provider,
and follow the email-first private route in [SECURITY.md](../SECURITY.md).
GitHub private vulnerability reporting is not assumed to be enabled; use an
advisory only when the repository Security page visibly offers that option. A
later deletion from Git does not revoke a credential or erase copies already
fetched.

## Allowed public contribution shapes

The public intake is deliberately limited to:

1. a deterministic adapter-contract defect reproduced with fake transport and
   authored-synthetic input;
2. a retrieval, citation, abstention, parser, privacy, or evidence-verifier
   regression with a minimal synthetic test;
3. a bounded adapter proposal whose network destination and side effects are
   fixed by configuration, disabled by default, and replaced by fake transport
   in CI;
4. a correction to public documentation or an existing synthetic data card.

Generic feature requests, private-corpus access requests, live-provider
experiments, diagnosis/therapy features, and broad Telegram or hosted-product
roadmaps are outside this surface. A proposed adapter does not become supported
merely because an issue or pull request exists.

## Creating a privacy-safe fixture

1. Write the record from scratch using invented people-free scenes and neutral
   objects. Do not start from private text and redact it.
2. Use new synthetic IDs with no mapping to runtime IDs. Omit dates, locations,
   contacts, URLs, accounts, and source-system identifiers.
3. Declare `provenance=handcrafted-synthetic` and the exact schema/version.
4. Add expected behavior for both answerable and no-answer or rejection paths;
   do not tune only for a passing example.
5. Run the conservative marker scan and exact-citation tests. Review the bytes
   manually because marker scans cannot prove anonymity or non-derivation.
6. Record the command, input hashes, evaluator revision, limitations, and
   whether any network/provider path ran.

For the current public replay:

```bash
python3 scripts/eval_public_fixture.py \
  --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json
python3 -m pytest tests/unit/test_public_fixture_eval.py -q
```

Its [data card](../evals/privacy_safe_retrieval_v1/DATA_CARD.md) and
[machine-readable report](../reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json)
are authoritative. The six documents and eight cases validate only a small
in-memory lexical ranking, abstention, source-attribution, and character-offset
citation contract. They do not validate the private corpus, live pgvector
retrieval, interpretations, longitudinal value, clinical validity, external
users, or production operation.

## Review and contribution rule

Every public adapter/test contribution must include a privacy-safe fixture and
a deterministic failing-then-passing regression. Reviewers reject unexplained
fixture provenance, private/source-derived text, undeclared network calls,
arbitrary destinations, hidden side effects, or claims broader than the raw
artifact. Real operator feedback can be documented only with explicit consent
and a separate privacy review; it must never be manufactured from synthetic
fixtures.

This policy is an engineering publication boundary, not a general anonymity
guarantee, clinical policy, or legal advice.
