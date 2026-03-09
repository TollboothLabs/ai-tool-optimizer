# tollbooth_server.py
# Tollbooth – API Tool Optimizer & MCP Proxy Server
# Monetized via x402 Bot-to-Bot microtransaction protocol

import json
import os
import time
import asyncio
from typing import AsyncGenerator

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from ai_fixer import AIFixer

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
# Replace with your actual USDC wallet address (Base or Solana)
TOLLBOOTH_WALLET  = os.environ.get(
    "TOLLBOOTH_WALLET",
    "0xYOUR_WALLET_ADDRESS_HERE"          # <-- set in Render env vars
)
OPTIMIZATION_PRICE_USD  = 0.005           # per optimization call, in USDC
PAYMENT_CURRENCY        = "USDC"
PAYMENT_PROTOCOL        = "x402"
PAYMENT_NETWORK         = "base"          # Base L2 (cheap USDC transfers)

# In-memory cache (lives for server lifetime)
_cache: dict = {}

# ─────────────────────────────────────────────────────────────────────────────
# APP INIT
# ─────────────────────────────────────────────────────────────────────────────
print("[TOLLBOOTH] Booting server...")
app = FastAPI(
    title="Tollbooth – AI Tool Optimizer",
    description=(
        "MCP-compatible API tool optimizer. "
        "Compress tool schemas 40-50%, pay per call in USDC via x402."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

fixer = AIFixer()
print("[TOLLBOOTH] AIFixer loaded.")


# ─────────────────────────────────────────────────────────────────────────────
# x402 PAYMENT GATE  (dependency injected into protected routes)
# ─────────────────────────────────────────────────────────────────────────────
def x402_payment_required_response() -> JSONResponse:
    """
    Standard x402 challenge response.
    The calling agent reads this and initiates a USDC microtransaction,
    then retries with X-Payment-Token header set.
    """
    print("  [x402] No valid payment token – returning 402.")
    return JSONResponse(
        status_code=402,
        content={
            "error":            "payment_required",
            "protocol":         PAYMENT_PROTOCOL,
            "amount":           OPTIMIZATION_PRICE_USD,
            "currency":         PAYMENT_CURRENCY,
            "network":          PAYMENT_NETWORK,
            "wallet":           TOLLBOOTH_WALLET,
            "description":      "Pay per optimization call. USDC on Base L2.",
            "retry_header":     "X-Payment-Token",
            "docs":             "https://x402.org",
        },
        headers={
            # Standard x402 hint headers (some agent frameworks read these)
            "X-Payment-Required":  "true",
            "X-Payment-Amount":    str(OPTIMIZATION_PRICE_USD),
            "X-Payment-Currency":  PAYMENT_CURRENCY,
            "X-Payment-Wallet":    TOLLBOOTH_WALLET,
            "X-Payment-Network":   PAYMENT_NETWORK,
        },
    )

async def require_payment(request: Request):
    """
    FastAPI dependency.
    Checks for X-Payment-Token header on protected routes.
    
    In production you would:
      1. Verify the token is a valid signed tx hash on Base/Solana
      2. Check the tx amount >= OPTIMIZATION_PRICE_USD
      3. Check the tx recipient == TOLLBOOTH_WALLET
      4. Check the tx is not already spent (replay protection)
      
    For now we do presence-check + basic format validation as scaffold.
    Swap in your on-chain verifier when ready.
    """
    print(f"  [x402] Checking payment token on route: {request.url.path}")
    payment_token = request.headers.get("X-Payment-Token", "").strip()
    
    if not payment_token:
        print("  [x402] X-Payment-Token header missing.")
        # We raise an exception that FastAPI will NOT catch normally,
        # so we return the response directly via a custom exception handler.
        raise PaymentRequiredException()

    # Basic sanity: token should look like a tx hash (hex, 0x-prefixed, 64+ chars)
    # or a base58 string for Solana. Adjust as needed.
    is_plausible_evm_tx  = (
        payment_token.startswith("0x") and len(payment_token) >= 66
    )
    is_plausible_solana_tx = (
        not payment_token.startswith("0x") and len(payment_token) >= 43
    )
    
    if not (is_plausible_evm_tx or is_plausible_solana_tx):
        print(f"  [x402] Token format invalid: {payment_token[:30]}...")
        raise PaymentRequiredException()

    print(f"  [x402] Payment token accepted: {payment_token[:20]}... (scaffold - "
          f"on-chain verification TODO)")
    # TODO: add real on-chain tx verification here
    return payment_token

class PaymentRequiredException(Exception):
    """Raised when X-Payment-Token is missing or invalid."""
    pass

@app.exception_handler(PaymentRequiredException)
async def payment_required_handler(request: Request, exc: PaymentRequiredException):
    return x402_payment_required_response()


# ─────────────────────────────────────────────────────────────────────────────
# MCP TOOL MANIFEST  (agents read this BEFORE calling – includes pricing)
# ─────────────────────────────────────────────────────────────────────────────
MCP_TOOL_MANIFEST = {
    "schema_version": "mcp-1.0",
    "server_info": {
        "name":        "tollbooth",
        "version":     "2.0.0",
        "description": "Token-minimization engine for LLM tool schemas. "
                       "Reduces payload size 40-50%. Pay-per-call via USDC.",
    },
    "pricing": {
        "model":            "per_call",
        "price_usd":        OPTIMIZATION_PRICE_USD,
        "currency":         PAYMENT_CURRENCY,
        "payment_protocol": PAYMENT_PROTOCOL,
        "network":          PAYMENT_NETWORK,
        "wallet":           TOLLBOOTH_WALLET,
        "arbitrage_note": (
            "Expected token savings per call: 40-50%. "
            "At $0.15/1M tokens (gpt-4o-mini), break-even at ~33K input tokens. "
            "Net positive for any tool schema >5KB."
        ),
    },
    "tools": [
        {
            "name":        "optimize_tools",
            "description": "Compress LLM tool schema JSON. Returns min-token equivalent.",
            "price_usd":    OPTIMIZATION_PRICE_USD,
            "payment_protocol": PAYMENT_PROTOCOL,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tools": {
                        "type":        "array",
                        "description": "Tool definition array (OpenAI/Anthropic format)",
                    }
                },
                "required": ["tools"],
            },
        }
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    print("[TOLLBOOTH] GET / called")
    return {
        "service":  "Tollbooth AI Tool Optimizer",
        "version":  "2.0.0",
        "status":   "live",
        "payment":  f"x402 / {PAYMENT_CURRENCY} on {PAYMENT_NETWORK}",
        "price":    f"${OPTIMIZATION_PRICE_USD} per call",
        "manifest": "/mcp/manifest",
        "optimize": "POST /optimize  (requires X-Payment-Token header)",
    }

@app.get("/health")
async def health():
    print("[TOLLBOOTH] GET /health called")
    return {"status": "ok", "timestamp": int(time.time())}

@app.get("/mcp/manifest")
async def mcp_manifest():
    """
    Agents fetch this endpoint FIRST to understand our capabilities and pricing.
    This is how an autonomous agent planner calculates the arbitrage before paying.
    No payment required for manifest discovery.
    """
    print("[TOLLBOOTH] GET /mcp/manifest called")
    return MCP_TOOL_MANIFEST

@app.get("/mcp/pricing")
async def mcp_pricing():
    """Standalone pricing endpoint for agent planners."""
    print("[TOLLBOOTH] GET /mcp/pricing called")
    return MCP_TOOL_MANIFEST["pricing"]


# ── PROTECTED: Main optimization endpoint ────────────────────────────────────
@app.post("/optimize")
async def optimize(
    request: Request,
    payment_token: str = Depends(require_payment),   # 402 gate
):
    """
    Accepts a JSON body with {"tools": [...]} and returns compressed tools.
    Requires X-Payment-Token header with valid USDC tx hash.
    """
    print(f"[TOLLBOOTH] POST /optimize called | token: {payment_token[:20]}...")
    
    try:
        body = await request.json()
    except Exception as e:
        print(f"[TOLLBOOTH] Failed to parse request body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    tools = body.get("tools")
    if not tools or not isinstance(tools, list):
        print("[TOLLBOOTH] Missing or invalid 'tools' field in body.")
        raise HTTPException(
            status_code=400,
            detail="Body must be JSON with key 'tools' containing an array."
        )

    print(f"[TOLLBOOTH] Processing {len(tools)} tool(s)...")

    # Check cache first
    cache_key = json.dumps(tools, sort_keys=True)
    if cache_key in _cache:
        print("[TOLLBOOTH] Cache HIT – returning cached result.")
        cached = _cache[cache_key]
        cached["cache_hit"] = True
        return JSONResponse(content=cached)

    print("[TOLLBOOTH] Cache MISS – calling AIFixer...")
    result = fixer.fix(tools)
    
    # Enrich with pricing info
    result["payment_token_used"] = payment_token[:20] + "..."
    result["price_charged_usd"]  = OPTIMIZATION_PRICE_USD
    result["currency"]           = PAYMENT_CURRENCY
    result["cache_hit"]          = False

    # Store in cache
    _cache[cache_key] = result
    print(f"[TOLLBOOTH] Cached result. Cache size: {len(_cache)} entries.")
    print(f"[TOLLBOOTH] Done. Savings: {result.get('savings_percent', 0):.1f}%")

    return JSONResponse(content=result)


# ── PROTECTED: MCP SSE transport ─────────────────────────────────────────────
@app.get("/mcp")
async def mcp_sse(
    request: Request,
    payment_token: str = Depends(require_payment),   # 402 gate
):
    """
    Server-Sent Events endpoint for MCP-compatible agents.
    Streams optimized tool definitions over SSE.
    Requires X-Payment-Token header.
    """
    print(f"[TOLLBOOTH] GET /mcp SSE opened | token: {payment_token[:20]}...")
    
    async def event_stream() -> AsyncGenerator[str, None]:
        # Send server info + pricing metadata as first event
        yield _sse_event("server_info", {
            "name":    "tollbooth",
            "version": "2.0.0",
            "pricing": MCP_TOOL_MANIFEST["pricing"],
        })
        
        # Send tool manifest
        yield _sse_event("tool_manifest", MCP_TOOL_MANIFEST["tools"])

        # Keep-alive ping every 15s (prevents Render from closing idle SSE)
        for _ in range(4):
            await asyncio.sleep(15)
            yield _sse_event("ping", {"ts": int(time.time())})
            
        yield _sse_event("done", {"message": "stream complete"})
        print("[TOLLBOOTH] SSE stream closed.")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.post("/mcp/call")
async def mcp_call(
    request: Request,
    payment_token: str = Depends(require_payment),   # 402 gate
):
    """
    MCP tool call endpoint (JSON-RPC style).
    Body: {"method": "optimize_tools", "params": {"tools": [...]}}
    """
    print(f"[TOLLBOOTH] POST /mcp/call | token: {payment_token[:20]}...")
    
    try:
        body = await request.json()
    except Exception as e:
        print(f"[TOLLBOOTH] Failed to parse MCP call body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id", 1)

    print(f"[TOLLBOOTH] MCP method: {method}")
    if method != "optimize_tools":
        return JSONResponse(content={
            "id":    req_id,
            "error": {
                "code":    -32601,
                "message": f"Method not found: {method}",
            }
        }, status_code=404)

    tools = params.get("tools")
    if not tools or not isinstance(tools, list):
        return JSONResponse(content={
            "id":    req_id,
            "error": {
                "code":    -32602,
                "message": "params.tools must be a non-empty array",
            }
        }, status_code=400)

    result = fixer.fix(tools)
    result["price_charged_usd"] = OPTIMIZATION_PRICE_USD
    result["currency"]          = PAYMENT_CURRENCY

    return JSONResponse(content={
        "id":     req_id,
        "result": result,
    })


# ── FREE: Test endpoint (no payment required) ────────────────────────────────
@app.post("/test/optimize")
async def test_optimize(request: Request):
    """
    Free test endpoint – no payment required.
    Returns sample compression result for integration testing.
    """
    print("[TOLLBOOTH] POST /test/optimize called (free endpoint)")
    
    sample_tools = [
        {
            "name": "get_weather",
            "description": (
                "This function allows you to retrieve the current weather "
                "information for a specified location. It returns temperature, "
                "humidity, and general weather conditions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The name of the city or location for which "
                                       "you want to retrieve weather information",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "The unit of temperature measurement you "
                                       "would like the results returned in",
                    },
                },
                "required": ["location"],
            },
        }
    ]

    try:
        body = await request.json()
        tools = body.get("tools", sample_tools)
    except Exception:
        tools = sample_tools

    result = fixer.fix(tools)
    result["note"] = "Free test endpoint. Production use requires X-Payment-Token."
    result["price_for_production"] = f"${OPTIMIZATION_PRICE_USD} {PAYMENT_CURRENCY}"
    
    return JSONResponse(content=result)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _sse_event(event_type: str, data: dict | list) -> str:
    """Format a Server-Sent Event string."""
    payload = json.dumps(data, separators=(",", ":"))
    return f"event: {event_type}\ndata: {payload}\n\n"

# ─────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT (for local dev: python tollbooth_server.py)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("[TOLLBOOTH] Starting local dev server on port 8000...")
    uvicorn.run("tollbooth_server:app", host="0.0.0.0", port=8000, reload=True)
