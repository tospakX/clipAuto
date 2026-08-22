import pytest

from clipauto.models import InvalidURLs, parse_youtube_urls


def test_parses_mixed_whitespace_and_removes_exact_duplicates():
    text = """https://youtu.be/abc123\n https://www.youtube.com/watch?v=xyz_789,
    https://youtu.be/abc123"""

    assert parse_youtube_urls(text) == [
        "https://youtu.be/abc123",
        "https://www.youtube.com/watch?v=xyz_789",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtube.com/shorts/abc123",
        "https://youtu.be/abc123?t=4",
        "https://m.youtube.com/live/abc123",
    ],
)
def test_accepts_supported_youtube_hosts(url):
    assert parse_youtube_urls(url) == [url]


def test_rejects_non_youtube_and_malformed_entries_together():
    with pytest.raises(InvalidURLs) as error:
        parse_youtube_urls("https://example.com/video not-a-url")

    assert error.value.invalid == ["https://example.com/video", "not-a-url"]


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/",
        "https://youtube.com/watch",
        "https://youtube.com/channel/example",
        "https://youtu.be/",
    ],
)
def test_rejects_youtube_pages_that_do_not_identify_a_video(url):
    with pytest.raises(InvalidURLs):
        parse_youtube_urls(url)


def test_rejects_empty_input():
    with pytest.raises(InvalidURLs, match="No YouTube URLs"):
        parse_youtube_urls(" \n,  ")


def test_rejects_more_than_configured_batch_limit():
    urls = "\n".join(f"https://youtu.be/video{i}" for i in range(201))

    with pytest.raises(InvalidURLs, match="at most 200"):
        parse_youtube_urls(urls, max_urls=200)
