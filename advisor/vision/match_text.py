# -*- coding: utf-8 -*-
"""Fuzzy-match OCR text against the known in-game name dictionary.

Ports the proven MaaAutoReverse rules:
  - explicit wrong->right Chinese correction map
  - exact match ignoring spaces
  - substring match only when length difference <= 1 (avoids base/alter confusion)
  - difflib similarity >= 0.6 for names of length >= 2
Because we hold the full 141-operator / 70-item dictionary, free OCR output is
snapped to a canonical name instead of being trusted verbatim.
"""
import difflib
from typing import List, Optional

# Known OCR confusions for this mode's operator names (extend from real runs).
DEFAULT_CORRECTION = {"铜": "锏", "湖": "溯"}

SIM_THRESHOLD = 0.6
MAX_LEN_DIFF = 1
# Higher bar for the large (~1.8k) enemy-name index. A threshold sweep over
# truncation probes showed 0.85 cuts confident-wrong snaps by ~78% vs 0.60
# while keeping full-name recall at 100% (real panel OCR reads whole names at
# ~0.99 confidence, score 1.0 exact). Only fuzzy guesses are made stricter;
# exact matches and single-glyph refusal are unaffected.
CONSERVATIVE_THRESHOLD = 0.85
# Minimum lead of the best candidate over the runner-up. A truncation probe
# over the full index showed most wrong snaps are crowded races (several near
# names tied, e.g. '险水手' -> 历险水手/寻险水手 both 0.857); requiring a clear
# margin turns those into safe unknowns instead of confident wrong guesses.
CONSERVATIVE_GAP = 0.12


def normalize(text: str, correction: dict = None) -> str:
    correction = correction or DEFAULT_CORRECTION
    s = (text or "").strip()
    if not s:
        return ""
    if s in correction:
        s = correction[s]
    for wrong, right in correction.items():
        if wrong in s:
            s = s.replace(wrong, right)
    return s


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def match_one(ocr_text: str, dictionary: List[str],
              correction: dict = None, threshold: float = SIM_THRESHOLD,
              conservative: bool = False) -> Optional[str]:
    """Return the canonical dictionary name best matching the OCR text, or None.

    Default mode keeps the proven shop-OCR behaviour (aggressive substring
    snap). ``conservative=True`` is for the large ~1.8k enemy-name index, where
    aggressive substring snaps cross-fire between near names (e.g. a truncated
    '奇重犯' wrongly snapping to the short name '重犯'). In conservative mode
    there is no unconditional substring short-circuit: candidates must clear
    the similarity threshold, exact-length matches are preferred, and single-
    character OCR is refused rather than guessed.
    """
    norm = normalize(ocr_text, correction)
    if not norm:
        return None
    norm_ns = norm.replace(" ", "")

    if conservative:
        if len(norm_ns) < 2:
            return None  # never guess a multi-char enemy name from one glyph
        eff_threshold = max(threshold, CONSERVATIVE_THRESHOLD)
        scored = match_ranked(norm_ns, dictionary, eff_threshold)
        if not scored:
            return None
        top_score = scored[0][0]
        if top_score >= 0.999:
            return scored[0][1]  # exact (space-insensitive) match
        if len(scored) == 1:
            return scored[0][1]  # sole candidate above the high threshold
        if top_score - scored[1][0] >= CONSERVATIVE_GAP:
            return scored[0][1]  # dominant, unambiguous candidate
        return None  # crowded near-name race: refuse rather than mis-snap

    best_name, best_score = None, 0.0
    for target in dictionary:
        if not target:
            continue
        t_ns = target.replace(" ", "")
        if t_ns == norm_ns:
            return target
        if abs(len(t_ns) - len(norm_ns)) <= MAX_LEN_DIFF:
            if target in norm or t_ns in norm_ns:
                return target
            if len(t_ns) >= 2:
                score = _similar(t_ns, norm_ns)
                if score >= threshold and score > best_score:
                    best_name, best_score = target, score
    return best_name


def match_ranked(norm_ns: str, dictionary: List[str],
                 threshold: float = SIM_THRESHOLD):
    """Conservative candidates as [(score, name, len_diff)], best first.

    Exact (space-insensitive) matches win outright. Otherwise every name within
    MAX_LEN_DIFF in length that clears the similarity threshold is ranked,
    preferring exact-length candidates then the highest similarity. Callers use
    this to detect ambiguity (top two scores too close to call confidently).
    """
    exact = [t for t in dictionary
             if t and t.replace(" ", "") == norm_ns]
    if exact:
        return [(1.0, exact[0], 0)]
    if len(norm_ns) < 2:
        return []
    candidates = []
    for target in dictionary:
        if not target:
            continue
        t_ns = target.replace(" ", "")
        len_diff = abs(len(t_ns) - len(norm_ns))
        if len_diff <= MAX_LEN_DIFF and len(t_ns) >= 2:
            score = _similar(t_ns, norm_ns)
            if score >= threshold:
                candidates.append((score, target, len_diff))
    # exact-length first (len_diff 0), then higher similarity, then shorter name
    candidates.sort(key=lambda c: (c[2], -c[0], len(c[1])))
    return candidates


def classify_kind(name: str, operators: set, items: set):
    if name in operators:
        return "operator"
    if name in items:
        return "item"
    return "unknown"
