"""Conservative, deterministic pruning; every result still requires full review."""
from .models import Edition, Omission, ReviewIssue
from .composition import issue_value


def shorten_failed_draft(raw_draft, reviews, developments, rejected):
    if not raw_draft or not reviews:
        return None
    last = reviews[-1]
    findings = [ReviewIssue.model_validate(f) for f in last.get('findings', [])]
    # Never infer an approval or a safe location from an unstructured rejection.
    if not findings or last.get('stage') not in ('edition_review', 'repair_check', 'structural_review'):
        return None
    if last.get('stage') == 'edition_review' and len(findings) < len(last.get('issues', [])):
        return None
    draft = Edition.model_validate(raw_draft)
    withheld = {o.development_id for o in draft.omissions if o.reason in (
        'Combined story removed because a related development failed review.',
        'Withheld after unresolved editorial review findings.')}
    drop_stories, drop_paragraphs = set(), {}
    for issue in findings:
        issue_value(draft, issue)
        if issue.field == 'edition':
            if (issue.category == 'coverage' and issue.development_ids
                    and set(issue.development_ids) <= withheld):
                continue  # Final review explicitly evaluates justified fallback omissions.
            return None
        if issue.field in ('subject', 'intro', 'closing', 'image_caption', 'image_description'):
            continue  # Replaced below with fixed, factual-claim-free presentation.
        if issue.field == 'paragraph' and issue.category == 'optional_presentation':
            drop_paragraphs.setdefault(issue.story_index, set()).add(issue.paragraph_index)
        else:
            # Factual and anchor errors are not fixed by silently deleting a caveat.
            drop_stories.add(issue.story_index)
    retained = []
    for index, story in enumerate(draft.stories):
        if index in drop_stories or set(story.development_ids) & set(rejected):
            continue
        story.paragraphs = [p for i, p in enumerate(story.paragraphs)
                            if i not in drop_paragraphs.get(index, set())]
        if not story.paragraphs:
            continue
        story.image_caption = 'Conceptual illustration.'
        story.image_description = ('Symbolic editorial illustration of: ' + story.headline +
                                   '. No text, logos, identifiable people or actual event reconstruction.')
        retained.append(story)
    if not retained:
        return None
    draft.stories = retained
    draft.subject = 'Future Appetite: Today’s briefing'
    draft.intro = draft.closing = ''
    draft.charts = []
    used = {sid for story in retained for sid in story.development_ids}
    old_reasons = {o.development_id: o.reason for o in draft.omissions}
    draft.omissions = [Omission(development_id=d['source_id'], reason=old_reasons.get(
        d['source_id'], 'Withheld after unresolved editorial review findings.'))
        for d in developments if d['source_id'] not in used]
    return draft
