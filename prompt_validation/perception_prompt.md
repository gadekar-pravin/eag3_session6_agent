# Perception Prompt

Perception is backed by Gemini Flash-Lite structured output.

Responsibilities:
1. Convert `PerceptionInput` JSON into `PerceptionOutput` JSON only.
2. If no prior goals exist, decompose the user query into bounded, ordered goals.
3. Preserve goal IDs, text, and order when prior goals already exist.
4. Mark goals done only from successful history evidence or durable memory hits.
5. Attach existing artifact IDs only to the first unfinished extraction, choice, or synthesis goal that needs raw bytes.

Validation contract: `PerceptionInput -> PerceptionOutput`, where `PerceptionOutput.observation.goals` is a list of typed `Goal` objects.
