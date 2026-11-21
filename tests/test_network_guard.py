"""The suite must never reach WhatsApp, Supabase, Gemini or Hugging Face."""
import os

import pytest
import requests

from conftest import NetworkBlockedError


@pytest.mark.parametrize("url", ["https://graph.facebook.com/v19.0/x/messages",
                                 "https://example.supabase.co/rest/v1/users"])
def test_real_http_is_blocked(url):
    with pytest.raises((NetworkBlockedError, requests.exceptions.ConnectionError)):
        requests.get(url, timeout=1)


def test_only_synthetic_credentials_in_environment():
    assert os.environ["WA_TOKEN"].startswith("test-")
    assert os.environ["GEN_API"].startswith("test-")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "MEDGEMMA_URL", "TRANSLATEGEMMA_URL", "HF_TOKEN"):
        assert key not in os.environ
