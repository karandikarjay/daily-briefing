# Future Appetite

This repository contains one autonomous Codex skill and a small shell launcher. All editorial preferences, research, formatting, media, review, and delivery instructions live in `skills/future-appetite/SKILL.md`. `.agents/skills/future-appetite` links to that same skill. Do not reintroduce a Python application, composition schemas, a separate renderer, or an editorial pipeline.

## Running

Production uses the SSH alias `daily-briefing-prod` and checkout `~/daily-briefing`. Use the alias; keep actual hostnames, usernames, and credentials out of Git. Codex CLI 0.154.0 is installed at `/opt/codex/0.154.0/`, with `codex` on PATH. The launcher selects `gpt-6-astra`.

- `./run.sh preview`: research and save an edition without sending.
- `./run.sh personal`: send one edition only to the configured personal recipient when explicitly authorized.
- `./run.sh group`: production only; requires `state/group-enabled` and standing schedule authorization. Never use for development/testing.

During the September 21 architecture cutover, Jay authorized a production personal test. Group delivery remains disabled until Jay approves that email. The skill cannot enable its own group schedule. Once approved, the weekday job runs at 6 a.m. America/New_York, accounting for daylight saving time.

The `.env` file is trusted shell syntax, permissions 0600, and is never committed. It provides `OPENAI_API_KEY`, `GOOGLE_USERNAME`, `PERSONAL_RECIPIENT`, and `RECIPIENT_EMAILS`. Existing Google OAuth credentials live outside the repository in the account-specific `gws-as` profile. Use `gws-as` for all email access and sending. The newsletter's explicit invocation authorization governs delivery; ordinary correspondence still follows Jay's global email conventions. No Gmail drafts.

Production tools: Codex, Bubblewrap (its Linux shell sandbox), Bash, coreutils (`flock`, `timeout`), Git, jq, curl, Node.js, gws/gws-as, Chrome, and rsvg-convert. General-purpose installed tools are dependencies, not another application to maintain here.

## State and investigation

`runs/` contains private per-run output, notes, media, launch logs, send attempts, provider receipts, and final status. `state/history.json` preserves legacy group coverage; `state/group-history.md` records new group editions. Personal sends never update group history. `previews/` preserves historical evidence. None belongs in Git.

The launcher prevents concurrent runs and repeated group attempts on the same Eastern date. An unsuccessful or uncertain attempt also blocks unattended retries. Before any retry, inspect the run and Gmail Sent. Never erase an attempt to bypass duplicate protection or resend blindly. A Codex exit code alone is not proof of delivery: inspect `status.json`, the provider receipt, and Sent confirmation. Gmail acceptance is not proof of external inbox delivery.

No Python watchdog remains. The Codex monitoring task reads these artifacts through SSH without running the newsletter or sending mail. Preserve its existing enabled/paused preference. No automatic service-notice emails go to the group.

## Changes and deployment

Inspect local and production Git status before editing/deploying; preserve unrelated work. Validate shell changes with `bash -n` and meaningful isolated process tests. Validate skill frontmatter with the installed skill-creator validator. Test editorial behavior with a preview or an explicitly authorized personal run, never a development group send.

After validated changes, commit the task's changes, push to GitHub `origin/master`, and sync production with `git pull --ff-only origin master`. Verify matching local/GitHub/production commits and clean working trees. Never force-push, discard changes, or deploy an unmerged feature branch. Keep a Git rollback point when replacing architecture; archived artifacts are data, not a parallel running pipeline.

`CLAUDE.md` is a relative symlink to this file. Keep it intact.
