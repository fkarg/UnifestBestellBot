from unifestbestellbot.bot.common import split_message


def test_split_message_prefers_sentence_boundary_over_hard_split():
    text = "First sentence. Second sentence is deliberately longer."

    chunks = split_message(text, limit=30)

    assert chunks == ["First sentence. ", "Second sentence is ", "deliberately longer."]


def test_split_message_prefers_word_boundary_when_no_sentence_fits():
    text = "one two three four"

    chunks = split_message(text, limit=10)

    assert chunks == ["one two ", "three four"]


def test_split_message_keeps_each_markdown_fence_balanced():
    text = "```\n" + "x" * 30 + "\n```"

    chunks = split_message(text, limit=20)

    assert len(chunks) > 1
    assert all(len(chunk) <= 20 for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
