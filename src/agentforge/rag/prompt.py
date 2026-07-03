"""Grounding-only prompt construction (Req 12.4).

The generation prompt is composed of exactly three ingredients:

1. a **fixed** template (the only static text the platform contributes),
2. the user's **query**, and
3. the **text of the retrieved chunks**.

No content from outside the retrieved chunks is ever introduced, which is what makes
the answers trustworthy and the citations verifiable. This is enforced as a correctness
property (Property 11) rather than left to convention.
"""

from __future__ import annotations

# Fixed template fragments. These are the ONLY static strings added to the prompt;
# everything else is the query or retrieved chunk text.
PROMPT_HEADER = (
    "Answer the question using only the provided context. "
    "If the context does not contain the answer, say you do not know.\n"
)
QUESTION_LABEL = "Question: "
CONTEXT_LABEL = "\nContext:\n"
CHUNK_SEPARATOR = "\n\n"


def build_prompt(query: str, chunk_texts: list[str]) -> str:
    """Build a grounding-only prompt from the template, query, and chunk texts.

    The result is a pure, deterministic function of its inputs and contains no content
    originating outside ``query`` and ``chunk_texts`` (Req 12.4).
    """
    context = CHUNK_SEPARATOR.join(chunk_texts)
    return f"{PROMPT_HEADER}{QUESTION_LABEL}{query}{CONTEXT_LABEL}{context}"
