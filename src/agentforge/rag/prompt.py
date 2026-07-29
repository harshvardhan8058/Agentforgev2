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
#
# The instructions are deliberately explicit about *form* as well as *grounding*: a
# terse instruction ("answer using only the context") yields terse, unstructured
# output from a real model, whereas asking for a direct answer plus organised
# supporting detail produces the readable result an operator expects. None of this
# adds knowledge — it only shapes how the retrieved context is presented, so the
# grounding guarantee (Req 12.4, Property 11) is untouched.
PROMPT_HEADER = (
    "You are AgentForge, a precise assistant answering from an organization's own "
    "documents.\n"
    "\n"
    "Rules:\n"
    "- Use ONLY the provided context. Never add outside knowledge or invent details.\n"
    "- If the context does not contain the answer, say so plainly and state what is "
    "missing.\n"
    "- Ignore blank form fields, page furniture, and repeated boilerplate in the "
    "context.\n"
    "\n"
    "Style:\n"
    "- Open with a direct answer in one or two sentences.\n"
    "- Then, only if it genuinely helps, add short Markdown bullets for the "
    "supporting details.\n"
    "- Preserve names, dates, amounts and identifiers exactly as written.\n"
    "- Do not restate these instructions or echo the context verbatim.\n"
)
QUESTION_LABEL = "\nQuestion: "
CONTEXT_LABEL = "\n\nContext:\n"
CHUNK_SEPARATOR = "\n\n"

# --- Ungrounded (general-knowledge) template --------------------------------------
#
# Kept strictly separate from the grounding-only template above. It is used ONLY when
# retrieval returns nothing AND the deployment has explicitly opted in to ungrounded
# answers; the resulting answer is always reported with ``grounded=False`` and zero
# citations so it can never be mistaken for a document-backed result.
GENERAL_PROMPT_HEADER = (
    "You are AgentForge, a helpful and knowledgeable assistant.\n"
    "\n"
    "No document in the user's corpus matched this question, so answer from your own "
    "general knowledge.\n"
    "\n"
    "Rules:\n"
    "- Be accurate and concise. Open with a direct answer.\n"
    "- Use short Markdown bullets or fenced code blocks when they aid clarity.\n"
    "- If you are uncertain or the question needs information you do not have, say so "
    "rather than guessing.\n"
    "- Do not claim the answer came from the user's documents.\n"
)


def build_prompt(query: str, chunk_texts: list[str]) -> str:
    """Build a grounding-only prompt from the template, query, and chunk texts.

    The result is a pure, deterministic function of its inputs and contains no content
    originating outside ``query`` and ``chunk_texts`` (Req 12.4).
    """
    context = CHUNK_SEPARATOR.join(chunk_texts)
    return f"{PROMPT_HEADER}{QUESTION_LABEL}{query}{CONTEXT_LABEL}{context}"



def build_general_prompt(query: str) -> str:
    """Build an ungrounded, general-knowledge prompt for ``query``.

    Used only on the explicitly opted-in no-grounding path. It is a separate function
    from :func:`build_prompt` on purpose: the grounding-only guarantee applies to
    document-backed answers, and mixing the two templates would make that guarantee
    impossible to verify. Answers produced from this prompt are always returned with
    ``grounded=False`` and no citations.
    """
    return f"{GENERAL_PROMPT_HEADER}{QUESTION_LABEL}{query}"
