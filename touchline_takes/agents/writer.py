"""Writer agent: drafts original Touchline Takes from stored stories, stats and predictions.

Facts-first generation: the Writer turns each evidence record (source story,
results-data record, fixture, model prediction) into short grounded fact
sentences that carry a citation marker such as ``[S1]``. Opinion lines ("takes")
carry no facts. With an LLM configured, the model restyles those facts in the
house voice; offline, a deterministic template composer does the job. Source
articles are never republished: only headlines and short fragments are quoted,
always with attribution, and every article lists its sources with links.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from touchline_takes.agents.base import Agent
from touchline_takes.db import Database
from touchline_takes.state import Draft, Evidence, NewsroomState, Story
from touchline_takes.tools.llm import LLMClient, LLMError
from touchline_takes.tools.relations import extract_results, headline_winner
from touchline_takes.tools.stats import ResultsStore
from touchline_takes.tools.teams import TeamDirectory
from touchline_takes.tools.text import split_paragraphs

ROLE_WORDS = {"midfielder", "striker", "forward", "winger", "manager", "defender", "goalkeeper",
              "substitute", "captain", "head", "coach", "boss", "centre-back", "full-back",
              "the", "a", "an", "local"}
PLACE_WORDS = {"Park", "Stadium", "Arena", "Road", "Lane", "Ground"}
# Countries and national teams with multi-word names: not people "in the frame".
NATIONS = {"Northern Ireland", "Republic Of Ireland", "United States", "South Korea",
           "North Korea", "Saudi Arabia", "New Zealand", "Costa Rica", "Ivory Coast",
           "South Africa", "Czech Republic", "Faroe Islands", "Cape Verde", "Burkina Faso",
           "Sierra Leone", "El Salvador", "Trinidad", "Dominican Republic", "San Marino",
           "United Arab Emirates", "Hong Kong", "Puerto Rico", "Equatorial Guinea",
           "Papua New Guinea", "Bosnia", "North Macedonia", "Great Britain", "Team GB"}
# People introduced like this are the article's author or broadcaster, not part of the story.
JOURNALIST_WORDS = {"correspondent", "reporter", "editor", "writer", "journalist", "columnist",
                    "presenter", "commentator"}
BYLINE_RE = re.compile(r"(?:(?:^|[.!?]\s+)By|\bwrites|\baccording to)\s*$")
DANGLING = {"the", "a", "an", "of", "on", "to", "in", "and", "with", "for", "at", "by", "from",
            "their", "his", "her", "its", "into", "over", "after", "before", "than"}
LEDE_PHRASES = {"transfer": "a transfer story", "injury": "an injury update",
                "manager": "a dugout story", "discipline": "a refereeing story",
                "match_report": "a match story", "preview": "a build-up story",
                "general": "a story"}
TITLE_LABELS = {"transfer": "the transfer talk", "injury": "the injury news",
                "manager": "the dugout", "discipline": "the refereeing row",
                "match_report": "the result", "preview": "the build-up", "general": "the latest"}
NUMBER_WORDS = r"(?:\d+\w*|one|two|three|four|five|six|seven|eight|nine|ten|twice)"

# Opinion lines: no proper nouns, no numbers (the fact-checker treats them as commentary).
TAKES = {
    "match_report": [
        "Results like this shape a season far more than any press conference ever will.",
        "That is the sort of afternoon that changes the mood around a dressing room.",
        "There is no hiding from a scoreline, and this one will be picked apart all week.",
        "It was the kind of game that tells you more about character than about tactics.",
    ],
    "transfer": [
        "Talk is cheap until the paperwork is signed, so treat every rumour with care.",
        "If this one goes through, it says plenty about where the club thinks it is heading.",
        "The smart money is on patience: rushed deals rarely age well.",
    ],
    "injury": [
        "This is where squad depth gets tested, and that is where seasons are quietly decided.",
        "This is exactly the kind of blow that exposes a thin bench.",
        "Nobody wins anything in the treatment room, but plenty of seasons are lost there.",
    ],
    "manager": [
        "The sack is the easiest lever to pull and the hardest one to get right.",
        "The next appointment matters far more than the timing of this one.",
        "Every board loves a fresh start; fans just want a plan that survives a bad month.",
    ],
    "discipline": [
        "Whatever the technology, supporters deserve decisions that are consistent and explained.",
        "One more weekend, one more refereeing row, and still no clarity for supporters.",
        "Every row like this sells, but clarity would serve the game far better.",
    ],
    "preview": [
        "Form matters, but big games have a habit of ignoring the spreadsheet.",
        "This is the kind of fixture where one moment of quality settles everything.",
        "Expect nerves early and a lot more freedom once the first goal goes in.",
    ],
    "general": [
        "It is a story worth keeping an eye on as the season unfolds.",
        "There is more to this than the headline suggests.",
    ],
}
TOPIC_VERDICTS = {
    "transfer": "The Touchline Take: judge the business when the window shuts, not before.",
    "injury": "The Touchline Take: how the squad copes will define the next month.",
    "manager": "The Touchline Take: get the next appointment right and this is forgotten.",
    "discipline": "The Touchline Take: consistency, please. That is all anyone asks.",
    "preview": "The Touchline Take: one to circle in the diary.",
    "general": "The Touchline Take: one to keep an eye on.",
}
DRAW_VERDICT = "The Touchline Take: a point apiece, and nobody fully satisfied."
VERDICTS = {
    "positive": "The Touchline Take: enjoy it, but the real test is backing it up next week.",
    "negative": "The Touchline Take: this needs a response, and quickly.",
    "neutral": "The Touchline Take: file this one under unfinished business.",
}
SYSTEM_PROMPT = (
    "You are the lead writer at Touchline Takes, a football site with a sharp, opinionated, "
    "fan-friendly voice, like a pundit on the touchline. You write original copy and never "
    "copy source articles. Hard rule: every factual sentence must come from the grounded "
    "facts you are given and must keep its citation marker, e.g. [S1]. You may rephrase "
    "facts and add opinion, but never add a new name, number, date or event.")


class Research(Protocol):
    """What the Writer needs from the RAG research tools."""

    def related(self, query: str, k: int = 3, exclude_ids: tuple[str, ...] = ()
                ) -> list[dict[str, Any]]:
        """Stories related to ``query`` (dicts with story_id, title, source, url, text)."""


@dataclass
class Assignment:
    """One article the Writer has decided to produce."""

    article_type: str
    story: Story | None = None
    fixture: dict[str, Any] | None = None

    @property
    def key(self) -> str:
        """Stable id for de-duplicating assignments across runs."""
        base = self.story.id if self.story else self.fixture["id"]
        return hashlib.sha1(f"{self.article_type}:{base}".encode()).hexdigest()[:10]


@dataclass
class Composition:
    """Grounded facts and opinion lines for a draft."""

    title: str
    facts: list[str]
    takes: list[str]
    evidence: list[Evidence] = field(default_factory=list)

    def body(self) -> str:
        """Lay facts and takes out as paragraphs."""
        paragraphs = [" ".join(self.facts[:3]), " ".join(self.facts[3:6]),
                      " ".join(self.facts[6:]), " ".join(self.takes)]
        return "\n\n".join(p for p in paragraphs if p)


def plural(count: int | str, noun: str) -> str:
    """'1 win', '2 wins'."""
    return f"{count} {noun}" if int(count) == 1 else f"{count} {noun}s"


def _pick(options: list[str], seed: str, count: int = 1) -> list[str]:
    """Deterministically pick ``count`` distinct options."""
    start = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(options)
    return [options[(start + i) % len(options)] for i in range(min(count, len(options)))]


class WriterAgent(Agent):
    """Plans assignments, writes first drafts and revises drafts sent back."""

    name = "writer"

    def __init__(self, db: Database, teams: TeamDirectory, results: ResultsStore | None = None,
                 research: Research | None = None, llm: LLMClient | None = None,
                 max_articles: int = 6, max_previews: int = 2,
                 results_label: str = "results data") -> None:
        super().__init__()
        self.db = db
        self.teams = teams
        self.results = results
        self.research = research
        self.llm = llm
        self.max_articles = max_articles
        self.max_previews = max_previews
        self.results_label = results.label if results is not None else results_label

    # ------------------------------------------------------------------ planning
    def plan(self, state: NewsroomState) -> list[Assignment]:
        """Choose what to write this run."""
        candidates: dict[str, Story] = {s.id: s for s in state.stories}
        for story in self.db.unused_stories():
            candidates.setdefault(story.id, story)
        priority = ["match_report", "manager", "transfer", "injury", "discipline", "preview"]
        stories = sorted((s for s in candidates.values() if s.teams),
                         key=lambda s: s.published, reverse=True)  # newest first...
        stories.sort(key=lambda s: priority.index(s.topic) if s.topic in priority
                     else len(priority))  # ...within topic priority (stable sort)
        assignments: list[Assignment] = []
        previews = [Assignment("preview", fixture=f) for f in state.fixtures
                    if f.get("probs")][: self.max_previews]
        story_slots = max(0, self.max_articles - len(previews))
        covered: dict[tuple[str, str], str] = {}  # (lead team, topic) -> story id
        for story in stories:
            if len(assignments) >= story_slots:
                break
            key = (story.teams[0], story.topic or "general")
            if key in covered:
                # Same club, same kind of story: one article, the rest as related coverage.
                self.db.mark_used([story.id])
                self.log(state, "merged", f"covered by the {key[0]} {key[1]} article "
                         f"({covered[key]}): {story.title}", story.id)
                continue
            covered[key] = story.id
            kind = "match_report" if story.topic == "match_report" else "explainer"
            assignments.append(Assignment(kind, story=story))
        assignments += previews
        return [a for a in assignments if self.db.get_draft(a.key) is None]

    # ------------------------------------------------------------------ evidence
    def _story_evidence(self, eid: str, story: Story | dict[str, Any]) -> Evidence:
        if isinstance(story, Story):
            return Evidence(eid, "story", f"{story.source}: {story.title}. {story.summary}",
                            story.source, story.url)
        return Evidence(eid, "story", f"{story['source']}: {story['text']}", story["source"],
                        story["url"])

    def _about(self, title: str, teams: list[str]) -> bool:
        """True if a headline names one of ``teams`` (so related coverage stays on topic)."""
        return not teams or bool(set(self.teams.find_teams(title)) & set(teams))

    def _related(self, query: str, exclude: tuple[str, ...], teams: list[str], k: int
                 ) -> list[dict[str, Any]]:
        """Related coverage via RAG, falling back to a team match over stored stories.

        Only stories whose headline names one of the clubs count: a passing mention in
        the summary ("...before facing Sunderland") isn't enough to make them relevant.
        """
        if self.research is not None:
            hits = self.research.related(query, k=k * 4, exclude_ids=exclude)
            return [h for h in hits if self._about(h["title"], teams)][:k]
        out = []
        for story in self.db.recent_stories(100):
            if story.id in exclude or not self._about(story.title, teams) or not teams:
                continue
            out.append({"story_id": story.id, "title": story.title, "source": story.source,
                        "url": story.url, "text": f"{story.title}. {story.summary}"})
        return out[:k]

    def _stats_evidence(self, teams: list[str], start: int) -> list[Evidence]:
        out = []
        if self.results is None:
            return out
        for team in teams:
            text = self.results.form_text(team, self.teams.data_name(team))
            if text:
                out.append(Evidence(f"ST{start + len(out)}", "stats", text,
                                    f"Football-Data.co.uk-format {self.results_label}"))
        return out

    # ------------------------------------------------------------------ facts
    def _names(self, story: Story) -> list[str]:
        """People/places named in the summary (not teams, leagues, the source or its writer)."""
        skip = {t.lower() for t in story.teams} | {
            a.lower() for t in story.teams for a in self.teams.aliases(t)}
        names = []
        # Allows "Saint-Germain", "McTominay", "O'Neill".
        word = r"[A-Z][a-zà-ÿ'’]+(?:[A-Z][a-zà-ÿ'’]+)?(?:-[A-Z]?[a-zà-ÿ'’]+)*"
        for match in re.finditer(rf"(?:{word}\s){{1,3}}{word}", story.summary):
            preceding = story.summary[:match.start()]
            if BYLINE_RE.search(preceding) or any(
                    w.strip(",.:'’") in JOURNALIST_WORDS for w in preceding.lower().split()[-4:]):
                continue  # the article's author, not someone in the story
            words = match.group(0).split()
            if words[0] == "By":
                continue  # "By Sami Mokbel": a byline
            while words and words[0].lower() in ROLE_WORDS | JOURNALIST_WORDS | {"senior"}:
                words = words[1:]
            for i, w in enumerate(words):  # "Pep Guardiola's Manchester City" -> "Pep Guardiola"
                if w.endswith(("'s", "’s")):
                    words = words[:i] + [w[:-2]]
                    break
            name = " ".join(words)
            for nation in NATIONS:  # "Northern Ireland" is a country, not a person
                if f" {nation.lower()} " in f" {name.lower()} ":
                    words = [w for w in name.split() if w not in nation.split()]
                    name = " ".join(words)
            if len(words) >= 2 and name.lower() not in skip and words[-1] not in PLACE_WORDS \
                    and not any(
                    lg in name for lg in ("League", "Liga", "Serie", "Premiership",
                                          "Bundesliga", "Cup")) and name not in names:
                names.append(name)
        return names[:2]

    def _result_fact(self, story: Story, teams: list[str], score: re.Match) -> str:
        """Phrase the result, naming the winner only when the source makes it unambiguous."""
        pair = frozenset(teams[:2])
        for result in extract_results(story.text, self.teams):
            if result.teams == pair:
                if result.draw or result.winner:
                    return result.describe()
                break
        return f"The game between {teams[0]} and {teams[1]} ended {score.group(0)}"

    @staticmethod
    def _detail(story: Story) -> str | None:
        """A complete short phrase with a number in it, quoted with attribution.

        Only whole phrases (4-14 words, not ending on a dangling word) are quoted, so
        a quote never stops mid-sentence.
        """
        for frag in re.split(r"[.,;:–—]|\band\b|\bas\b|\bbut\b", story.summary):
            words = frag.split()
            if not 4 <= len(words) <= 14 or words[-1].lower() in DANGLING:
                continue
            if re.search(rf"\b{NUMBER_WORDS}\b", frag) and not re.search(r"\b\d+-\d+\b", frag):
                return " ".join(words)
        return None

    def _story_facts(self, story: Story, detail: int) -> Composition:
        evidence = [self._story_evidence("S1", story)]
        facts = []
        teams = story.teams[:2]
        score = re.search(r"\b(\d+)-(\d+)\b", story.text)
        winner = headline_winner(story.title, self.teams, story.teams) \
            if len(teams) >= 2 else None
        if story.topic == "match_report" and len(teams) >= 2 and score:
            facts.append(self._result_fact(story, teams, score) +
                         f", as reported by {story.source} [S1].")
        elif story.topic == "match_report" and winner:
            facts.append(f"{winner[0]} beat {winner[1]}, as reported by {story.source} [S1].")
        else:
            phrase = LEDE_PHRASES.get(story.topic or "general", "a story")
            facts.append(f"{story.source} has {phrase} involving {' and '.join(teams)} [S1].")
        facts.append(f"The headline said it plainly: “{story.title}” [S1].")
        names = self._names(story)
        if names:
            facts.append(f"The names in the frame: {' and '.join(names)} [S1].")
        frag = self._detail(story)
        if frag:
            facts.append(f"One detail from the report stands out: “{frag}” [S1].")
        related = self._related(story.text, (story.id,), teams, k=1 + detail)
        for i, rel in enumerate(related, start=2):
            evidence.append(self._story_evidence(f"S{i}", rel))
            facts.append(f"For context, {rel['source']} also ran: “{rel['title']}” [S{i}].")
        stats = self._stats_evidence(teams, 1)
        evidence += stats
        facts += [self._form_fact(e) for e in stats]
        kind = story.topic if story.topic in TAKES else "general"
        takes = _pick(TAKES[kind], story.id + str(detail), 2)
        takes.append(self._verdict(story, teams))
        if story.topic == "match_report" and len(teams) >= 2:
            title = f"{teams[0]} v {teams[1]}: the Touchline Take"
        else:
            label = TITLE_LABELS.get(story.topic or "general", "the latest")
            title = f"{teams[0]}: the Touchline Take on {label}"
        return Composition(title, facts, takes, evidence)

    def _verdict(self, story: Story, teams: list[str]) -> str:
        """Closing line that fits what actually happened (cited when it names a winner)."""
        if story.topic != "match_report":
            return TOPIC_VERDICTS.get(story.topic or "general", TOPIC_VERDICTS["general"])
        pair = frozenset(teams[:2])
        for result in extract_results(story.text, self.teams):
            if result.teams == pair and result.draw:
                return DRAW_VERDICT
            if result.teams == pair and result.winner:
                return (f"The Touchline Take: {result.winner} earned this one [S1], and now "
                        "they have to back it up.")
        winner = headline_winner(story.title, self.teams, story.teams)
        if winner and frozenset(winner) == pair:
            return (f"The Touchline Take: {winner[0]} earned this one [S1], and now they have "
                    "to back it up.")
        return VERDICTS["neutral"]

    def _form_fact(self, ev: Evidence) -> str:
        match = re.match(r"(.+?) last (\d+) league matches in .+?: (\d+) wins?, (\d+) draws?, "
                         r"(\d+) defeats?, (\d+) points?, (\d+) goals? scored, (\d+) conceded",
                         ev.text)
        team, played, wins, draws, losses, points, gf, ga = match.groups()
        return (f"In our {self.results_label}, {team} have {plural(wins, 'win')}, "
                f"{plural(draws, 'draw')} and {plural(losses, 'defeat')} from their last "
                f"{played} league games: {points} points, {gf} scored and {ga} conceded "
                f"[{ev.id}].")

    def _preview_facts(self, fixture: dict[str, Any], detail: int) -> Composition:
        home, away = self.teams.canonical(fixture["home"]), self.teams.canonical(fixture["away"])
        league = fixture.get("league") or self.teams.league_of(home) or "league"
        probs = fixture["probs"]
        pct = {k: round(100 * v) for k, v in probs.items()}
        evidence = [
            Evidence("F1", "fixture", f"Fixture: {home} v {away}, {league}, {fixture['date']}.",
                     fixture.get("source", "fixtures")),
            Evidence("M1", "model",
                     f"Touchline Takes Analyst model (logistic regression on "
                     f"{self.results_label}): {home} win {pct['H']}%, draw {pct['D']}%, "
                     f"{away} win {pct['A']}%.", "Touchline Takes Analyst model"),
        ]
        facts = [f"{home} host {away} in the {league} on {fixture['date']} [F1].",
                 f"The Touchline Takes Analyst model gives {home} a {pct['H']}% chance of "
                 f"winning, the draw {pct['D']}% and {away} {pct['A']}% [M1]."]
        stats = self._stats_evidence([home, away], 1)
        evidence += stats
        facts += [self._form_fact(e) for e in stats]
        if self.results is not None:
            meeting = self.results.last_meeting(self.teams.data_name(home),
                                                self.teams.data_name(away))
            if meeting:
                mh, ma = self.teams.canonical(meeting["home"]), self.teams.canonical(
                    meeting["away"])
                eid = f"ST{len(stats) + 1}"
                evidence.append(Evidence(
                    eid, "stats", f"Last meeting in {self.results_label}: {meeting['date']}, "
                    f"{mh} {meeting['home_goals']}-{meeting['away_goals']} {ma}.",
                    f"Football-Data.co.uk-format {self.results_label}"))
                facts.append(f"The last meeting in our {self.results_label}, on "
                             f"{meeting['date']}, finished {mh} {meeting['home_goals']}-"
                             f"{meeting['away_goals']} {ma} [{eid}].")
        related = self._related(f"{home} {away}", (), [home, away], k=1 + detail)
        for i, rel in enumerate(related, start=1):
            evidence.append(self._story_evidence(f"S{i}", rel))
            facts.append(f"The latest from {rel['source']}: “{rel['title']}” [S{i}].")
        fav = max(("H", "A"), key=lambda k: probs[k])
        fav_team = home if fav == "H" else away
        takes = _pick(TAKES["preview"], fixture["id"] + str(detail), 2)
        if probs[fav] >= 0.45:
            takes.append(f"The Touchline Take: back {fav_team} [M1], but do not be shocked "
                         "if this gets messy.")
        else:
            takes.append("The Touchline Take: too close to call, and the draw is very much "
                         "in play.")
        return Composition(f"Preview: {home} v {away}, who has the edge?", facts, takes,
                           evidence)

    def compose(self, assignment: Assignment, detail: int = 0) -> Composition:
        """Grounded facts + takes for an assignment (``detail`` adds more context)."""
        if assignment.article_type == "preview":
            return self._preview_facts(assignment.fixture, detail)
        return self._story_facts(assignment.story, detail)

    # ------------------------------------------------------------------ LLM path
    def _prompt(self, comp: Composition, draft: Draft | None = None) -> str:
        lines = [f"WORKING TITLE: {comp.title}", "", "EVIDENCE (cite by id):"]
        lines += [f"[{e.id}] {e.text}" for e in comp.evidence]
        lines += ["", "GROUNDED FACTS (keep each citation marker; rephrase freely, add no new "
                  "facts):"]
        lines += [f"- FACT: {f}" for f in comp.facts]
        lines += ["", "SUGGESTED TAKES (opinion only, no names or numbers):"]
        lines += [f"- TAKE: {t}" for t in comp.takes]
        lines += ["", "Write 150-350 words in 3-5 short paragraphs. End with a one-line "
                  "verdict starting 'The Touchline Take:'.",
                  "Reply as:\nTITLE: <headline>\n\n<body>"]
        if draft is not None:
            lines += ["", "REVISION REQUEST: fix these problems:"]
            lines += [f"- {f}" for f in draft.feedback]
            lines += ["", "PREVIOUS DRAFT:", draft.body]
        return "\n".join(lines)

    @staticmethod
    def _parse(text: str, fallback_title: str) -> tuple[str, str]:
        match = re.match(r"\s*TITLE:\s*(.+?)\s*\n(.*)", text, re.S)
        if match:
            return match.group(1).strip().strip('"'), "\n\n".join(
                split_paragraphs(match.group(2)))
        return fallback_title, "\n\n".join(split_paragraphs(text))

    def _render(self, comp: Composition, draft: Draft, state: NewsroomState,
                previous: Draft | None = None) -> None:
        """Fill ``draft`` title/body via the LLM (if any) or the template composer."""
        if self.llm is not None:
            try:
                resp = self.llm.complete(self._prompt(comp, previous), SYSTEM_PROMPT)
                draft.title, draft.body = self._parse(resp.text, comp.title)
                draft.mode = "llm"
                draft.add_metrics(llm_calls=0 if resp.cached else 1, cost_usd=resp.cost_usd,
                                  tokens_in=resp.tokens_in, tokens_out=resp.tokens_out)
                return
            except LLMError as exc:
                self.log(state, "llm_fallback", str(exc), draft.id)
        draft.title, draft.body, draft.mode = comp.title, comp.body(), "template"

    # ------------------------------------------------------------------ run
    def write(self, assignment: Assignment, state: NewsroomState) -> Draft:
        """First draft for an assignment."""
        start = time.perf_counter()
        comp = self.compose(assignment)
        story = assignment.story
        teams = story.teams if story else [self.teams.canonical(assignment.fixture["home"]),
                                           self.teams.canonical(assignment.fixture["away"])]
        draft = Draft(
            id=assignment.key, article_type=assignment.article_type, title=comp.title, body="",
            evidence=comp.evidence, story_ids=[story.id] if story else [],
            league=(story.league if story else assignment.fixture.get("league")), teams=teams,
            fixture_id=assignment.fixture["id"] if assignment.fixture else None)
        self._render(comp, draft, state)
        draft.add_metrics(latency_s=time.perf_counter() - start)
        return draft

    def revise(self, draft: Draft, state: NewsroomState) -> Draft:
        """Rewrite a draft that the Fact-checker or Editor sent back."""
        start = time.perf_counter()
        draft.revision += 1
        if draft.story_ids:
            story = self.db.get_story(draft.story_ids[0])
            assignment = Assignment(draft.article_type, story=story)
        else:
            fixture = next(f for f in state.fixtures if f["id"] == draft.fixture_id)
            assignment = Assignment("preview", fixture=fixture)
        detail = draft.revision if any("short" in f for f in draft.feedback) else 0
        comp = self.compose(assignment, detail=detail)
        if any("long" in f for f in draft.feedback):
            comp.facts = comp.facts[:6]
        previous = Draft.from_dict(draft.to_dict())
        draft.evidence = comp.evidence
        self._render(comp, draft, state, previous=previous)
        draft.status, draft.claims = "drafted", []
        draft.add_metrics(latency_s=time.perf_counter() - start)
        return draft

    def run(self, state: NewsroomState) -> NewsroomState:
        if not state.drafting_done:
            assignments = self.plan(state)
            for assignment in assignments:
                draft = self.write(assignment, state)
                state.drafts.append(draft)
                self.db.save_draft(draft, state.run_id)
                if assignment.story:
                    self.db.mark_used([assignment.story.id])
                self.log(state, "drafted", f"{draft.article_type} ({draft.mode}): "
                         f"{draft.title}", draft.id)
            state.drafting_done = True
            state.metrics["writer"] = {"assignments": len(assignments)}
        for draft in state.drafts_with_status("needs_revision"):
            self.revise(draft, state)
            self.db.save_draft(draft, state.run_id)
            self.log(state, "revised", f"revision {draft.revision}: "
                     f"{'; '.join(draft.feedback)[:200]}", draft.id)
        return state
