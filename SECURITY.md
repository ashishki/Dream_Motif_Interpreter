# Security and private-data reporting policy

Dream Motif Interpreter is a single-operator, private-archive prototype, not a
hosted service. Reports are accepted only for the current default branch or an
identified privacy-safe tag and its documented local auth, ingestion,
retrieval/citation, storage, adapter, and public-fixture boundaries. There is no
production deployment, public archive access, clinical use, or security SLA.

Do not open a public issue for a suspected vulnerability or private-data
exposure. Email `verter25@gmail.com` with subject
`Dream_Motif_Interpreter security report`. Include the exact revision,
prerequisites, a minimal authored-synthetic reproduction, impact, and suggested
mitigation. Keep the first message minimal. Do not attach private dreams,
journal text, interpretations, Telegram/Google exports, prompts or provider
output, voice files, database content, credentials, tokens, `.env`, private
URLs, local paths, or an exploit against a system or data you do not own. A
safer detail-transfer path can be agreed before details are sent.

GitHub private vulnerability reporting is not assumed to be enabled. Use a
GitHub private advisory form only if the repository Security page visibly
offers **Report a vulnerability**. This maintainer-run prototype cannot promise
a response or remediation deadline.

If a credential or private record is exposed, stop publication and rotate or
revoke affected credentials. Removing a later commit does not retract copies
already fetched. Follow `docs/PUBLIC_FIXTURE_PRIVACY.md` for the public/private
fixture boundary.
