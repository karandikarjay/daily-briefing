# Future Appetite

An Axios-style briefing for Jay and other people in the vegan movement. It covers
consequential new developments in farmed-animal advocacy, alternative protein,
and AI broadly, explaining what changed and why it matters in five minutes or less.

An AI editor allocates space freely across these interests. There are no topic
quotas, fixed section order, or minimum number of stories. The writing is concise,
professional, engaging, and grounded in evidence.

## Architecture

1. **Collect:** RSS, publisher sitemaps, FAST emails, and seeded public searches
   produce a shared pool. Publisher publication evidence must fall within the
   reporting window; search timestamps and sitemap updates do not prove novelty.
2. **Investigate:** An editor chooses structured `inspect`, `research`, `verify`,
   and `finish` actions. It compares compact cards and loads full evidence on demand.
3. **Verify:** Candidates undergo an unrestricted original-announcement search
   and evidence-grounded novelty review. Private emails use a separate path without
   public search. Development records retain dated supporting and conflicting evidence.
4. **Compose:** The writer chooses the lead, ordering, depth, paragraph labels,
   and implications. Paragraphs reference exact supporting source quotations.
   Omission rationales remain in the private audit.
5. **Review:** Native JSON schemas constrain editor responses. Code checks IDs, quotations, dates, repeated events, omissions,
   word count, and media limits. GPT-5.6 Sol separately reviews the complete edition,
   including subject, intro, comparisons, and conclusions. Bounded repairs correct
   specific fields/paragraphs without changing untouched copy, or remove invalid
   developments. Exhausted repairs trigger one shorter rewrite from verified evidence,
   with prior feedback and the same review/repair checks. If that also fails review,
   prune unresolved material and independently review the shortened edition (up to
   two pruning passes). Only if no useful edition passes, send a fixed service notice
   with no unapproved stories or media. The audit retains failed reviews and drafts;
   service notices mark no stories delivered. Writer/API errors still abort.
6. **Render and deliver:** Controlled HTML components escape model text and
   construct citations from stored evidence. Optional media is archived with the
   preview. Delivery checks checksums and prevents blind duplicate sends.

The editor has no SMTP tool. Analysis must distinguish interpretation from reported
findings and avoid overstating causality, certainty, or transferability.

## Editorial configuration

`editorial.json` contains audience, purpose, voice, selection principles, topic
scopes, and budgets. Defaults:

| Setting | Default |
| --- | --- |
| Target length | About 650 words; shorter when warranted |
| Hard length ceiling | 800 words, including attribution and captions |
| Editor actions | 32 |
| Adaptive public searches | 4 |
| Candidate verifications | 10 |
| Research deadline | 900 seconds, checked between actions |
| Draft repair attempts | 2 |
| Composition deadline | 900 seconds between calls; up to 120 reserved for pruning |
| Coverage recovery | Independent review plus up to 3 additional verifications |
| Illustrations / charts | An illustration per story (up to 8); all 5 regular charts |

Initial collection and original-announcement verification searches are additional
bounded operations. In-flight calls and retries may outlast the research deadline.
Audits record actual text-model token counts; action budgets are not dollar caps.

Illustrations are clearly labeled and must not imply actual event photography.
The regular footer includes Beyond Meat stock and bond, Oatly, S&P 500, and egg prices.
Failed or stale media is omitted and logged. Each story receives an illustration prompt.
Verification preserves an exact source quote identifying the intended development,
repairs malformed candidate quotes once, and rechecks empty selections with a reason.
A separate coverage review can recover up to three missed candidates before writing.
Cached rejections exclude an event, not every development in the same roundup.

## Freshness and privacy

Every story must be anchored in a new development within the latest completed
weekday window ending at 6 a.m. America/New_York. Tuesday–Friday windows begin at
6 a.m. the previous day; Monday begins at 6 a.m. Friday. Weekend and early runs
reuse the latest completed scheduled window. Start is inclusive; end is exclusive.

Older material is explicitly dated context, never a standalone item. A newly
released evaluation of an older intervention may qualify; an old evaluation
discovered today cannot. Unknown/conflicting dates and post-cutoff evidence are excluded.

Public-query generation is isolated from private emails, editor rationales, and
private history. Only a public source or an enumerated topic can seed adaptive
research. Source documents are untrusted data, never instructions.

Exact quotation matching and model review reduce errors but cannot guarantee
truth or editorial usefulness. Retained evidence supports investigation of mistakes.

## Setup

Use the Python environment provisioned for the checkout. Dependencies are in
`requirements.txt`; Python 3.10+ is required by the type syntax.

Configure `.env` in the checkout:

- `ANTHROPIC_API_KEY`: primary text generation and verification.
- `OPENAI_API_KEY`: text fallback and optional images.
- `TAVILY_API_KEY`: discovery and original-announcement verification.
- `GOOGLE_USERNAME` / `GOOGLE_PASSWORD`: Gmail account and app password.
- `RECIPIENT_EMAILS`: production recipient list.

`.env` overrides existing environment values. Optional overrides: `AI_MODEL`,
`BRIEFING_STATE_DIR` (default `state/`), and `BRIEFING_PIPELINE` (`editor` by default;
`legacy` for rollback). `--pipeline` overrides that last setting.

Text defaults to `claude-opus-5` with the existing `gpt-5.6-sol` fallback. Whole-edition review uses `gpt-5.6-sol`, separate from the default writer; if writing falls back to OpenAI, review remains a separate call. Optional
images use `gpt-image-2.5-sunburst`, medium quality, 1536×1024 PNG.

## Preview and test

Generate a complete preview without sending email:

```bash
python main.py --dry-run
```

A dry run calls external APIs and writes local preview/rejection state. It does
not update production delivery history.

Run deterministic regression tests without external APIs or sending:

```bash
python -m unittest discover -s tests -v
```

Ignored `previews/RUN/` directories contain frozen `research-input.json`, verified
`developments.json`, structured `edition.json`, `audit.json`, `final-review.json`,
`newsletter.html`, archived media, and `delivery.json`. Evidence, emails, logs,
and credentials must not be committed.

## Evaluate changes on identical evidence

```bash
python main.py --dry-run --replay-evidence /absolute/path/to/previews/RUN/developments.json
python compare_previews.py /absolute/path/to/previews/A /absolute/path/to/previews/B
```

Replay uses the frozen reporting window, evidence, and history with the current
editorial brief. It calls text models but performs no collection, search, live media
generation, or history/rejection updates. Replay previews cannot be sent.

The comparison command uses no APIs. It reports headlines, events, topics, word
counts, review attempts, research budgets, omissions, and text usage. Human review
should assess significance, important omissions, useful implications, factual
support, repetition, voice, and reading experience. Replay tests writing/review;
live previews also test discovery.

## Delivery and rollback

**`python main.py` sends a personal preview. It is not a no-send test.** Sending
test email requires explicit approval. To send an approved saved preview:

```bash
python main.py --send-preview /absolute/path/to/previews/RUN
```

Personal delivery uses the sender's `+list` address and a `[Preview]` subject prefix.
`--send-to-everyone` is reserved for production, never development or testing.

Delivery checks HTML and editor-media hashes. Exclusive attempt markers prevent
blind duplicate sends. If SMTP fails or its outcome is uncertain, inspect Sent
before acting; never remove a marker and retry blindly.

`state/history.json` records production deliveries. Personal previews do not change
it. Same-window semantic rejections persist in `state/excluded-events.json`. A
state-directory lock prevents concurrent runs.

`--pipeline legacy` or `BRIEFING_PIPELINE=legacy` retains the old three-section
orchestration for operational rollback. Shared freshness and delivery safeguards
apply to both pipelines. See `AGENTS.md` for production sync instructions.

### Resilient editorial delivery and monitoring

Reviews identify exact fields and issue IDs. Repairs cover captions and illustration descriptions; ineffective repairs are detected before another review call. After normal and simpler recovery drafts exhaust repairs, up to two deterministic pruning passes can retain a smaller edition. Every shortened edition still needs independent whole-edition approval. Unresolved factual stories are withheld, and a fixed service notice remains the last resort. Composition defaults to 900 seconds between calls, with up to 120 seconds reserved for pruning; in-flight calls can exceed that deadline.

Production records its active stage in `state/production-run.json`. The independent weekday watchdog runs at 6:45 a.m. Eastern and writes `state/watchdog-status.json`:

```bash
python check_delivery.py --write-state
```

It distinguishes full or shortened approved delivery from service notices, missing delivery, and uncertain sends. Exit status 1 means investigate; it does not mean resend. It uses only Python's standard library and can inspect production even if application dependencies fail. Codex's recurring SSH check provides user alerts while the local computer and app are running. Neither monitor sends newsletter email.
