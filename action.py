from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from schemas import ActionInput, ActionOutput, Artifact, ToolCall

ARTIFACT_THRESHOLD_BYTES = 4 * 1024


class ArtifactStore:
    """Content-addressable store for large tool outputs."""

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.root = Path(state_dir) / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def _prefix(self, blob: bytes) -> str:
        return hashlib.sha256(blob).hexdigest()[:16]

    def put(
        self,
        blob: bytes,
        *,
        content_type: str = "text/plain",
        source: str,
        descriptor: str,
    ) -> str:
        aid = f"art:{self._prefix(blob)}"
        stem = aid.replace(":", "_")
        bin_path = self.root / f"{stem}.bin"
        meta_path = self.root / f"{stem}.json"
        if not bin_path.exists():
            bin_path.write_bytes(blob)
        artifact = Artifact(
            id=aid,
            content_type=content_type,
            size_bytes=len(blob),
            source=source,
            descriptor=descriptor,
        )
        meta_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return aid

    def get_bytes(self, artifact_id: str) -> bytes:
        stem = artifact_id.replace(":", "_")
        return (self.root / f"{stem}.bin").read_bytes()

    def get_text(self, artifact_id: str) -> str:
        return self.get_bytes(artifact_id).decode("utf-8", errors="replace")

    def get_meta(self, artifact_id: str) -> Artifact:
        stem = artifact_id.replace(":", "_")
        data = json.loads((self.root / f"{stem}.json").read_text(encoding="utf-8"))
        return Artifact.model_validate(data)

    def exists(self, artifact_id: str) -> bool:
        stem = artifact_id.replace(":", "_")
        return (self.root / f"{stem}.bin").exists()


def _stringify_block(block: Any) -> str:
    if hasattr(block, "text") and block.text is not None:
        return str(block.text)
    if hasattr(block, "model_dump"):
        dumped = block.model_dump()
        if "text" in dumped and dumped["text"] is not None:
            return str(dumped["text"])
        return json.dumps(dumped, ensure_ascii=False)
    if isinstance(block, dict):
        if "text" in block and block["text"] is not None:
            return str(block["text"])
        return json.dumps(block, ensure_ascii=False)
    return str(block)


def flatten_mcp_result(result: Any) -> str:
    # FastMCP normally returns content blocks, but different mcp versions also
    # expose structured_content/structuredContent. Preserve whatever is present.
    content = getattr(result, "content", None)
    if content:
        return "\n".join(_stringify_block(block) for block in content)
    for attr in ("structured_content", "structuredContent"):
        value = getattr(result, attr, None)
        if value:
            return json.dumps(value, ensure_ascii=False, indent=2)
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
    return str(result)


class Action:
    """Pure execution layer: dispatch one MCP tool call and store large outputs."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifacts = artifact_store

    async def execute(self, session: Any, action_input: ActionInput) -> ActionOutput:
        tool_call: ToolCall = action_input.tool_call

        for key, value in tool_call.arguments.items():
            if key in {"path", "url"} and isinstance(value, str) and value.startswith("art:"):
                return ActionOutput(
                    ok=False,
                    descriptor=(
                        f"Refused {tool_call.name}: artifact handle "
                        f"{value!r} is not a real path or URL. "
                        "Perception must attach artifact bytes "
                        "before Decision reads them."
                    ),
                )

        try:
            result = await session.call_tool(tool_call.name, arguments=tool_call.arguments)
            text = flatten_mcp_result(result)
        except Exception as exc:
            return ActionOutput(ok=False, descriptor=f"Tool {tool_call.name} failed: {exc}")

        blob = text.encode("utf-8", errors="replace")
        if len(blob) > ARTIFACT_THRESHOLD_BYTES:
            preview = text[:700].replace("\n", " ")
            descriptor = (
                f"[artifact produced by {tool_call.name}, "
                f"{len(blob)} bytes] preview: {preview}"
            )
            artifact_id = self.artifacts.put(
                blob,
                content_type="text/plain; charset=utf-8",
                source=tool_call.name,
                descriptor=descriptor,
            )
            artifact = self.artifacts.get_meta(artifact_id)
            return ActionOutput(
                ok=True,
                descriptor=f"[artifact {artifact_id}, {len(blob)} bytes] preview: {preview}",
                result_text="",
                artifact_id=artifact_id,
                artifact=artifact,
            )

        descriptor = text[:1000]
        return ActionOutput(ok=True, descriptor=descriptor, result_text=text)
