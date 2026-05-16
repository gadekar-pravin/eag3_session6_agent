#!/usr/bin/env bash
set -euo pipefail

uv run python agent6.py --clean "Fetch https://en.wikipedia.org/wiki/Claude_Shannon and tell me his birth date, death date, and three key contributions to information theory."

uv run python agent6.py --clean "Find 3 family-friendly things to do in Tokyo this weekend. Check Saturday's weather forecast there and tell me which one is most appropriate."

uv run python agent6.py --clean "My mom's birthday is 15 May 2026. Remember that and give me a calendar reminder for two weeks before and on the day."
uv run python agent6.py "When is mom's birthday?"

uv run python agent6.py --clean "Search for 'Python asyncio best practices', read the top 3 results, and give me a short numbered list of the advice they agree on."
