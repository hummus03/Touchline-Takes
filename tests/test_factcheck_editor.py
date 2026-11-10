"""Tests for the Fact-check and Editor agents and the bounded revision loop."""
# pylint: disable=redefined-outer-name

from touchline_takes.agents.editor import EditorAgent, StyleGuide
from touchline_takes.agents.factcheck import FactCheckAgent, check_draft, unsupported_claims
from touchline_takes.state import Draft, Evidence, NewsroomState

EVIDENCE = [
    Evidence("S1", "story", "Test Wire: Arsenal beat Chelsea 2-1. Leo Hartmann scored the "
             "winner in the 78th minute.", "Test Wire", "https://example.com/1"),
    Evidence("ST1", "stats", "Arsenal last 5 league matches in results: 3 wins, 1 draw, "
             "1 defeat, 10 points.", "results"),
]
GOOD = ("Arsenal beat Chelsea 2-1, as reported by Test Wire [S1]. Leo Hartmann scored in the "
        "78th minute [S1]. In our results, Arsenal have 3 wins, 1 draw and 1 defeat from their "
        "last 5 league games: 10 points [ST1].\n\n"
        "That is the sort of afternoon that changes the mood around a dressing room. There is "
        "no hiding from a scoreline, and this one will be picked apart all week, from the "
        "back four to the bench. It was the kind of game that tells you more about character "
        "than about tactics, and character is what carries a side through a long winter. "
        "The Touchline Take: enjoy it, but the real test is backing it up next week.")


def make_draft(body=GOOD, revision=0, title="Arsenal v Chelsea: the Touchline Take"):
    """A draft with fixed evidence."""
    return Draft(id="d1", article_type="match_report", title=title, body=body,
                 evidence=list(EVIDENCE), story_ids=["s1"], revision=revision)


def test_check_draft_classifies_sentences():
    """Supported claims, opinion and unsupported claims are told apart."""
    body = GOOD + " Chelsea will sign Kai Brandt [S1]. Juventus are watching."
    checks = {c.sentence: c for c in check_draft(make_draft(body))}
    assert checks["Arsenal beat Chelsea 2-1, as reported by Test Wire [S1]."].supported
    assert not checks["That is the sort of afternoon that changes the mood around a dressing "
                      "room."].is_claim
    bad = checks["Chelsea will sign Kai Brandt [S1]."]
    assert not bad.supported and bad.missing == ["kai", "brandt"]
    assert checks["Juventus are watching."].reason == "no source cited"


def test_factcheck_removes_minor_unsupported_claims(db):
    """A few unsupported claims are stripped and the draft proceeds."""
    draft = make_draft(GOOD.replace("[ST1].", "[ST1]. Insiders expect 200 million [S1]."))
    state = NewsroomState(drafts=[draft])
    FactCheckAgent(db).run(state)
    assert draft.status == "checked"
    assert "200 million" not in draft.body
    assert unsupported_claims(draft) == []


def test_factcheck_sends_back_then_rejects(db):
    """Too many unsupported claims bounce the draft; after max revisions it is rejected."""
    body = "Juventus will bid 90 million [S1]. Bayern are interested [S9]. " + GOOD
    draft = make_draft(body)
    state = NewsroomState(drafts=[draft])
    FactCheckAgent(db, max_revisions=2).run(state)
    assert draft.status == "needs_revision" and draft.feedback
    assert db.recent_rejections()[0]["agent"] == "factcheck"
    late = make_draft(body, revision=2)
    FactCheckAgent(db, max_revisions=2).run(NewsroomState(drafts=[late]))
    assert late.status == "rejected"


def test_editor_approves_good_draft(db):
    """A grounded, opinionated, right-sized draft is approved."""
    draft = make_draft()
    draft.status = "checked"
    EditorAgent(db, StyleGuide(min_words=60)).run(NewsroomState(drafts=[draft]))
    assert draft.status == "approved", draft.rejection_history


def test_editor_flags_style_problems(db):
    """Length, tone, banned phrases, copying and missing verdicts are all caught."""
    editor = EditorAgent(db, StyleGuide(min_words=60))
    copied = make_draft(GOOD.replace("Leo Hartmann scored in the 78th minute [S1].",
                                     "Leo Hartmann scored the winner in the 78th minute "
                                     "said Test Wire [S1].") + " In conclusion, AMAZING!!!")
    problems = " | ".join(editor.review(copied))
    for expected in ("banned phrase", "exclamation", "shouting", "originality"):
        assert expected in problems
    short = make_draft("Arsenal beat Chelsea 2-1 [S1].", title="Short")
    problems = " | ".join(editor.review(short))
    for expected in ("too short", "title length", "no opinion", "verdict", "too thin"):
        assert expected in problems


def test_editor_bounded_retries_logged(db):
    """The editor sends back until max revisions, then rejects; reasons are logged."""
    editor = EditorAgent(db, StyleGuide(min_words=500), max_revisions=2)
    draft = make_draft()
    for revision in range(3):
        draft.status, draft.revision = "checked", revision
        editor.run(NewsroomState(drafts=[draft]))
    assert draft.status == "rejected"
    assert len(draft.rejection_history) == 3
    reasons = db.recent_rejections()
    assert len(reasons) == 3 and "too short" in reasons[0]["reasons"][0]
