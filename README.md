# Future Appetite

One Codex skill researches, writes, designs, reviews, and delivers a daily briefing on animal advocacy, alternative protein, and AI. GPT-6 Astra owns the editorial workflow and resolves source problems directly.

- [The skill](skills/future-appetite/SKILL.md) contains the entire brief and workflow.
- `run.sh` starts one unattended Codex session, locks concurrent runs, captures output, and prevents repeated group attempts.
- [AGENTS.md](AGENTS.md) describes deployment, tools, and operational boundaries.

On the production Linux server:

```bash
./run.sh preview   # Save only
./run.sh personal  # Explicitly authorized personal test
./run.sh group     # Scheduled production only, after approval
```

Configure the four values in `.env.sample` in a private `.env` using valid shell quoting. Provision the sending account's encrypted `gws-as` login outside the repository. No credentials, recipient list, history, or generated editions are tracked.

The weekday schedule is 6 a.m. America/New_York. Group sending requires `state/group-enabled`, created by the operator only after Jay approves the personal test. The skill must never enable it itself.

Each `runs/<timestamp>-<mode>-<pid>/` retains the edition, sources, images, process log, and status. For sends it also retains the exact MIME message, attempt, provider response, and Sent confirmation. On an uncertain send, investigate Sent before taking any further action. Do not retry automatically.

Legacy editions and group history remain private archives. The prior Python application is recoverable from Git history; it is no longer part of the active system.
