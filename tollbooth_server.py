from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import json
import hashlib
import uuid
import os
import traceback

# --- IMPORTY NASZYCH MODUŁÓW ---
from tool_fixer import RadicalToolFixer
from pricing_engine import PricingEngine, TokenCounter, BillingDetails, MODEL_PRICING
from mcp_transport import router as mcp_router
from ai_fixer import AIFixer

app = FastAPI(title="AI Tool Description Optimizer", version="0.4.6-bulletproof")
app.include_router(mcp_router)

CACHE = {}
BILLING_LOG = []

class ToolInput(BaseModel):
    name: str
    description: str
    parameters: dict = Field(default_factory=dict)

class OptimizeRequest(BaseModel):
    tool: ToolInput
    model: str = "gpt-4o-mini"
    optimization_level: str = "radical"
    request_id: Optional[str] = None

class OptimizeResponse(BaseModel):
    request_id: str
    optimized_tool: dict
    billing: BillingDetails
    message: str

@app.post("/optimize", response_model=OptimizeResponse)
async def optimize_tool(request: OptimizeRequest):
    request_id = request.request_id or str(uuid.uuid4())
    if request.model not in MODEL_PRICING:
        raise HTTPException(status_code=400, detail="unsupported_model")

    fingerprint = hashlib.sha256(json.dumps({
        "n": request.tool.name, 
        "d": request.tool.description, 
        "p": request.tool.parameters, 
        "l": request.optimization_level
    }, sort_keys=True).encode()).hexdigest()[:16]
    
    if fingerprint in CACHE:
        optimized = CACHE[fingerprint]
    else:
        optimized = AIFixer.fix(
            request.tool.name, 
            request.tool.description, 
            request.tool.parameters
        )
        
        if optimized is None:
            optimized = RadicalToolFixer.fix(
                request.tool.name, 
                request.tool.description, 
                request.tool.parameters, 
                request.optimization_level
            )
        
        CACHE[fingerprint] = optimized

    original_def = {
        "type": "function", 
        "function": {
            "name": request.tool.name, 
            "description": request.tool.description, 
            "parameters": request.tool.parameters
        }
    }
    
    tokens_orig = TokenCounter.count(original_def, request.model)
    tokens_fixed = TokenCounter.count(optimized, request.model)
    billing = PricingEngine.calculate(tokens_orig, tokens_fixed, request.model)

    BILLING_LOG.append({
        "request_id": request_id, 
        "tokens_saved": billing.tokens_saved, 
        "fee_usd": billing.tollbooth_fee_usd
    })

    return OptimizeResponse(
        request_id=request_id,
        optimized_tool=optimized,
        billing=billing,
        message=f"Saved {billing.tokens_saved} tokens. Fee: ${billing.tollbooth_fee_usd:.6f}"
    )

# =============================================================
#  🔍 NOWY ENDPOINT TESTOWY DLA AI
# =============================================================

@app.get("/test-ai-fixer")
async def test_ai_fixer():
    """Testuje AI Fixer z prostym przykładem bez uzywania czarnych okienek."""
    test_name = "do_stuff"
    test_desc = (
        "this does stuff with weather. pass it params and "
        "it returns data. use it when needed i guess. "
        "its for weather or something like that, could also "
        "maybe do forecasts? idk just try it."
    )
    test_params = {
        "type": "object",
        "properties": {
            "thing1": {
                "type": "string",
                "description": "put something here, probably a place name or coords or whatever"
            },
            "thing2": {
                "type": "string",
                "description": "optional maybe? some kind of format idk"
            }
        },
        "required": ["thing1"]
    }

    # Wyczyść cache żeby wymusić świeży AI call
    AIFixer.clear_cache()
    result = AIFixer.fix(test_name, test_desc, test_params)

    if result is not None:
        original_def = {
            "type": "function",
            "function": {
                "name": test_name,
                "description": test_desc,
                "parameters": test_params
            }
        }
        from pricing_engine import TokenCounter
        tokens_orig = TokenCounter.count(original_def, "gpt-4o-mini")
        tokens_fixed = TokenCounter.count(result, "gpt-4o-mini")
        reduction = (
            (tokens_orig - tokens_fixed) / tokens_orig * 100
            if tokens_orig > 0 else 0
        )

        return {
            "status": "success",
            "ai_fixer": "working",
            "original_tokens": tokens_orig,
            "optimized_tokens": tokens_fixed,
            "tokens_saved": tokens_orig - tokens_fixed,
            "reduction_pct": f"{reduction:.1f}%",
            "optimized_tool": result
        }
    else:
        return {
            "status": "error",
            "ai_fixer": "failed",
            "message": "AIFixer returned None. Code could not parse OpenAI response."
        }

if __name__ == "__main__":
    import uvicorn
    print("\n" + "🏰 " * 15)
    print("  TOLLBOOTH v4.6-BULLETPROOF — AI-POWERED OPTIMIZER")
    print("  REST:  http://localhost:8000/docs")
    print("  MCP:   http://localhost:8000/sse")
    print("🏰 " * 15 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
