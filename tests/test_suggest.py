import pytest

from troetochie_mcp.server import _parse_variants


VARIANT = 'event: variant.done\ndata: {"index":0,"text":"Hello"}\n\n'
DONE = 'event: done\ndata: {}\n\n'


def test_complete_stream_returns_variants():
    assert _parse_variants((VARIANT + DONE).replace('\n', '\r\n')) == ["Hello"]


@pytest.mark.parametrize("stream", [
    "", VARIANT, DONE,
    'event: error\ndata: {"code":"llm"}\n\n',
    VARIANT + 'event: error\ndata: {"code":"llm"}\n\n',
    'event: variant.done\ndata: not-json\n\n' + DONE,
    'event: variant.done\ndata: {"index":-1,"text":"Bad"}\n\n' + DONE,
])
def test_failure_or_partial_stream_cannot_be_reported_as_success(stream):
    with pytest.raises(RuntimeError):
        _parse_variants(stream)
