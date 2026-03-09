from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
import json
import uuid
import asyncio

router = APIRouter()
SESSIONS = {}

@router.get("/sse")
async def sse_connect(request: Request):
    session_id = str(uuid.uuid4())
    message_queue = asyncio.Queue()
    SESSIONS[session_id] = {"queue": message_queue, "created": True}
    print(f"  📡 SSE: Nowa sesja {session_id[:8]}...")
    
    async def event_generator():
        try:
            yield {"event": "endpoint", "data": f"/mcp/messages?session_id={session_id}"}
            while True:
                if await request.is_disconnected(): break
                try:
                    message = await asyncio.wait_for(message_queue.get(), timeout=30.0)
                    yield {"event": "message", "data": json.dumps(message)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "keepalive"}
        finally:
            SESSIONS.pop(session_id, None)
            print(f"  📡 SSE: Sesja {session_id[:8]} zakończona.")
            
    return EventSourceResponse(event_generator())

@router.post("/mcp/messages")
async def handle_mcp_message(request: Request, session_id: str):
    if session_id not in SESSIONS:
        return {"error": "Invalid session. Connect to /sse first."}
    body = await request.json()
    method = body.get("method", "")
    msg_id = body.get("id", 1)
    params = body.get("params", {})
    queue = SESSIONS[session_id]["queue"]
    
    if method == "initialize":
        response = {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tollbooth-optimizer", "version": "0.4.0"}
            }
        }
        await queue.put(response)
        return {"status": "ok"}
        
    if method == "notifications/initialized":
        return {"status": "ok"}
        
    if method == "tools/list":
        response = {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "tools": [{
                    "name": "optimize_tool_description",
                    "description": "Accepts a verbose or ambiguous MCP tool definition (JSON) and returns an optimized version with reduced token count.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "tool_name": {"type": "string"},
                            "tool_description": {"type": "string"},
                            "tool_parameters": {"type": "object"},
                            "ai_model": {"type": "string", "default": "gpt-4o-mini"},
                            "optimization_level": {"type": "string", "default": "radical"}
                        },
                        "required": ["tool_name", "tool_description", "tool_parameters"]
                    }
                }]
            }
        }
        await queue.put(response)
        return {"status": "ok"}
        
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name == "optimize_tool_description":
            from tool_fixer import RadicalToolFixer
            from pricing_engine import PricingEngine, TokenCounter
            
            t_name = arguments.get("tool_name", "unknown")
            t_desc = arguments.get("tool_description", "")
            t_params = arguments.get("tool_parameters", {})
            model = arguments.get("ai_model", "gpt-4o-mini")
            opt_level = arguments.get("optimization_level", "radical")
            
            fixed = RadicalToolFixer.fix(t_name, t_desc, t_params, opt_level)
            original_def = {"type": "function", "function": {"name": t_name, "description": t_desc, "parameters": t_params}}
            
            tokens_orig = TokenCounter.count(original_def, model)
            tokens_fixed = TokenCounter.count(fixed, model)
            billing = PricingEngine.calculate(tokens_orig, tokens_fixed, model)
            
            response = {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "optimized_tool": fixed,
                            "billing": {
                                "tokens_saved": billing.tokens_saved,
                                "savings_usd": billing.estimated_savings_usd,
                                "fee_usd": billing.tollbooth_fee_usd
                            }
                        }, indent=2)
                    }]
                }
            }
            await queue.put(response)
            return {"status": "ok"}
            
        response = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        await queue.put(response)
        return {"status": "ok"}
        
    return {"status": "ignored", "method": method}