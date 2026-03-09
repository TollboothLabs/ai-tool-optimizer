from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import json
import hashlib
import uuid

# --- IMPORTY NASZYCH MODUŁÓW ---
from tool_fixer import RadicalToolFixer
from pricing_engine import PricingEngine, TokenCounter, BillingDetails, MODEL_PRICING
from mcp_transport import router as mcp_router
from ai_fixer import AIFixer

app = FastAPI(title="AI Tool Description Optimizer", version="0.4.5-debug")
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
#  🔍 DEBUG ENDPOINTS — Diagnostyka
# =============================================================

@app.get("/debug/ai-fixer")
async def debug_ai_fixer():
    import os
    api_key = os.environ.get("OPENAI_API_KEY", "")
    return {
        "api_key_present": len(api_key) > 0,
        "api_key_length": len(api_key),
        "api_key_first_7_chars": api_key[:7] + "..." if api_key else "EMPTY",
        "api_key_valid_format": api_key.startswith("sk-") if api_key else False,
        "ai_fixer_cache_size": len(AIFixer._cache),
        "environment_keys": [
            k for k in os.environ.keys()
            if "KEY" in k.upper() or "API" in k.upper() or "OPENAI" in k.upper()
        ]
    }

@app.post("/debug/test-ai-fix")
async def debug_test_ai_fix(request: Request):
    import os
    import traceback
    body = await request.json()
    name = body.get("name", "test_tool")
    description = body.get("description", "")
    parameters = body.get("parameters", {})

    api_key = os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return {
            "ai_fixer_status": "no_api_key",
            "error_message": "OPENAI_API_KEY environment variable is empty or not set."
        }

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        test_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'OK' and nothing else."}],
            max_tokens=5
        )
        test_reply = test_response.choices[0].message.content
        ai_result = AIFixer.fix(name, description, parameters)

        if ai_result is not None:
            return {"ai_fixer_status": "success", "openai_test": f"OpenAI responds: {test_reply}", "ai_result": ai_result}
        else:
            return {"ai_fixer_status": "error", "error_type": "AIFixer returned None"}

    except openai.AuthenticationError as e:
        return {"ai_fixer_status": "error", "error_type": "AuthenticationError (401)", "error_message": str(e)}
    except openai.RateLimitError as e:
        return {"ai_fixer_status": "error", "error_type": "RateLimitError (429)", "error_message": str(e)}
    except openai.InsufficientQuotaError as e:
        return {"ai_fixer_status": "error", "error_type": "InsufficientQuotaError", "error_message": str(e)}
    except Exception as e:
        return {"ai_fixer_status": "error", "error_type": type(e).__name__, "error_message": str(e), "traceback": traceback.format_exc()}

if __name__ == "__main__":
    import uvicorn
    print("\n" + "🏰 " * 15)
    print("  TOLLBOOTH v4.5-DEBUG — AI-POWERED OPTIMIZER")
    print("  REST:  http://localhost:8000/docs")
    print("  MCP:   http://localhost:8000/sse")
    print("🏰 " * 15 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
