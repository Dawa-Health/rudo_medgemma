"""
generate_reply / answer_user: the multilingual MedGemma pipeline.
Translation and MedGemma are stubbed; the real clinical guardrails (compose_reply,
clean_model_output) run unmodified so danger-sign behaviour is tested end to end.
"""
import pytest

import main
import medgemma_guardrails as g
from conftest import PHONE_ID, USER

ANSWER = "Drink plenty of water and attend your antenatal visits regularly."


@pytest.fixture(autouse=True)
def footer_on(monkeypatch):
    monkeypatch.setattr(g, "FOOTER_ON", True)


def setup_user(bot, lang, prompt):
    bot.main.user_states[USER] = {"step": "chat", "language": lang, "user_id": "DH-0001-TEST"}
    bot.db.add_message(USER, "user", prompt)


# ─────────────── English (no pivot) ───────────────

def test_english_reply_has_footer_and_english_copy(bot):
    setup_user(bot, "english", "What should I eat?")
    reply, reply_en = bot.main.generate_reply(USER, "What should I eat?", "english")
    assert reply == f"{ANSWER}\n\n{g.SEE_DOCTOR_DEFAULT}"
    assert reply_en == ANSWER
    assert bot.models.medgemma_questions == ["What should I eat?"]
    assert bot.models.translations == []


def test_english_history_is_passed_as_pairs(bot):
    bot.db.add_message(USER, "user", "How many visits?")
    bot.db.add_message(USER, "bot", "At least eight antenatal contacts are recommended.")
    setup_user(bot, "english", "And when should the first be?")
    bot.main.generate_reply(USER, "And when should the first be?", "english")
    assert bot.models.medgemma_histories[0] == [
        {"user": "How many visits?", "model": "At least eight antenatal contacts are recommended."}]


def test_danger_sign_referral_comes_first(bot):
    setup_user(bot, "english", "I have heavy bleeding")
    reply, _ = bot.main.generate_reply(USER, "I have heavy bleeding", "english")
    assert reply.startswith(f"⚠️ {g.SEE_DOCTOR_DEFAULT}")
    assert ANSWER in reply


def test_self_harm_never_returns_model_text(bot):
    setup_user(bot, "english", "I want to end my life")
    reply, _ = bot.main.generate_reply(USER, "I want to end my life", "english")
    assert reply == f"💛 {g.SELF_HARM_DEFAULT}"


# ─────────────── model-service failures ───────────────

def test_medgemma_unavailable_returns_none(bot, monkeypatch):
    monkeypatch.setattr(main, "medgemma_enabled", lambda: False)
    assert bot.main.generate_reply(USER, "What should I eat?", "english") == (None, None)


def test_medgemma_unavailable_still_refers_danger_sign(bot, monkeypatch):
    monkeypatch.setattr(main, "medgemma_enabled", lambda: False)
    reply, reply_en = bot.main.generate_reply(USER, "the baby stopped moving", "english")
    assert reply == f"⚠️ {g.SEE_DOCTOR_DEFAULT}"
    assert reply_en is None


def test_medgemma_garbage_output_is_discarded(bot):
    bot.models.medgemma = ["ok."]          # too short: clean_model_output drops it
    setup_user(bot, "english", "What should I eat?")
    assert bot.main.generate_reply(USER, "What should I eat?", "english") == (None, None)


def test_medgemma_returns_none(bot):
    bot.models.medgemma = []
    setup_user(bot, "english", "What should I eat?")
    assert bot.main.generate_reply(USER, "What should I eat?", "english") == (None, None)


# ─────────────── pivoted languages ───────────────

def test_shona_pivot_round_trip(bot):
    bot.models.translate_fn = lambda t, s, d: "I am pregnant, what should I eat?" if d == "english" \
        else "Inwa mvura yakawanda uye enda kukiriniki nguva dzose."
    setup_user(bot, "shona", "Ndine pamuviri, ndodya chii?")
    reply, reply_en = bot.main.generate_reply(USER, "Ndine pamuviri, ndodya chii?", "shona")

    assert bot.models.translations[0] == ("Ndine pamuviri, ndodya chii?", "shona", "english")
    assert bot.models.medgemma_questions == ["I am pregnant, what should I eat?"]
    assert bot.models.translations[1] == (ANSWER, "english", "shona")
    assert reply == f"Inwa mvura yakawanda uye enda kukiriniki nguva dzose.\n\n{g.SEE_DOCTOR['shona']}"
    assert reply_en == ANSWER
    # the English question was attached to the stored user message
    assert bot.db.messages[USER][-1]["message_en"] == "I am pregnant, what should I eat?"


def test_pivot_danger_sign_found_via_english_translation(bot):
    # The local wording has no listed keyword; the English translation does.
    bot.models.translate_fn = lambda t, s, d: "My waters broke" if d == "english" \
        else "Enda kuchipatara izvozvi nekukurumidza."
    setup_user(bot, "shona", "Mvura yangu yaputika")
    reply, _ = bot.main.generate_reply(USER, "Mvura yangu yaputika", "shona")
    assert reply.startswith(f"⚠️ {g.SEE_DOCTOR['shona']}")


def test_pivot_requires_translategemma(bot, monkeypatch):
    monkeypatch.setattr(main, "translategemma_enabled", lambda: False)
    assert bot.main.generate_reply(USER, "Ndine pamuviri", "shona") == (None, None)
    assert bot.models.medgemma_questions == []


def test_translation_failure_is_retried_then_fails_safely(bot):
    calls = []

    def broken(t, s, d):
        calls.append(1)
        raise RuntimeError("translator down")

    bot.models.translate_fn = broken
    setup_user(bot, "bemba", "Ndi ne fumo")
    assert bot.main.generate_reply(USER, "Ndi ne fumo", "bemba") == (None, None)
    assert len(calls) == 2                     # _retry made two attempts


def test_non_english_model_reply_retried_without_history(bot):
    bot.models.medgemma = ["Ndine urombo kuti uri kurwadziwa zvikuru nhasi chaizvo mai", ANSWER]
    bot.models.translate_fn = lambda t, s, d: "question in english" if d == "english" \
        else "Inwa mvura yakawanda uye enda kukiriniki."
    setup_user(bot, "shona", "Ndiri kurwadziwa")
    reply, reply_en = bot.main.generate_reply(USER, "Ndiri kurwadziwa", "shona")
    assert bot.models.medgemma_histories[1] == []
    assert reply_en == ANSWER


def test_non_english_model_reply_twice_is_discarded(bot):
    shona = "Ndine urombo kuti uri kurwadziwa zvikuru nhasi chaizvo mai"
    bot.models.medgemma = [shona]
    setup_user(bot, "shona", "Ndiri kurwadziwa")
    assert bot.main.generate_reply(USER, "Ndiri kurwadziwa", "shona") == (None, None)


def test_english_leak_in_outbound_translation_is_discarded(bot):
    bot.models.translate_fn = lambda t, s, d: "question" if d == "english" else ANSWER
    setup_user(bot, "tonga", "Ndiyanda kuziba")
    assert bot.main.generate_reply(USER, "Ndiyanda kuziba", "tonga") == (None, None)


# ─────────────── answer_user ───────────────

def test_answer_user_success_sends_thinking_reply_and_follow_up(bot):
    setup_user(bot, "english", "What should I eat?")
    bot.main.answer_user(USER, "What should I eat?", PHONE_ID)
    texts = bot.wa.texts_to(USER)
    assert texts[0] == "Let me think..."
    assert ANSWER in texts[1]
    assert texts[2] == "Is there anything else I can help you with?"
    assert bot.main.user_states[USER]["step"] == "follow_up"
    stored = [m for m in bot.db.messages[USER] if m["role"] == "bot"]
    assert len(stored) == 1 and stored[0]["message_en"] == ANSWER    # only the answer is stored


def test_answer_user_short_prompt_skips_thinking(bot):
    setup_user(bot, "shona", "iron?")
    bot.models.translate_fn = lambda t, s, d: "iron?" if d == "english" else "Simbi yakakosha."
    bot.main.answer_user(USER, "iron?", PHONE_ID)
    assert bot.wa.texts_to(USER)[0].startswith("Simbi")


def test_answer_user_failure_message_not_stored(bot, monkeypatch):
    monkeypatch.setattr(main, "medgemma_enabled", lambda: False)
    setup_user(bot, "chinyanja", "Ndikufuna kudziwa za mimba")
    bot.main.answer_user(USER, "Ndikufuna kudziwa za mimba", PHONE_ID)
    texts = bot.wa.texts_to(USER)
    assert texts[0] == main.THINKING_MAP["chinyanja"]
    assert texts[1] == main.failure_message("chinyanja")
    assert bot.main.user_states[USER]["step"] == "chat"
    assert [m["role"] for m in bot.db.messages[USER]] == ["user"]
