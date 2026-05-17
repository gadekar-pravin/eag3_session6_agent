import json

import pytest

from action import ArtifactStore, _stringify_block, flatten_mcp_result
from schemas import ActionInput, ToolCall


class TestArtifactStore:
    def test_prefix_deterministic(self, tmp_state):
        store = ArtifactStore(state_dir=tmp_state)
        blob = b"hello world"
        assert store._prefix(blob) == store._prefix(blob)
        assert len(store._prefix(blob)) == 16

    def test_prefix_different_content(self, tmp_state):
        store = ArtifactStore(state_dir=tmp_state)
        assert store._prefix(b"hello") != store._prefix(b"world")

    def test_put_and_get_roundtrip(self, tmp_state):
        store = ArtifactStore(state_dir=tmp_state)
        blob = b"test content here"
        aid = store.put(blob, source="test", descriptor="desc")
        assert store.get_bytes(aid) == blob

    def test_put_dedup_same_content(self, tmp_state):
        store = ArtifactStore(state_dir=tmp_state)
        blob = b"same content"
        aid1 = store.put(blob, source="test", descriptor="first")
        aid2 = store.put(blob, source="test", descriptor="second")
        assert aid1 == aid2

    def test_put_creates_metadata(self, tmp_state):
        store = ArtifactStore(state_dir=tmp_state)
        blob = b"metadata test"
        aid = store.put(blob, content_type="text/html", source="fetch", descriptor="a page")
        meta = store.get_meta(aid)
        assert meta.id == aid
        assert meta.content_type == "text/html"
        assert meta.size_bytes == len(blob)
        assert meta.source == "fetch"


class TestStringifyBlock:
    def test_text_attr(self):
        class Block:
            text = "hello from attr"

        assert _stringify_block(Block()) == "hello from attr"

    def test_dict_text(self):
        assert _stringify_block({"text": "hello"}) == "hello"

    def test_plain(self):
        assert _stringify_block(42) == "42"

    def test_dict_no_text(self):
        result = _stringify_block({"key": "val"})
        assert json.loads(result) == {"key": "val"}


class TestFlattenMcpResult:
    def test_content_blocks(self):
        class Block:
            text = "line1"

        class Block2:
            text = "line2"

        class Result:
            content = [Block(), Block2()]

        assert flatten_mcp_result(Result()) == "line1\nline2"

    def test_no_content_fallback(self):
        class Result:
            content = None

            def model_dump(self):
                return {"data": 123}

        result = flatten_mcp_result(Result())
        assert json.loads(result) == {"data": 123}


class TestArtifactHandleRejection:
    @pytest.mark.asyncio
    async def test_rejects_artifact_url(self, tmp_state):
        from action import Action

        store = ArtifactStore(state_dir=tmp_state)
        action = Action(store)
        inp = ActionInput(tool_call=ToolCall(name="fetch_url", arguments={"url": "art:abc123"}))
        out = await action.execute(None, inp)
        assert out.ok is False
        assert "artifact handle" in out.descriptor
