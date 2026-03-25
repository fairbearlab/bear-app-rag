import unittest
from unittest.mock import MagicMock, patch

from bear_rag.models import Chunk, ChunkMetadata


def _make_chunk(
    note_pk: int,
    chunk_index: int,
    text: str,
    title: str,
    heading_path: str,
) -> Chunk:
    metadata: ChunkMetadata = {
        "note_pk": note_pk,
        "title": title,
        "tags": "tag1, tag2",
        "chunk_index": chunk_index,
        "heading_path": heading_path,
        "modified_at": "2024-06-01T12:00:00+00:00",
        "source": "bear",
    }
    return Chunk(
        id=f"{note_pk}-{chunk_index}",
        text=text,
        metadata=metadata,
    )


class TestGenerateAnswer(unittest.TestCase):

    def test_no_chunks_returns_message_without_api_call(self):
        """Empty chunks list returns a 'no relevant notes' message without calling the API."""
        with patch("bear_rag.generator.anthropic.Anthropic") as mock_anthropic_cls:
            from bear_rag.generator import generate_answer

            result = generate_answer("What is the meaning of life?", [])

            mock_anthropic_cls.assert_not_called()
            self.assertIn("No relevant notes", result)

    @patch("bear_rag.generator.anthropic.Anthropic")
    def test_prompt_contains_question(self, mock_anthropic_cls):
        """The user message sent to Claude contains the original question text."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="The answer.")]
        )

        from bear_rag.generator import generate_answer

        question = "What did I write about Python?"
        chunk = _make_chunk(1, 0, "Python is great.", "My Note", "Intro")
        generate_answer(question, [chunk])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]
        self.assertIn(question, user_msg)

    @patch("bear_rag.generator.anthropic.Anthropic")
    def test_prompt_contains_chunk_text(self, mock_anthropic_cls):
        """The user message sent to Claude includes the chunk's text content."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Here is the answer.")]
        )

        from bear_rag.generator import generate_answer

        chunk_text = "Bears are fascinating creatures that hibernate in winter."
        chunk = _make_chunk(2, 0, chunk_text, "Bear Facts", "Overview")
        generate_answer("Tell me about bears.", [chunk])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]
        self.assertIn(chunk_text, user_msg)

    @patch("bear_rag.generator.anthropic.Anthropic")
    def test_prompt_contains_citation_numbers(self, mock_anthropic_cls):
        """The user message includes [1], [2] citation numbering for each chunk."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Cited answer.")]
        )

        from bear_rag.generator import generate_answer

        chunk1 = _make_chunk(1, 0, "First chunk content.", "Note One", "Section A")
        chunk2 = _make_chunk(2, 0, "Second chunk content.", "Note Two", "Section B")
        generate_answer("What do I know?", [chunk1, chunk2])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]
        self.assertIn("[1]", user_msg)
        self.assertIn("[2]", user_msg)

    @patch("bear_rag.generator.anthropic.Anthropic")
    def test_returns_claude_response_text(self, mock_anthropic_cls):
        """generate_answer returns the text from the first content block of the API response."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        expected_answer = "This is the definitive answer from Claude."
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=expected_answer)]
        )

        from bear_rag.generator import generate_answer

        chunk = _make_chunk(1, 0, "Some context text.", "A Note", "Main")
        result = generate_answer("A question?", [chunk])

        self.assertEqual(result, expected_answer)


if __name__ == "__main__":
    unittest.main()
