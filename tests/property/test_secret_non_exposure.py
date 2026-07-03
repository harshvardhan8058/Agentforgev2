"""Property-based test: secret values are never exposed.

Feature: agentforge-foundation-rag, Property 14: For any configured credential
value, that value never appears in the serialized settings representation, log
output, or error bodies produced by the platform.

Validates: Requirements 3.6
"""

from __future__ import annotations

import io
import logging

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.config.settings import Settings

# Smart generator: secrets are prefixed with a unique, collision-free token so that
# a match anywhere in serialized output unambiguously indicates a real leak (and not
# an incidental collision with a non-secret default such as the port or dimension).
_secret_values = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=40,
).map(lambda s: f"SEKRET-TOKEN-{s}")


@hyp_settings(max_examples=100)
@given(groq_secret=_secret_values, hosted_secret=_secret_values)
def test_secret_values_never_exposed(groq_secret, hosted_secret):
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        groq_api_key=groq_secret,
        hosted_embedding_api_key=hosted_secret,
    )

    # The real values are only recoverable via the explicit accessor.
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == groq_secret
    assert settings.hosted_embedding_api_key.get_secret_value() == hosted_secret

    # 1. repr / str must not contain the raw secret.
    assert groq_secret not in repr(settings)
    assert groq_secret not in str(settings)
    assert hosted_secret not in repr(settings)
    assert hosted_secret not in str(settings)

    # 2. Serialized settings (dict + JSON) must not contain the raw secret.
    dumped = str(settings.model_dump())
    dumped_json = settings.model_dump_json()
    for blob in (dumped, dumped_json):
        assert groq_secret not in blob
        assert hosted_secret not in blob

    # 3. Log output must not contain the raw secret. Use a local handler (not the
    # function-scoped caplog fixture, which is not reset between Hypothesis examples).
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("agentforge.test.secret")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("settings=%s", settings)
        logger.info("settings_repr=%r", settings)
        handler.flush()
        log_text = stream.getvalue()
    finally:
        logger.removeHandler(handler)
    assert groq_secret not in log_text
    assert hosted_secret not in log_text
