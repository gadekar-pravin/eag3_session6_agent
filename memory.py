from __future__ import annotations

import json
import re
from datetime import date, timedelta
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

FAMILY_ALIASES = {
    "mother": "mom",
    "mum": "mom",
    "mom": "mom",
    "father": "dad",
    "dad": "dad",
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
            entity, birthday_date, human_date = birthday
            reminders = self._extract_birthday_reminders(text, birthday_date)
            reminder_keywords = [
                date_token
                for reminder in reminders
                for date_token in (reminder["date"], reminder["human_date"].lower())
            ]
            stored.append(
                MemoryItem(
                    kind="fact",
                    keywords=[
                        entity.lower(),
                        "birthday",
                        human_date.lower(),
                        birthday_date.isoformat(),
                        *reminder_keywords,
                    ],
                    descriptor=f"{entity.title()}'s birthday is on {human_date}.",
                    value={
                        "entity": entity.lower(),
                        "attribute": "birthday",
                        "date": birthday_date.isoformat(),
                        "human_date": human_date,
                        "reminders": reminders,
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

    def _extract_birthday_fact(self, text: str) -> tuple[str, date, str] | None:
        entity_pattern = r"(?:my\s+)?(?P<entity>[A-Za-z][A-Za-z _-]{0,60}?)'?s?"
        day_month_year = (
            r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})"
        )
        month_day_year = (
            r"(?P<month2>[A-Za-z]+)\s+"
            r"(?P<day2>\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+"
            r"(?P<year2>\d{4})"
        )
        iso_year_month_day = r"(?P<iso_year>\d{4})-(?P<iso_month>\d{1,2})-(?P<iso_day>\d{1,2})"
        pattern = re.compile(
            rf"{entity_pattern}\s+birthday\s+is\s+(?:on\s+)?"
            rf"(?:{day_month_year}|{month_day_year}|{iso_year_month_day})",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None

        entity = self._normalize_entity(match.group("entity"))
        parsed_date = self._date_from_match(match)
        if parsed_date is None:
            return None

        human = self._human_date(parsed_date)
        return entity, parsed_date, human

    def _date_from_match(self, match: re.Match[str]) -> date | None:
        try:
            if match.group("iso_year"):
                return date(
                    int(match.group("iso_year")),
                    int(match.group("iso_month")),
                    int(match.group("iso_day")),
                )

            if match.group("month"):
                month = MONTHS.get(match.group("month").lower())
                if not month:
                    return None
                return date(int(match.group("year")), month, int(match.group("day")))

            month = MONTHS.get(match.group("month2").lower())
            if not month:
                return None
            return date(int(match.group("year2")), month, int(match.group("day2")))
        except ValueError:
            return None

    def _extract_birthday_reminders(
        self,
        text: str,
        birthday_date: date,
    ) -> list[dict[str, object]]:
        lower = text.lower()
        if "reminder" not in lower and "calendar" not in lower:
            return []

        reminders: list[dict[str, object]] = []
        if re.search(r"\b(?:two|2)\s+weeks?\s+before\b", lower):
            reminders.append(
                self._reminder_value(
                    "two_weeks_before",
                    birthday_date - timedelta(days=14),
                    birthday_date,
                    -14,
                )
            )
        if re.search(r"\b(?:one|1)\s+weeks?\s+before\b", lower):
            reminders.append(
                self._reminder_value(
                    "one_week_before",
                    birthday_date - timedelta(days=7),
                    birthday_date,
                    -7,
                )
            )
        if re.search(r"\b(?:on\s+the\s+day|day\s+of|same\s+day|on\s+birthday)\b", lower):
            reminders.append(self._reminder_value("on_day", birthday_date, birthday_date, 0))
        return reminders

    def _reminder_value(
        self,
        label: str,
        reminder_date: date,
        event_date: date,
        offset_days: int,
    ) -> dict[str, object]:
        return {
            "label": label,
            "date": reminder_date.isoformat(),
            "human_date": self._human_date(reminder_date),
            "event_date": event_date.isoformat(),
            "event_human_date": self._human_date(event_date),
            "offset_days": offset_days,
        }

    @staticmethod
    def _normalize_entity(entity: str) -> str:
        clean = re.sub(r"\s+", " ", entity.strip().lower().replace("_", " ").replace("-", " "))
        clean = clean.removeprefix("my ")
        return FAMILY_ALIASES.get(clean, clean)

    @staticmethod
    def _human_date(value: date) -> str:
        return f"{value.day} {value.strftime('%B %Y')}"

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
