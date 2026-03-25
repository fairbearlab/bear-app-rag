import anthropic

from bear_rag import config
from bear_rag.models import Chunk

_SYSTEM_PROMPT = (
    "You are a knowledge assistant grounded in the user's personal notes. "
    "Answer based ONLY on the provided context. "
    "Cite the chunk number [1], [2], etc. "
    "If the context doesn't contain enough information, say so explicitly."
)

_NO_CHUNKS_RESPONSE = "No relevant notes found for your question."


def generate_answer(question: str, chunks: list[Chunk]) -> str:
    """Generate an answer to *question* grounded in the retrieved *chunks*.

    Returns a plain-text answer.  If *chunks* is empty the API is not called
    and a canned 'no relevant notes' message is returned instead.
    """
    if not chunks:
        return _NO_CHUNKS_RESPONSE

    # Build the retrieved-context section.
    context_lines: list[str] = ["## Retrieved Context\n"]
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        header = (
            f"[{i}] (Source: {meta['title']} > {meta['heading_path']} "
            f"| Tags: {meta['tags']} | Modified: {meta['modified_at']})"
        )
        context_lines.append(header)
        context_lines.append(chunk.text)
        context_lines.append("")  # blank line between chunks

    question_section = f"## Question\n\n{question}"

    user_message = "\n".join(context_lines) + "\n" + question_section

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text
