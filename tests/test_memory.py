from memory import Memory
from schemas import MemoryRememberInput


class TestTokenize:
    def test_basic(self):
        assert Memory.tokenize("Hello World") == {"hello", "world"}

    def test_stopwords_removed(self):
        result = Memory.tokenize("I am the best")
        assert "best" in result
        assert "the" not in result
        # "i" is a stopword but also len==1, "am" is NOT in STOPWORDS
        assert "am" in result

    def test_short_words_removed(self):
        result = Memory.tokenize("a b cd ef")
        assert result == {"cd", "ef"}


class TestNormalizeEntity:
    def test_mother(self):
        assert Memory._normalize_entity("Mother") == "mom"

    def test_mum(self):
        assert Memory._normalize_entity("My Mum") == "mom"

    def test_father(self):
        assert Memory._normalize_entity("Father") == "dad"

    def test_no_alias(self):
        assert Memory._normalize_entity("John") == "john"


class TestBirthdayExtraction:
    def test_dmy(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text="Mom's birthday is 15 March 1990",
            source="test",
            run_id="r1",
        )
        out = mem.remember(inp)
        assert len(out.stored) == 1
        item = out.stored[0]
        assert item.value["entity"] == "mom"
        assert item.value["date"] == "1990-03-15"

    def test_mdy(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text="Dad's birthday is March 15, 1990",
            source="test",
            run_id="r1",
        )
        out = mem.remember(inp)
        assert len(out.stored) == 1
        assert out.stored[0].value["date"] == "1990-03-15"
        assert out.stored[0].value["entity"] == "dad"

    def test_iso(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text="John's birthday is 1990-03-15",
            source="test",
            run_id="r1",
        )
        out = mem.remember(inp)
        assert len(out.stored) == 1
        assert out.stored[0].value["date"] == "1990-03-15"
        assert out.stored[0].value["entity"] == "john"

    def test_no_match(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text="It's sunny today",
            source="test",
            run_id="r1",
        )
        out = mem.remember(inp)
        assert out.stored == []


class TestReminders:
    def test_two_weeks(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text="Mom's birthday is 15 March 1990. Set a reminder two weeks before.",
            source="test",
            run_id="r1",
        )
        out = mem.remember(inp)
        reminders = out.stored[0].value["reminders"]
        assert len(reminders) == 1
        assert reminders[0]["label"] == "two_weeks_before"

    def test_all_reminders(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text=(
                "Mom's birthday is 15 March 1990. "
                "Set a reminder two weeks before, one week before, and on the day."
            ),
            source="test",
            run_id="r1",
        )
        out = mem.remember(inp)
        reminders = out.stored[0].value["reminders"]
        assert len(reminders) == 3
        labels = [r["label"] for r in reminders]
        assert "two_weeks_before" in labels
        assert "one_week_before" in labels
        assert "on_day" in labels

    def test_no_reminder_keyword(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text="Mom's birthday is 15 March 1990",
            source="test",
            run_id="r1",
        )
        out = mem.remember(inp)
        assert out.stored[0].value["reminders"] == []


class TestDeduplication:
    def test_append_unique_skips_duplicate(self, tmp_state):
        mem = Memory(state_dir=tmp_state)
        inp = MemoryRememberInput(
            raw_text="Mom's birthday is 15 March 1990",
            source="test",
            run_id="r1",
        )
        out1 = mem.remember(inp)
        out2 = mem.remember(inp)
        assert len(out1.stored) == 1
        assert len(out2.stored) == 0  # duplicate skipped
