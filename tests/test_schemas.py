import pytest
from pydantic import ValidationError

from schemas import DecisionOutput, Goal, MemoryItem, Observation, ToolCall


def test_decision_output_answer_only():
    out = DecisionOutput(answer="hello", tool_call=None)
    assert out.is_answer
    assert out.answer == "hello"


def test_decision_output_tool_call_only():
    tc = ToolCall(name="web_search", arguments={"query": "x"})
    out = DecisionOutput(answer=None, tool_call=tc)
    assert not out.is_answer
    assert out.tool_call.name == "web_search"


def test_decision_output_both_raises():
    with pytest.raises(ValidationError):
        DecisionOutput(answer="hi", tool_call=ToolCall(name="web_search", arguments={}))


def test_decision_output_neither_raises():
    with pytest.raises(ValidationError):
        DecisionOutput(answer=None, tool_call=None)


def test_goal_all_attachment_ids_dedup():
    g = Goal(text="test", attach_artifact_id="art:aaa", attach_artifact_ids=["art:aaa", "art:bbb"])
    assert g.all_attachment_ids() == ["art:aaa", "art:bbb"]


def test_goal_all_attachment_ids_empty():
    g = Goal(text="test")
    assert g.all_attachment_ids() == []


def test_observation_all_done():
    obs = Observation(goals=[Goal(text="a", done=True), Goal(text="b", done=True)])
    assert obs.all_done


def test_observation_not_all_done():
    obs = Observation(goals=[Goal(text="a", done=True), Goal(text="b", done=False)])
    assert not obs.all_done


def test_observation_next_unfinished():
    g1 = Goal(text="done", done=True)
    g2 = Goal(text="pending", done=False)
    obs = Observation(goals=[g1, g2])
    assert obs.next_unfinished() == g2


def test_observation_next_unfinished_all_done():
    obs = Observation(goals=[Goal(text="a", done=True)])
    assert obs.next_unfinished() is None


def test_memory_item_confidence_bounds():
    with pytest.raises(ValidationError):
        MemoryItem(
            kind="fact", descriptor="x", source="test", run_id="r1", confidence=1.5
        )
    with pytest.raises(ValidationError):
        MemoryItem(
            kind="fact", descriptor="x", source="test", run_id="r1", confidence=-0.1
        )
