# VPS Cognition Vault

Shared vault path on this VPS:

```text
/srv/codex-entropy/repos/product-3/engineering-cognition-vault
```

Live project checkout:

```text
/srv/openclaw-you/workspace/Dream_Motif_Interpreter
```

## Role

Repo-local docs remain the source of truth for architecture, prompts, runbooks, tasks, evals, findings, decisions, and implementation facts.

The vault is a downstream navigation layer for cross-project cognition, generated indexes, and context packets. It helps agents and the operator discover project context, but it must not become the place where canonical findings, evals, or decisions are written by hand.

## Update Policy

1. Update this repository first.
2. Commit and push repo-local docs, evals, ADRs, findings, or decisions here.
3. Refresh the vault only from a sync-owner node or after an explicit operator command.

If the vault must be refreshed on this VPS, pull it first:

```bash
git -c safe.directory=/srv/codex-entropy/repos/product-3/engineering-cognition-vault \
  -C /srv/codex-entropy/repos/product-3/engineering-cognition-vault \
  pull --ff-only
```

Do not push the vault automatically from normal project work. Do not restart services for docs-only changes.
