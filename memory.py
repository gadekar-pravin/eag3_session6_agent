from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from schemas import (
    MemoryItem,
    MemoryKind,
    MemoryOutcomeInput,
    MemoryReadInput,
    MemoryReadOutput,
    MemoryRememberInput,
    MemoryRememberOutput,
)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "give",
    "has", "have", "i", "in", "is", "it", "me", "my", "of", "on", "or", "the",
    "there", "this", "to", "we", "what", "when", "where", "which", "with", "you",
}


MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


class Memory:
    """Simple persistent JSON memory with typed reads/writes."""

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / "memory.json"
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _load(self) -> list[MemoryItem]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = []
        return [MemoryItem.model_validate(item) for item in raw]

    def _save(self, items: Iterable[MemoryItem]) -> None:
        data = [item.model_dump(mode="json") for item in items]
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _append_unique(self, new_items: list[MemoryItem]) -> list[MemoryItem]:
        if not new_items:
            return []
        items = self._load()
        existing_keys = {
            (i.kind, i.descriptor.lower(), json.dumps(i.value, sort_keys=True, default=str))
            for i in items
        }
        stored: list[MemoryItem] = []
        for item in new_items:
            key = (
                item.kind,
                item.descriptor.lower(),
                json.dumps(item.value, sort_keys=True, default=str),
            )
            if key not in existing_keys:
                items.append(item)
                stored.append(item)
                existing_keys.add(key)
        self._save(items)
        return stored

    @staticmethod
    def tokenize(text: str) -> set[str]:
        words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        return {w for w in words if len(w) > 1 and w not in STOPWORDS}

    def read(self, read_input: MemoryReadInput) -> MemoryReadOutput:
        query_tokens = self.tokenize(read_input.query)
        history_text = " ".join(
            part
            for event in read_input.history[-6:]
            for part in [event.goal_text or "", event.text or "", event.result_descriptor or ""]
        )
        query_tokens |= self.tokenize(history_text)

        candidates = self._load()
        if read_input.kinds:
            allowed = set(read_input.kinds)
            candidates = [i for i in candidates if i.kind in allowed]

        scored: list[tuple[int, MemoryItem]] = []
        for item in candidates:
            haystack = " ".join(
                item.keywords + [item.descriptor, json.dumps(item.value, default=str)]
            )
            score = len(query_tokens & self.tokenize(haystack))
            if item.artifact_id:
                # Tool outcomes with artifacts are often useful after a fetch.
                score += 1
            if score:
                scored.append((score, item))

        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return MemoryReadOutput(hits=[item for _, item in scored[: read_input.top_k]])

    def filter(
        self,
        *,
        kinds: list[MemoryKind] | None = None,
        goal_id: str | None = None,
        recent: int | None = None,
    ) -> list[MemoryItem]:
        items = self._load()
        if kinds:
            allowed = set(kinds)
            items = [i for i in items if i.kind in allowed]
        if goal_id:
            items = [i for i in items if i.goal_id == goal_id]
        items.sort(key=lambda i: i.created_at, reverse=True)
        if recent is not None:
            items = items[:recent]
        return items

    def remember(self, remember_input: MemoryRememberInput) -> MemoryRememberOutput:
        text = remember_input.raw_text.strip()
        lower = text.lower()
        stored: list[MemoryItem] = []

        birthday = self._extract_birthday_fact(text)
        if birthday:
            entity, iso_date, human_date = birthday
            stored.append(
                MemoryItem(
                    kind="fact",
                    keywords=[entity.lower(), "birthday", human_date.lower(), iso_date],
                    descriptor=f"{entity.title()}'s birthday is on {human_date}.",
                    value={
                        "entity": entity.lower(),
                        "attribute": "birthday",
                        "date": iso_date,
                        "human_date": human_date,
                    },
                    source=remember_input.source,
                    run_id=remember_input.run_id,
                    goal_id=remember_input.goal_id,
                    confidence=1.0,
                )
            )

        if "prefer" in lower or "preference" in lower:
            stored.append(
                MemoryItem(
                    kind="preference",
                    keywords=list(self.tokenize(text)),
                    descriptor=text[:180],
                    value={"raw": text},
                    source=remember_input.source,
                    run_id=remember_input.run_id,
                    goal_id=remember_input.goal_id,
                    confidence=0.7,
                )
            )

        return MemoryRememberOutput(stored=self._append_unique(stored))

    def _extract_birthday_fact(self, text: str) -> tuple[str, str, str] | None:
        # This parser is for user input, not LLM output. It intentionally handles
        # the assignment phrasing and a few nearby variants.
        pattern = re.compile(
            r"(?P<entity>mom|mother|mum|john|[A-Za-z]+)'?s?\s+birthday\s+is\s+"
            r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None
        entity = match.group("entity").lower()
        if entity in {"mother", "mum"}:
            entity = "mom"
        month_name = match.group("month").lower()
        month = MONTHS.get(month_name)
        if not month:
            return None
        day = int(match.group("day"))
        year = int(match.group("year"))
        date = datetime(year, month, day).date()
        human = f"{date.day} {date.strftime('%B %Y')}"
        return entity, date.isoformat(), human

    def record_outcome(self, outcome_input: MemoryOutcomeInput) -> MemoryItem:
        args_text = json.dumps(
            outcome_input.tool_call.arguments, ensure_ascii=False, sort_keys=True
        )
        descriptor = outcome_input.result_text[:220].replace("\n", " ")
        if outcome_input.artifact_id:
            descriptor = (
                f"{outcome_input.tool_call.name}({args_text}) "
                f"produced {outcome_input.artifact_id}."
            )
        item = MemoryItem(
            kind="tool_outcome",
            keywords=[
                outcome_input.tool_call.name,
                *self.tokenize(args_text),
                *self.tokenize(descriptor),
            ],
            descriptor=descriptor,
            value={
                "tool": outcome_input.tool_call.name,
                "arguments": outcome_input.tool_call.arguments,
            },
            artifact_id=outcome_input.artifact_id,
            source="action",
            run_id=outcome_input.run_id,
            goal_id=outcome_input.goal_id,
            confidence=1.0 if outcome_input.result_text else 0.8,
        )
        self._append_unique([item])
        return item
