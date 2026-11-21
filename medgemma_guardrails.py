
import logging
import os
import re
import unicodedata
from dataclasses import dataclass

SEE_DOCTOR = {
    "shona": "Enda kuchiremba kana uine kurwadziwa kwakanyanya, kubuda ropa kwakawanda, kana fivha yepamusoro.",
    "ndebele": "Iya kudokotela uma unobuhlungu obukhulu, ukuphuma kwegazi okukhulu, noma imfiva ephezulu.",
    "chinyanja": "Pitani kudokotala ngati muli ndi kupweteka kwakukulu, kutuluka magazi ambiri, kapena malungo apamwamba.",
    "lozi": "Bona ngaka kapili ha u ka ba ni buhlungu bo boholo, kuelwa mali a mangi, kamba mufufutso o mutuna.",
    "tonga": "Bona dokotela cakufwambana, kutuluka magazi amanji, naa malungo apamwamba.",
    "bemba": "Kamubona musilisi mukufwambaana kuti mwamvwa kucisa kapati, kuswa bulowa bunji, naa kupya kapati mubili.",
}
SEE_DOCTOR_DEFAULT = "See a doctor immediately if you experience severe pain, heavy bleeding, or high fever."


SELF_HARM_SUPPORT = {
    # "shona": "...",
    # "ndebele": "...",
    # "chinyanja": "...",
    # "lozi": "...",
    # "tonga": "...",
    # "bemba": "...",
}
SELF_HARM_DEFAULT = (
    "I'm really sorry you're going through this. You don't have to face it alone. "
    "Please go to your nearest clinic or hospital now, or tell someone you trust so they can be "
    "with you. If you are in immediate danger, ask someone nearby to take you for help right away. "
    "You can also type *agent* to speak to a person."
)

# ─────────────────────────────────────────────────────────────────────────────
# LOCAL-LANGUAGE SELF-HARM PHRASES
# ─────────────────────────────────────────────────────────────────────────────
# Structure: {lang: (list_of_phrases, "description", review_status)}
#
# ACTIVE IN PRODUCTION: a language's phrases are matched (assess_safety, is_self_harm,
# compose_reply and the message router in main.py) when its review_status is "APPROVED".
# Matching is language-independent: an approved phrase is detected whatever language the
# message was classified as, inside mixed-language messages, and without TranslateGemma.
# Matching is whole-word only, after normalize_for_safety (case, spacing, apostrophes, NFKC).
#
# REVIEW STATE: the Dawa Health project team confirmed that the existing phrase contents below
# were clinically and linguistically verified, and authorised their activation. That
# confirmation is recorded in CLAUDE_INDEPENDENT_AUDIT.md. The phrase text is byte-for-byte the
# version that was audited (locked by tests/test_guardrails.py). Do not add or edit phrases
# without the same clinical and native-speaker review.
# ─────────────────────────────────────────────────────────────────────────────
MULTILINGUAL_SELF_HARM_FIXTURES = {
    "shona": (
        ["ndinovave kubuda", "hana hunhu hwekushanda"],
        "shona: distress / life-ending expressions",
        "APPROVED",
    ),
    "ndebele": (
        ["ngilokhu ngacabanga ngokuzibulala", "angifuni ukupila"],
        "ndebele: self-harm / life-ending expressions",
        "APPROVED",
    ),
    "chinyanja": (
        ["sindikhuluphire ndikufuna kubvina"],
        "chinyanja: distress / self-harm expressions",
        "APPROVED",
    ),
    "bemba": (
        ["nshakusanga ubulwele"],
        "bemba: distress / life-ending expressions",
        "APPROVED",
    ),
    "tonga": (
        ["ndiilonda kapati"],
        "tonga: distress / self-harm expressions",
        "APPROVED",
    ),
    "lozi": (
        ["ha ni zuba mbilien"],
        "lozi: distress / self-harm expressions",
        "APPROVED",
    ),
}


# Audit history. The English glosses quoted here were written by an earlier coding agent, were
# never verified, and were superseded by the project team's confirmation of the phrases.
# They are kept only so the audit trail is complete; they are not translations.
LOCAL_SELF_HARM_REVIEW_NOTES = {
    "shona": "Unverified agent gloss: 'ndinovave kubuda' = 'I keep vomiting'. Audit flagged that if "
             "that gloss were right, vomiting messages would get the self-harm reply. Team confirmed "
             "the phrase; monitor for false positives after release.",
    "ndebele": "Unverified agent glosses: 'thinking about killing myself', 'I don't want to live'. "
               "Team confirmed the phrases as written (including the spelling 'ukupila').",
    "chinyanja": "Unverified agent gloss: 'distress expressions'. Team confirmed the phrase.",
    "bemba": "Unverified agent gloss: 'expressions of despair'. Team confirmed the phrase.",
    "tonga": "Unverified agent gloss: 'deep distress'. Team confirmed the phrase.",
    "lozi": "Unverified agent gloss: 'ha ni zuba mbilien' = 'I am very sick'. Audit flagged the same "
            "false-positive risk as Shona. Team confirmed the phrase; monitor after release.",
}

APPROVED = "APPROVED"


def multilingual_self_harm_fixture_status(lang: str) -> str:
    """Review status of a language's local self-harm phrases: "APPROVED", "PENDING" or
    "NOT_INCLUDED". Only "APPROVED" phrases are used for detection."""
    entry = MULTILINGUAL_SELF_HARM_FIXTURES.get(lang)
    if entry is None:
        return "NOT_INCLUDED"
    return entry[2]


def approved_local_self_harm_phrases():
    """[(lang, phrase)] for every language whose phrases are APPROVED."""
    return [(lang, phrase)
            for lang, (phrases, _desc, status) in MULTILINGUAL_SELF_HARM_FIXTURES.items()
            if status == APPROVED
            for phrase in phrases]


# STARTER LIST: English terms plus the local blood/bleeding words that already appear in this repo.
# Clinicians who speak each language should extend this (convulsions, baby not moving, waters breaking...).
# A false positive only adds the referral line in front of the answer, so lean towards including terms.
DANGER_PATTERNS = [
    r"\bbleed(?:ing|s)?\b", r"\bblood loss\b", r"\bpassing blood\b", r"\bheavy period\b",
    r"\bhaemorrhag\w*", r"\bhemorrhag\w*", r"\bmiscarr\w*",
    r"\bconvuls\w*", r"\bseizure\w*", r"\bfits\b", r"\bunconscious\b", r"\bfaint(?:ed|ing)?\b",
    r"\bpassed out\b", r"\bsevere (?:headache|pain|abdominal pain|stomach pain)\b",
    r"\bblurr?(?:ed|y) vision\b", r"\bswollen (?:face|hands)\b",
    r"\b(?:baby|fetus|foetus) (?:is |has )?(?:not|stopped|isn't|no) (?:moving|movement)\b",
    r"\bno (?:fetal |foetal |baby )?movement\b", r"\bwater(?:s)? (?:has |have )?broke\b",
    r"\bleaking (?:fluid|water)\b", r"\b(?:high|very high) fever\b",
    r"\b(?:can'?t|cannot|difficulty|hard to) breath\w*", r"\blabou?r pains?\b",
    # local-language words already used in the bot's own referral lines
    r"\bropa\b", r"\bmagazi\b", r"\bigazi\b", r"\bbulowa\b", r"\bkuelwa mali\b",
]
_DANGER_RE = re.compile("|".join(DANGER_PATTERNS), re.I)

# "end ..." was r"\bend (?:my|it all|my life)\b": the bare "my" alternative matched any "end my <x>"
# ("How can I end my nausea?"), sending the crisis message instead of an answer. It is narrowed to
# the self-harm objects it was there to catch; "end it all" is unchanged.
# STARTER LIST: self-harm wording. Same rule as above: clinicians who speak each language
# should extend this. A false positive here only sends the supportive message, so lean inclusive.
SELF_HARM_PATTERNS = [
    r"\bsuicid\w*", r"\bkill (?:myself|me)\b", r"\bend (?:it all|my (?:own )?(?:life|suffering|existence))\b",
    r"\bwant(?:ed)? to die\b", r"\bdon'?t want to (?:live|be alive)\b",
    r"\bhurt(?:ing)? myself\b", r"\bharm(?:ing)? myself\b", r"\bself[- ]?harm\b",
    r"\btake my (?:own )?life\b", r"\bbetter off dead\b",
]
_SELF_HARM_RE = re.compile("|".join(SELF_HARM_PATTERNS), re.I)

_CONTROL_TOKENS = re.compile(r"<\s*/?\s*(?:start_of_turn|end_of_turn|bos|eos|pad)\s*>|<unused\d+>", re.I)
FOOTER_ON = os.environ.get("MEDGEMMA_FOOTER", "1") != "0"
MIN_ANSWER_CHARS = 8


def see_doctor_line(lang: str) -> str:
    return SEE_DOCTOR.get(lang, SEE_DOCTOR_DEFAULT)


def self_harm_message(lang: str) -> str:
    return SELF_HARM_SUPPORT.get(lang, SELF_HARM_DEFAULT)


# WhatsApp clients (iOS "smart punctuation" in particular) send typographic apostrophes, so
# "I don’t want to live" or "I can’t breathe" would otherwise slip past the ASCII patterns.
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u2032": "'",
                              "\u00b4": "'", "`": "'"})


def normalize_for_safety(text) -> str:
    """NFKC (full-width letters, non-breaking spaces), straight apostrophes, single spaces,
    case-folded. Only used for matching; the user's text is never altered."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).translate(_APOSTROPHES)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _phrase_regex(phrase: str):
    """Whole-word match for a phrase, tolerant of spacing; never matches inside a longer word."""
    words = normalize_for_safety(phrase).split(" ")
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)")


@dataclass(frozen=True)
class SafetyAssessment:
    """Result of the safety screen on a user's message.
    matches: tuple of (kind, source, detail), e.g. ("self_harm", "english", "kill myself")
    or ("self_harm", "ndebele", "<approved phrase>")."""
    self_harm: bool
    danger_sign: bool
    matches: tuple = ()

    @property
    def urgent(self) -> bool:
        return self.self_harm or self.danger_sign

    @property
    def category(self):
        """Self-harm takes priority over danger signs, as in compose_reply."""
        if self.self_harm:
            return "self_harm"
        return "danger_sign" if self.danger_sign else None


def assess_safety(text) -> SafetyAssessment:
    """Run every safety check on one message: English self-harm patterns, approved local-language
    self-harm phrases (any language, no translation needed) and maternal danger signs."""
    norm = normalize_for_safety(text)
    if not norm:
        return SafetyAssessment(False, False)
    matches = []
    m = _SELF_HARM_RE.search(norm)
    if m:
        matches.append(("self_harm", "english", m.group(0)))
    for lang, phrase in approved_local_self_harm_phrases():
        if _phrase_regex(phrase).search(norm):
            matches.append(("self_harm", lang, phrase))
    m = _DANGER_RE.search(norm)
    if m:
        matches.append(("danger_sign", "pattern", m.group(0)))
    kinds = {k for k, _, _ in matches}
    return SafetyAssessment("self_harm" in kinds, "danger_sign" in kinds, tuple(matches))


def is_danger_sign(text: str) -> bool:
    return assess_safety(text).danger_sign


def is_self_harm(text: str) -> bool:
    return assess_safety(text).self_harm


def _has_repetition_loop(text: str) -> bool:
    parts = [p.strip().lower() for p in re.split(r"[.!?\n]+", text) if len(p.strip()) >= 4]
    return any(parts.count(p) >= 3 for p in set(parts))


def clean_model_output(text):
    """Return a safe-to-send string, or None if the output should be discarded."""
    if not text:
        return None
    text = _CONTROL_TOKENS.sub("", text)
    text = text.replace("product_image", "").replace("unable_to_solve_query", "").replace("agent_request", "")
    text = re.sub(r"^\s*model\s*\n", "", text, flags=re.I).strip()
    if len(text) < MIN_ANSWER_CHARS or _has_repetition_loop(text):
        return None
    if text[-1] not in ".!?)\"'”:" and not text.endswith("\n"):      # generation hit max_new_tokens mid-sentence
        cut = max(text.rfind(c) for c in ".!?")
        if cut > len(text) * 0.5:
            text = text[: cut + 1]
    return text


def compose_reply(question: str, lang: str, model_text):
    """Combine guardrails and the (already cleaned) model answer.
    Returns None only when there is nothing to send and no danger sign (caller shows its fallback)."""
    safety = assess_safety(question)
    # Self-harm wording takes priority: send the supportive message, never the model's answer.
    if safety.self_harm:
        sources = sorted({src for kind, src, _ in safety.matches if kind == "self_harm"})
        logging.warning(f"[guardrails] self-harm wording detected, lang={lang}, matched={sources}")
        return f"💛 {self_harm_message(lang)}"

    line = see_doctor_line(lang)
    if safety.danger_sign:
        logging.warning(f"[guardrails] danger sign detected, lang={lang}")
        return f"⚠️ {line}" + (f"\n\n{model_text}" if model_text else "")
    if not model_text:
        return None
    return f"{model_text}\n\n{line}" if FOOTER_ON else model_text
