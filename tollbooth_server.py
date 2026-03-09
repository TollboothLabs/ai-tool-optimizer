from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import json
import hashlib
import uuid

from tool_fixer import RadicalToolFixer
from pricing_engine import PricingEngine, TokenCounter, BillingDetails, MODEL_PRICING
from mcp_transport import router as mcp_router

app = FastAPI(title="AI Tool Description Optimizer", version="0.4.0")
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

    fingerprint = hashlib.sha256(json.dumps({"n": request.tool.name, "d": request.tool.description, "p": request.tool.parameters, "l": request.optimization_level}, sort_keys=True).encode()).hexdigest()[:16]
    
    if fingerprint in CACHE:
        optimized = CACHE[fingerprint]
    else:
        optimized = RadicalToolFixer.fix(request.tool.name, request.tool.description, request.tool.parameters, request.optimization_level)
        CACHE[fingerprint] = optimized

    original_def = {"type": "function", "function": {"name": request.tool.name, "description": request.tool.description, "parameters": request.tool.parameters}}
    tokens_orig = TokenCounter.count(original_def, request.model)
    tokens_fixed = TokenCounter.count(optimized, request.model)
    billing = PricingEngine.calculate(tokens_orig, tokens_fixed, request.model)

    BILLING_LOG.append({"request_id": request_id, "tokens_saved": billing.tokens_saved, "fee_usd": billing.tollbooth_fee_usd})

    return OptimizeResponse(
        request_id=request_id,
        optimized_tool=optimized,
        billing=billing,
        message=f"Saved {billing.tokens_saved} tokens. Fee: ${billing.tollbooth_fee_usd:.6f}"
    )

if __name__ == "__main__":
    import uvicorn
    print("\n" + "🏰 " * 15)
    print("  TOLLBOOTH v4 — AI Tool Description Optimizer")
    print("  REST:  http://localhost:8000/docs")
    print("  MCP:   http://localhost:8000/sse")
    print("🏰 " * 15 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)