"""Follow-up question and shop/order flow in main.py."""
import pytest

import main
from conftest import PHONE_ID, USER
from products_data import products_by_category

LANGS = ["english", "shona", "ndebele", "chinyanja", "tonga", "bemba", "lozi"]
CATS = list(products_by_category)


def user(bot, step="chat", lang="english", **extra):
    bot.main.user_states[USER] = {"step": step, "language": lang, "user_id": "DH-0001-TEST", **extra}
    return bot.main.user_states[USER]


def last_text(bot):
    return bot.wa.texts_to(USER)[-1]


# ─────────────── follow-up ───────────────

def test_follow_up_no_offers_products(bot):
    user(bot, "follow_up")
    bot.db.add_message(USER, "user", "no")
    assert bot.main.handle_follow_up_reply(USER, "no", PHONE_ID) is True
    assert bot.main.user_states[USER]["step"] == "shop_interest"
    assert USER not in bot.db.messages or bot.db.messages[USER] == []   # bare "no" dropped
    assert "purchase" in last_text(bot)


def test_follow_up_yes_asks_question(bot):
    user(bot, "follow_up", "shona")
    assert bot.main.handle_follow_up_reply(USER, "hongu", PHONE_ID) is True
    assert last_text(bot) == main.ASK_QUESTION_MAP["shona"]
    assert bot.main.user_states[USER]["step"] == "chat"


def test_follow_up_new_question_falls_through(bot):
    user(bot, "follow_up")
    assert bot.main.handle_follow_up_reply(USER, "What about iron tablets?", PHONE_ID) is False
    assert bot.main.user_states[USER]["step"] == "chat"
    assert bot.wa.calls == []


@pytest.mark.parametrize("lang", LANGS)
def test_ask_follow_up_in_each_language(bot, lang):
    user(bot, "chat", lang)
    bot.main.ask_follow_up_question(USER, PHONE_ID)
    assert last_text(bot) == main.FOLLOWUP_MAP.get(lang, "Is there anything else I can help you with?")


# ─────────────── shop interest / categories ───────────────

@pytest.mark.parametrize("text, intent", [
    ("yes", "browse"), ("show me", "browse"), ("imikhiqizo", "browse"),
    ("no", "decline"), ("bye", "decline"), ("kwete", "decline"),
    ("hmm", "unknown"),
])
def test_interpret_shop_intent(text, intent):
    assert main._interpret_shop_intent(text) == intent


@pytest.mark.parametrize("lang", LANGS)
def test_shop_interest_decline_says_bye_in_language(bot, lang):
    user(bot, "shop_interest", lang, cart=[{"product": "x"}])
    bot.main.handle_shop_interest(USER, "no", PHONE_ID)
    expected = main.BYE_MAP.get(lang, "Alright! Have a nice day. Say 'hi' if you have more questions.")
    assert last_text(bot) == expected
    assert bot.main.user_states[USER]["step"] == "chat"
    assert "cart" not in bot.main.user_states[USER]


@pytest.mark.parametrize("lang", LANGS)
def test_shop_categories_listing(bot, lang):
    user(bot, "shop_interest", lang)
    bot.main.handle_shop_interest(USER, "yes", PHONE_ID)
    text = last_text(bot)
    assert f"*1. {CATS[0]}*" in text
    assert bot.main.user_states[USER]["step"] == "shop_browse"


def test_purchase_interest_prompt_languages(bot):
    for lang in LANGS:
        user(bot, "follow_up", lang)
        bot.main._ask_purchase_interest(USER, PHONE_ID, lang)
        assert bot.main.user_states[USER]["step"] == "shop_interest"


# ─────────────── browse ───────────────

@pytest.mark.parametrize("lang", LANGS)
def test_browse_valid_category_number(bot, lang):
    user(bot, "shop_browse", lang)
    bot.main.handle_shop_browse(USER, "1", PHONE_ID)
    text = last_text(bot)
    first = products_by_category[CATS[0]][0]
    assert first["name"] in text and first["price"] in text
    st = bot.main.user_states[USER]
    assert st["step"] == "shop_order_decision" and st["shop_category"] == CATS[0]


@pytest.mark.parametrize("lang", LANGS)
def test_browse_invalid_number(bot, lang):
    user(bot, "shop_browse", lang)
    bot.main.handle_shop_browse(USER, "99", PHONE_ID)
    assert str(len(CATS)) in last_text(bot)
    assert bot.main.user_states[USER]["step"] == "shop_browse"


def test_browse_product_name_selects_it(bot):
    user(bot, "shop_browse")
    bot.main.handle_shop_browse(USER, "birth kit", PHONE_ID)
    st = bot.main.user_states[USER]
    assert st["shop_selected_product"] == "Birth kit" and st["step"] == "shop_quantity"


def test_browse_unknown_text_relists_categories(bot):
    user(bot, "shop_browse")
    bot.main.handle_shop_browse(USER, "zz", PHONE_ID)
    assert "Product Categories" in last_text(bot)


def test_match_product():
    assert main._match_product("ul") is None
    assert main._match_product("ultrasound")["name"] == "Ultrasound"
    assert main._match_product("i want the hpv test kit please")["name"] == "HPV Test Kit"
    assert main._match_product("nothing matches this") is None


# ─────────────── order decision ───────────────

@pytest.mark.parametrize("lang", LANGS)
def test_order_decision_yes(bot, lang):
    user(bot, "shop_order_decision", lang)
    bot.main.handle_shop_order_decision(USER, "yes", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_product_name"


@pytest.mark.parametrize("lang", LANGS)
def test_order_decision_no(bot, lang):
    user(bot, "shop_order_decision", lang)
    bot.main.handle_shop_order_decision(USER, "no", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_more_categories"


def test_order_decision_product_name(bot):
    user(bot, "shop_order_decision")
    bot.main.handle_shop_order_decision(USER, "ultrasound", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_quantity"


@pytest.mark.parametrize("lang", LANGS)
def test_order_decision_unclear(bot, lang):
    user(bot, "shop_order_decision", lang)
    bot.main.handle_shop_order_decision(USER, "hmm", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_order_decision"
    assert bot.wa.texts_to(USER)


# ─────────────── product name / more categories ───────────────

@pytest.mark.parametrize("lang", LANGS)
def test_product_name_not_found(bot, lang):
    user(bot, "shop_product_name", lang)
    bot.main.handle_shop_product_name(USER, "unicorn", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_product_name"


def test_product_name_found(bot):
    user(bot, "shop_product_name")
    bot.main.handle_shop_product_name(USER, "Birth kit", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_quantity"


def test_more_categories(bot):
    user(bot, "shop_more_categories")
    bot.main.handle_shop_more_categories(USER, "yes", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_browse"
    user(bot, "shop_more_categories", "lozi")
    bot.main.handle_shop_more_categories(USER, "no", PHONE_ID)
    assert last_text(bot) == main.BYE_MAP["lozi"]


# ─────────────── quantity / add more / address ───────────────

@pytest.mark.parametrize("lang", LANGS)
def test_quantity_in_each_language(bot, lang):
    user(bot, "shop_quantity", lang, shop_selected_product="Birth kit", shop_selected_price="K200")
    bot.main._ask_quantity(USER, PHONE_ID, lang, "Birth kit")
    assert "Birth kit" in last_text(bot)
    bot.main.handle_shop_quantity(USER, "I want 3 please", PHONE_ID)
    st = bot.main.user_states[USER]
    assert st["cart"] == [{"product": "Birth kit", "price": "K200", "quantity": 3}]
    assert st["step"] == "shop_add_more"
    assert "x3" in last_text(bot)


@pytest.mark.parametrize("lang", LANGS)
def test_quantity_invalid(bot, lang):
    user(bot, "shop_quantity", lang)
    bot.main.handle_shop_quantity(USER, "zero", PHONE_ID)
    bot.main.handle_shop_quantity(USER, "0", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_quantity"
    assert "cart" not in bot.main.user_states[USER]


def test_add_more_product_and_browse(bot):
    user(bot, "shop_add_more")
    bot.main.handle_shop_add_more(USER, "ultrasound", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_quantity"
    user(bot, "shop_add_more")
    bot.main.handle_shop_add_more(USER, "yes", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_browse"


@pytest.mark.parametrize("lang", LANGS)
def test_add_more_done_asks_address(bot, lang):
    user(bot, "shop_add_more", lang)
    bot.main.handle_shop_add_more(USER, "no", PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "shop_address"


@pytest.mark.parametrize("lang", LANGS)
def test_address_saves_orders_and_confirms(bot, lang):
    cart = [{"product": "Birth kit", "price": "K200", "quantity": 2},
            {"product": "Ultrasound", "price": "K150", "quantity": 1}]
    user(bot, "shop_address", lang, cart=cart, shop_selected_product="Ultrasound")
    bot.main.handle_shop_address(USER, "  12 Test Street, Test Town  ", PHONE_ID)

    assert [o["product"] for o in bot.db.orders] == ["Birth kit", "Ultrasound"]
    assert bot.db.orders[0] == {"phone": USER, "user_id": "DH-0001-TEST", "product": "Birth kit",
                                "price": "K200", "quantity": 2, "address": "12 Test Street, Test Town"}
    text = last_text(bot)
    assert "Birth kit x2" in text and "12 Test Street, Test Town" in text
    st = bot.main.user_states[USER]
    assert st["step"] == "chat" and "cart" not in st and "shop_selected_product" not in st


def test_address_with_empty_cart_just_resets(bot):
    user(bot, "shop_address")
    bot.main.handle_shop_address(USER, "Somewhere", PHONE_ID)
    assert bot.db.orders == [] and bot.wa.calls == []
    assert bot.main.user_states[USER]["step"] == "chat"
