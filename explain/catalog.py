"""The models explanations can be written with, by provider, and what they cost (pokerland-llm-reports.md, 6).

The player brings their own key and pays the provider; the price list only says about how much. It is the one place
to update when a provider changes its models or prices, and a model joins it only once it has been through the
evaluation set (pokerland-llm-reports.md, 10).

Prices are US dollars per million tokens, from each provider's pricing page on PRICES_AS_OF. A price can change on a
date (`until` ends a price, the next one takes over), and DeepSeek's are halved off-peak.
"""

import datetime

PRICES_AS_OF = datetime.date(2026, 10, 11)

# Each provider: what the page calls it, where a key comes from, its terms, the stop value its API gives when an
# answer is finished (explain.checks), and anything the consent notice must add (pokerland-llm-reports.md, 7).
PROVIDERS = {
    "anthropic": {
        "label": "Claude",
        "company": "Anthropic",
        "key_url": "https://platform.claude.com/settings/keys",
        "terms_url": "https://www.anthropic.com/legal/commercial-terms",
        "finished": "end_turn",
        "notice": "",
    },
    "openai": {
        "label": "OpenAI",
        "company": "OpenAI",
        "key_url": "https://platform.openai.com/api-keys",
        "terms_url": "https://openai.com/policies/",
        "finished": "completed",
        "notice": "",
    },
    "google": {
        "label": "Gemini",
        "company": "Google",
        "key_url": "https://aistudio.google.com/apikey",
        "terms_url": "https://ai.google.dev/gemini-api/terms",
        "finished": "STOP",
        "notice": (
            "Google says content sent with a free-tier Gemini key is used to improve its products; with a paid key "
            "it isn't."
        ),
    },
    "deepseek": {
        "label": "DeepSeek",
        "company": "DeepSeek",
        "key_url": "https://platform.deepseek.com/api_keys",
        "terms_url": "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html",
        "finished": "stop",
        "notice": (
            "DeepSeek's privacy policy says it stores and processes personal data in the People's Republic of China."
        ),
    },
}

PROVIDER_NAMES = {key: provider["company"] for key, provider in PROVIDERS.items()}


def _price(input_, cached, output, cache_write=None):
    return {"input": input_, "cached_input": cached, "cache_write": cache_write, "output": output}


# The models offered, each provider's default first. `effort` is how hard it thinks, as the client asks for it.
MODELS = [
    {"provider": "anthropic", "id": "claude-opus-5-5", "label": "Claude Opus 5.5", "default": True,
     "prices": [_price(4.00, 0.20, 20.00, cache_write=5.00)]},
    {"provider": "anthropic", "id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "default": False,
     "prices": [_price(2.00, 0.20, 10.00, cache_write=2.50)]},
    {"provider": "anthropic", "id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "default": False,
     "prices": [_price(0.10, 0.01, 0.50, cache_write=0.125)]},
    {"provider": "openai", "id": "gpt-6.1-sol", "label": "GPT-6.1 Sol", "default": True,
     "prices": [_price(2.00, 0.10, 10.00)]},
    {"provider": "openai", "id": "gpt-6-astra", "label": "GPT-6 Astra", "default": False,
     "prices": [_price(10.00, 1.00, 50.00)]},
    {"provider": "openai", "id": "gpt-6-luna", "label": "GPT-6 Luna", "default": False,
     "prices": [_price(0.10, 0.01, 0.50)]},
    {"provider": "google", "id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash", "default": True,
     "prices": [
         {**_price(0.75, 0.075, 3.75), "until": datetime.date(2026, 12, 31)},
         _price(1.50, 0.15, 7.50),
     ]},
    {"provider": "google", "id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (preview)", "default": False,
     "prices": [_price(2.00, 0.20, 12.00)]},
    {"provider": "google", "id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite", "default": False,
     "prices": [_price(0.30, 0.03, 2.50)]},
    {"provider": "deepseek", "id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro", "default": True,
     "prices": [_price(1.32, 0.044, 3.96)], "off_peak": True},
    {"provider": "deepseek", "id": "deepseek-flash", "label": "DeepSeek V4.1 Flash", "default": False,
     "prices": [_price(0.30, 0.006, 1.20)], "off_peak": True},
]
BY_ID = {(model["provider"], model["id"]): model for model in MODELS}

# What a typical explanation of a hand uses, for the estimate beside each model: instructions and brief in, the
# answer and the model's reasoning out (pokerland-llm-reports.md, 6).
TYPICAL = {"input": 6000, "cached_input": 0, "cache_write": 0, "output": 3000}

# DeepSeek's peak hours, UTC, on weekdays; the rest of the week is off-peak at half price. Chinese public holidays are
# off-peak too, which this doesn't know, so it can read high.
PEAK_HOURS = (range(1, 4), range(6, 10))


def offered(provider, model_id):
    """Whether a model is on the list."""
    return (provider, model_id) in BY_ID


def price_at(model, when, hourly=True):
    """The model's prices per million tokens at a moment: the first price whose `until` hasn't passed, halved
    off-peak where the provider prices by the hour (unless `hourly` is false: the peak price, an upper bound)."""
    day = when.date()
    price = next(price for price in model["prices"] if price.get("until") is None or day <= price["until"])
    if hourly and model.get("off_peak") and not peak(when):
        price = {key: value / 2 if isinstance(value, float) else value for key, value in price.items()}
    return price


def peak(when):
    """Whether a moment falls in DeepSeek's peak hours."""
    moment = when.astimezone(datetime.UTC)
    return moment.weekday() < 5 and any(moment.hour in hours for hours in PEAK_HOURS)


def cost(provider, model_id, usage, when, hourly=True):
    """About what a call cost in US dollars, from its usage: {"input", "cached_input", "cache_write", "output"} tokens,
    with `input` counting only the tokens read afresh. None for a model no longer on the list."""
    model = BY_ID.get((provider, model_id))
    if model is None:
        return None
    price = price_at(model, when, hourly)
    total = 0.0
    for kind in ("input", "cached_input", "cache_write", "output"):
        rate = price[kind] if price[kind] is not None else price["input"]
        total += (usage.get(kind) or 0) * rate
    return total / 1_000_000


def listing(now):
    """The providers and models offered, with today's prices and the cost of a typical hand, as the page shows them.
    Where the price changes by the hour, these are the peak prices, which the page says."""
    return {
        "prices_as_of": PRICES_AS_OF,
        "providers": [{"key": key, **provider} for key, provider in PROVIDERS.items()],
        "models": [
            {
                "provider": model["provider"],
                "id": model["id"],
                "label": model["label"],
                "default": model["default"],
                "input": price_at(model, now, hourly=False)["input"],
                "output": price_at(model, now, hourly=False)["output"],
                "off_peak": bool(model.get("off_peak")),
                "typical_hand": cost(model["provider"], model["id"], TYPICAL, now, hourly=False),
            }
            for model in MODELS
        ],
    }
