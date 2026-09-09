import re
from difflib import SequenceMatcher

from dateutil.parser import parse

from app.schemas.domain import ContractMapping, MarketSnapshot


def normalize_title(title: str) -> str:
    title = title.lower()
    # Normalize explicit dates without guessing ambiguous slash dates.
    pattern = r"(?:january|february|march|april|may|june|july|august|september|october|november|december) \d{1,2},? \d{4}"
    title = re.sub(pattern, lambda m: parse(m.group()).strftime("%Y-%m-%d"), title)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title).split())


def similarity(left: str, right: str) -> float:
    a, b = normalize_title(left), normalize_title(right)
    # Numeric mismatches (thresholds, dates) must never disappear in fuzzy matching.
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return 0.5 * len(ta & tb) / len(ta | tb) + 0.5 * SequenceMatcher(None, a, b).ratio()


class ContractMatcher:
    def __init__(self, threshold: float, mappings: list[ContractMapping]):
        self.threshold, self.mappings = threshold, mappings

    def candidate_score(self, left: MarketSnapshot, right: MarketSnapshot) -> float:
        return similarity(left.title, right.title)

    def validated(self, left: MarketSnapshot, right: MarketSnapshot) -> bool:
        for m in self.mappings:
            if m.enabled and {m.left_key, m.right_key} == {left.key, right.key}:
                # A manual override may bypass title similarity, never settlement validation.
                return left.resolution_key == right.resolution_key == m.resolution_key
        return False

    def candidate(self, left: MarketSnapshot, right: MarketSnapshot) -> bool:
        return self.validated(left, right) or self.candidate_score(left, right) >= self.threshold
