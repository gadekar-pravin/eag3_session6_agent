from decision import _extract_fallback_url, _is_fetch_goal
from schemas import DecisionInput, Goal, HistoryEvent, MemoryItem


class TestIsFetchGoal:
    def test_imperative(self):
        assert _is_fetch_goal("Fetch the top result") is True

    def test_read_url(self):
        assert _is_fetch_goal("Read the URL from result #1") is True

    def test_fetched_past_tense(self):
        assert _is_fetch_goal("Extract from fetched page") is False

    def test_unrelated(self):
        assert _is_fetch_goal("Search for python tutorials") is False

    def test_get_page(self):
        assert _is_fetch_goal("Get the webpage content") is True

    def test_fetching_present_tense(self):
        assert _is_fetch_goal("Fetching the article now") is True


class TestExtractFallbackUrl:
    def test_from_history(self):
        di = DecisionInput(
            query="test",
            goal=Goal(text="Fetch it"),
            history=[
                HistoryEvent(
                    iter=1,
                    kind="action",
                    tool="web_search",
                    result_text='Found: https://example.com/page1 is the top result',
                )
            ],
        )
        assert _extract_fallback_url(di) == "https://example.com/page1"

    def test_from_hits(self):
        di = DecisionInput(
            query="test",
            goal=Goal(text="Fetch it"),
            hits=[
                MemoryItem(
                    kind="tool_outcome",
                    descriptor="search result",
                    value={"url": "https://example.com/hit1"},
                    source="action",
                    run_id="r1",
                )
            ],
        )
        assert _extract_fallback_url(di) == "https://example.com/hit1"

    def test_none_when_no_urls(self):
        di = DecisionInput(
            query="test",
            goal=Goal(text="Fetch it"),
            history=[HistoryEvent(iter=1, kind="action", tool="web_search", result_text="no urls")],
        )
        assert _extract_fallback_url(di) is None
