"""The shape of an explanation, as every provider is asked for it (pokerland-llm-reports.md, 5.4).

One JSON schema for every kind and every provider, in the subset they all accept: every field required, no
additional properties, nullable fields as ["string", "null"], enums of strings, no length limits (not every provider
takes them; the instructions state them and explain.checks enforces them). It is fixed per schema version: Anthropic
and OpenAI process a new schema on its first use, so a schema made per hand would slow every call.

A review reads top down: a headline and a short summary; what happened, part by part; each decision with the engine's
verdict; what went well; and suggestions by priority, the first being the one thing to fix. There is no score: a
model's score says as much about the model as the play, and the verdicts already count what the engine can.

DeepSeek's JSON mode guarantees valid JSON but not this shape, so its instructions carry the schema and EXAMPLE.
"""

SCHEMA_VERSION = 2

VERDICTS = ("kept", "broke", "close", "your_call", "none")
PRIORITIES = ("high", "medium", "low")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "summary", "story", "decisions", "strengths", "suggestions", "luck", "caveats"],
    "properties": {
        "headline": {"type": "string", "description": "One sentence, up to 120 characters"},
        "summary": {"type": "string", "description": "The overall assessment, two to four sentences"},
        "story": {
            "type": "array",
            "description": "What happened, a part at a time: for a hand, one entry per street",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "text"],
                "properties": {
                    "label": {"type": "string", "description": "The part: a street's name for a hand"},
                    "text": {"type": "string", "description": "Up to three sentences"},
                },
            },
        },
        "decisions": {
            "type": "array",
            "description": "One entry per decision in the brief, in its order",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "verdict", "why", "instead"],
                "properties": {
                    "ref": {"type": "string", "description": "The decision's ref in the brief"},
                    "verdict": {"type": "string", "enum": list(VERDICTS), "description": "The brief's verdict"},
                    "why": {"type": "string", "description": "A short explanation, up to three sentences"},
                    "instead": {"type": ["string", "null"], "description": "What to do instead, if anything"},
                },
            },
        },
        "strengths": {
            "type": "array",
            "description": "Up to four things the player did well, one sentence each",
            "items": {"type": "string"},
        },
        "suggestions": {
            "type": "array",
            "description": "One to four, most important first; the first is the one thing to fix",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["priority", "text", "practice"],
                "properties": {
                    "priority": {"type": "string", "enum": list(PRIORITIES)},
                    "text": {"type": "string", "description": "What to do differently, up to two sentences"},
                    "practice": {"type": ["string", "null"], "description": "One of the brief's practice_links"},
                },
            },
        },
        "luck": {"type": ["string", "null"], "description": "Luck against play, when the brief has an all-in"},
        "caveats": {
            "type": "array",
            "description": "What the explanation can't know",
            "items": {"type": "string"},
        },
    },
}

# An answer of the right shape, for the instructions of a provider whose JSON mode doesn't enforce the schema.
EXAMPLE = {
    "headline": "Calling the flop needed 20%, and two overcards had 13%",
    "summary": (
        "A routine big blind defence turned costly on the flop. The price was wrong for your draw, and the turn "
        "fold was right once you'd seen it."
    ),
    "story": [
        {"label": "preflop", "text": "The button opened to 2.5 bb and you defended your big blind with A♥ Q♦."},
        {"label": "flop", "text": "K♥ 9♦ 2♣ missed you. You checked, the button bet 1.8 bb, and you called."},
    ],
    "decisions": [
        {
            "ref": "d2",
            "verdict": "broke",
            "why": "The call needed 20%. Only an ace or a queen improves you: 6 cards, 13%.",
            "instead": "Fold. Call with one card to come only when your outs beat the price.",
        }
    ],
    "strengths": ["Checking the flop to the raiser out of position kept the playbook's default."],
    "suggestions": [
        {
            "priority": "high",
            "text": "Before calling a flop bet with a draw, count your outs and compare them with the price.",
            "practice": "rule:price_to_call",
        }
    ],
    "luck": None,
    "caveats": ["No showdown, so the button's hand is unknown."],
}
