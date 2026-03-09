import json
import tiktoken
from pydantic import BaseModel

MODEL_PRICING = {
    "gpt-4o-mini":      {"input": 0.15,  "output": 0.60,  "tiktoken_model": "gpt-4o-mini",    "tier": "budget"},
    "gpt-3.5-turbo":    {"input": 0.50,  "output": 1.50,  "tiktoken_model": "gpt-3.5-turbo",  "tier": "budget"},
    "gpt-4o":           {"input": 2.50,  "output": 10.00, "tiktoken_model": "gpt-4o",          "tier": "standard"},
    "claude-3.5-sonnet": {"input": 3.00,  "output": 15.00, "tiktoken_model": "gpt-4o",         "tier": "standard"},
    "gemini-1.5-pro":   {"input": 1.25,  "output": 5.00,  "tiktoken_model": "gpt-4o",          "tier": "standard"},
    "gpt-4-turbo":      {"input": 10.00, "output": 30.00, "tiktoken_model": "gpt-4-turbo",     "tier": "premium"},
    "claude-3-opus":    {"input": 15.00, "output": 75.00, "tiktoken_model": "gpt-4o",          "tier": "premium"},
    "gpt-4":            {"input": 30.00, "output": 60.00, "tiktoken_model": "gpt-4",           "tier": "premium"},
}

TOLLBOOTH_COMMISSION = 0.30

class BillingDetails(BaseModel):
    tokens_original: int
    tokens_optimized: int
    tokens_saved: int
    model: str
    model_tier: str
    cost_per_million_input: float
    estimated_savings_usd: float
    tollbooth_fee_usd: float
    commission_rate: float

class TokenCounter:
    @staticmethod
    def count(tool_definition: dict, model: str = "gpt-4o-mini") -> int:
        tiktoken_model = MODEL_PRICING.get(model, {}).get("tiktoken_model", "gpt-4o-mini")
        try:
            encoder = tiktoken.encoding_for_model(tiktoken_model)
        except KeyError:
            encoder = tiktoken.get_encoding("cl100k_base")
        text = json.dumps(tool_definition, ensure_ascii=False)
        return len(encoder.encode(text))

class PricingEngine:
    @staticmethod
    def calculate(tokens_original: int, tokens_optimized: int, model: str) -> BillingDetails:
        tokens_saved = max(0, tokens_original - tokens_optimized)
        model_info = MODEL_PRICING.get(model, MODEL_PRICING["gpt-4o-mini"])
        cost_per_token = model_info["input"] / 1_000_000
        estimated_savings = tokens_saved * cost_per_token
        tollbooth_fee = estimated_savings * TOLLBOOTH_COMMISSION
        
        return BillingDetails(
            tokens_original=tokens_original,
            tokens_optimized=tokens_optimized,
            tokens_saved=tokens_saved,
            model=model,
            model_tier=model_info["tier"],
            cost_per_million_input=model_info["input"],
            estimated_savings_usd=round(estimated_savings, 8),
            tollbooth_fee_usd=round(tollbooth_fee, 8),
            commission_rate=TOLLBOOTH_COMMISSION
        )