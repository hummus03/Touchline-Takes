"""Classifier agent: tag league, teams, topic, sentiment and emotion per story.

Pluggable: :class:`LexiconClassifier` works fully offline; :class:`LLMClassifier`
uses the configured hosted LLM and falls back to the lexicon on any failure.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from touchline_takes.agents.base import Agent
from touchline_takes.db import Database
from touchline_takes.state import NewsroomState, Story
from touchline_takes.tools.llm import LLMClient, LLMError, parse_json_object
from touchline_takes.tools.teams import TeamDirectory

TOPICS = ("match_report", "transfer", "injury", "manager", "discipline", "preview", "general")
SENTIMENTS = ("positive", "neutral", "negative")
EMOTIONS = ("joy", "anger", "sadness", "fear", "surprise", "neutral")
LEAGUE_KEYWORDS = {
    "Champions League": ["champions league"], "Europa League": ["europa league"],
    "International": ["world cup", "euro 20", "nations league", "international break"],
    "Premier League": ["premier league"], "La Liga": ["la liga"], "Serie A": ["serie a"],
    "Bundesliga": ["bundesliga"], "Ligue 1": ["ligue 1"],
    "Scottish Premiership": ["scottish premiership"],
}
TOPIC_KEYWORDS = {
    "match_report": [r"\d+-\d+", r"\bbeat\b", r"\bwin\b", r"\bwon\b", r"\bdraw\b", r"\bheld\b",
                     r"\bdefeat\b", r"\bthrash", r"\bscored\b", r"\bwinner\b", r"\bvictory\b",
                     r"\bgoalless\b", r"\bcome from behind\b"],
    "transfer": [r"\bsign(?:s|ed|ing)?\b", r"\btransfer\b", r"\bfee\b", r"\bbid\b", r"\bloan\b",
                 r"\bcontract\b", r"\bin talks\b", r"\bextension\b", r"\bdeal\b",
                 r"\bshortlist\b", r"\btargets?\b", r"\bstrengthen\b", r"\bgossip\b",
                 r"\bon (?:their|the) radar\b"],
    "injury": [r"\binjur", r"\bruled out\b", r"\bhamstring\b", r"\bknee\b", r"\bsidelined\b",
               r"\bfitness\b", r"\bankle\b", r"\bsurgery\b", r"\btreatment\b"],
    "manager": [r"\bsack(?:s|ed|ing)?\b", r"\bappointed\b", r"\bhead coach\b", r"\bdismissed\b",
                r"\bresign", r"\bboss\b", r"\b(?:manager(?:ial)?|coaching) (?:job|post|role)\b",
                r"\blinked with [\w\s]{0,30}\bjob\b", r"\bmanager ins and outs\b",
                r"\bmanag(?:er|ers|erial)\b"],
    "discipline": [r"\bvar\b", r"\bred card\b", r"\bpenalty\b", r"\breferee", r"\bban\b",
                   r"\bsuspen(?:sion|sions|ded)\b", r"\byellow cards?\b",
                   r"\bappeal\b", r"\bcontroversy\b"],
    "preview": [r"\bpreview\b", r"\bahead of\b", r"\bthis weekend\b", r"\bwill host\b",
                r"\bhost\b", r"\btravel to\b", r"\bupcoming\b"],
}
# A story only counts as a match report if its headline has a scoreline or a result
# verb: Guardian summaries run to a paragraph and mention earlier results in passing.
# Words like "win" or "defeat" on their own ("title win", "World Cup winner",
# "semi-final defeat") turned features and transfer stories into match reports.
SCORE_RE = re.compile(r"(?<![\d-])\d{1,2}\s?[-–]\s?\d{1,2}(?![\d-])")
TITLE_RESULT_RE = re.compile(
    r"\b(beat|beats|thrash(?:es|ed)?|stun(?:s|ned)?|held|hold|draw (?:with|at|against)|"
    r"drew|draws|goalless|come from behind|came from behind|fight back|fought back|"
    r"lose (?:to|at)|lost (?:to|at)|edge (?:past|out)|rout|hammer(?:s|ed)?|"
    r"see off|sees off|saw off|win (?:at|against|over|away)|wins (?:at|against|over|away))\b",
    re.I)
AWARD_RE = re.compile(r"\b(vote|voting|award|awards|of the year|nominee|nominated|ballon d'or)\b",
                      re.I)
# Legal and governance stories use "deal" and "in talks" too, but aren't transfers.
LEGAL_RE = re.compile(r"\b(lawyers?|court|fraud|charges?|police|tribunal|whistleblower|"
                      r"investigation|hearing|lawsuit)\b", re.I)
TOPIC_WEIGHTS = {"manager": 1.6, "transfer": 1.3, "injury": 1.5, "discipline": 1.4,
                 "preview": 1.6, "match_report": 1.0}
POSITIVE = set("""win wins won beat victory thrash thrashed brilliant superb stunning delight
delighted celebrate boost lifting lifted extend extension clear top dominant welcome welcomed
agree agreed help comeback winner response""".split())
NEGATIVE = set("""defeat lost lose losing sacked furious disgrace blow injury injured ruled
controversy denied shock stunned frustrated frustrating crisis worry miss misses dropped
without held poor struggling row fury""".split())
EMOTION_WORDS = {
    "joy": {"celebrate", "delight", "delighted", "brilliant", "superb", "thrashed", "thrash",
            "dominant", "welcome", "welcomed", "victory"},
    "anger": {"furious", "fury", "disgrace", "row", "controversy", "slammed", "outrage",
              "blasted"},
    "sadness": {"sacked", "blow", "heartbreak", "relegated", "devastated", "misery", "injury",
                "ruled"},
    "fear": {"worry", "concern", "crisis", "threat", "pressure", "danger"},
    "surprise": {"shock", "stunned", "stunning", "upset", "unexpected", "surprise"},
}
NEGATORS = {"not", "no", "never", "without"}


@dataclass
class Classification:
    """Tags for one story."""

    league: str
    teams: list[str]
    topic: str
    sentiment: str
    sentiment_score: float
    emotion: str

    def apply(self, story: Story) -> Story:
        """Copy the tags onto ``story``."""
        story.league, story.teams, story.topic = self.league, self.teams, self.topic
        story.sentiment, story.sentiment_score = self.sentiment, self.sentiment_score
        story.emotion = self.emotion
        return story


class BaseClassifier(ABC):
    """Interface for classifier back-ends."""

    name = "base"

    @abstractmethod
    def classify(self, story: Story) -> Classification:
        """Tag a story."""


class LexiconClassifier(BaseClassifier):
    """Offline classifier built on keyword lexicons and the team directory."""

    name = "lexicon"

    def __init__(self, teams: TeamDirectory) -> None:
        self.teams = teams

    def league(self, text: str, teams: list[str]) -> str:
        """Explicit competition keywords win; otherwise the league of the teams mentioned."""
        lower = text.lower()
        for league, words in LEAGUE_KEYWORDS.items():
            if any(w in lower for w in words):
                return league
        leagues = [self.teams.league_of(t) for t in teams if self.teams.league_of(t)]
        if leagues:
            # Most-mentioned league; ties go to the first team mentioned.
            return max(dict.fromkeys(leagues), key=leagues.count)
        return "General"

    @staticmethod
    def topic(title: str, summary: str) -> str:
        """Weighted keyword scoring; the title counts double."""
        scores = {}
        for topic, patterns in TOPIC_KEYWORDS.items():
            score = 0.0
            for pattern in patterns:
                score += 2 * len(re.findall(pattern, title, re.I))
                score += len(re.findall(pattern, summary, re.I))
            scores[topic] = score * TOPIC_WEIGHTS.get(topic, 1.0)
        if not (SCORE_RE.search(title) or TITLE_RESULT_RE.search(title)):
            scores["match_report"] = 0.0
        if AWARD_RE.search(title) or LEGAL_RE.search(title):
            return "general"  # awards shortlists and legal "deals" aren't transfer stories
        for topic in ("transfer", "injury", "manager", "discipline", "preview"):
            # A passing mention in the summary ("...after Joao Pedro's injury...") doesn't
            # make a story about that topic: the headline has to say so too.
            if not any(re.search(p, title, re.I) for p in TOPIC_KEYWORDS[topic]):
                scores[topic] = 0.0
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "general"

    @staticmethod
    def sentiment(text: str) -> tuple[str, float, str]:
        """Lexicon sentiment with simple negation, plus a dominant emotion."""
        words = re.findall(r"[a-z']+", text.lower())
        pos = neg = 0
        emotions = dict.fromkeys(EMOTION_WORDS, 0)
        for i, word in enumerate(words):
            negated = i > 0 and words[i - 1] in NEGATORS
            if word in POSITIVE:
                neg, pos = (neg + 1, pos) if negated else (neg, pos + 1)
            elif word in NEGATIVE:
                pos, neg = (pos + 1, neg) if negated else (pos, neg + 1)
            for emotion, lexicon in EMOTION_WORDS.items():
                if word in lexicon:
                    emotions[emotion] += 1
        score = (pos - neg) / math.sqrt(pos + neg + 1)
        label = "positive" if score > 0.3 else "negative" if score < -0.3 else "neutral"
        top = max(emotions, key=emotions.get)
        return label, round(score, 3), top if emotions[top] else "neutral"

    def classify(self, story: Story) -> Classification:
        teams = self.teams.find_teams(story.text)
        label, score, emotion = self.sentiment(story.text)
        return Classification(self.league(story.text, teams), teams,
                              self.topic(story.title, story.summary), label, score, emotion)


class LLMClassifier(BaseClassifier):
    """Hosted classification via the configured LLM, validated, with lexicon fallback."""

    name = "llm"
    SYSTEM = ("You are the Touchline Takes newsroom classifier. Reply with one JSON object "
              "only, no prose.")

    def __init__(self, llm: LLMClient, fallback: LexiconClassifier) -> None:
        self.llm = llm
        self.fallback = fallback
        self.failures = 0

    def prompt(self, story: Story) -> str:
        """Classification prompt."""
        return (
            "Classify this football story.\n"
            f"Allowed topics: {', '.join(TOPICS)}.\n"
            f"Allowed sentiments: {', '.join(SENTIMENTS)}.\n"
            f"Allowed emotions: {', '.join(EMOTIONS)}.\n"
            'Return {"league": str, "teams": [str], "topic": str, "sentiment": str, '
            '"emotion": str}.\n\n'
            f"TITLE: {story.title}\nSUMMARY: {story.summary}\n")

    def classify(self, story: Story) -> Classification:
        base = self.fallback.classify(story)
        try:
            data = parse_json_object(self.llm.complete(self.prompt(story), self.SYSTEM,
                                                       max_tokens=300).text)
        except LLMError:
            self.failures += 1
            return base
        topic = data.get("topic") if data.get("topic") in TOPICS else base.topic
        sentiment = data.get("sentiment") if data.get("sentiment") in SENTIMENTS \
            else base.sentiment
        emotion = data.get("emotion") if data.get("emotion") in EMOTIONS else base.emotion
        teams = [self.fallback.teams.canonical(t) for t in data.get("teams", [])
                 if isinstance(t, str)] or base.teams
        league = data.get("league") if isinstance(data.get("league"), str) and data.get(
            "league") else base.league
        return Classification(league, teams, topic, sentiment, base.sentiment_score, emotion)


class ClassifierAgent(Agent):
    """Tags every unclassified story and persists the tags."""

    name = "classifier"

    def __init__(self, db: Database, classifier: BaseClassifier) -> None:
        super().__init__()
        self.db = db
        self.classifier = classifier

    def run(self, state: NewsroomState) -> NewsroomState:
        pending = {s.id: s for s in self.db.unclassified_stories()}
        for story in state.new_stories:
            pending.setdefault(story.id, story)
        for story in pending.values():
            self.classifier.classify(story).apply(story)
            self.db.update_classification(story)
            state.stories.append(story)
            self.log(state, "classified",
                     f"{story.league} | {', '.join(story.teams) or '-'} | {story.topic} | "
                     f"{story.sentiment}/{story.emotion} via {self.classifier.name}", story.id)
        state.metrics["classifier"] = {"classified": len(pending),
                                       "backend": self.classifier.name}
        return state
