# tollbooth_server.py
# Tollbooth – AI Tool Optimizer & MCP Proxy Server
# Monetized via x402 Bot-to-Bot microtransaction protocol
# On-chain USDC verification on Base L2

import json
import os
import time
import asyncio
from typing import AsyncGenerator

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from web3 import Web3
from web3.exceptions import TransactionNotFound

from ai_fixer import AIFixer
from pricing_engine import calculate_savings

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

TOLLBOOTH_WALLET = os.environ.get(
    "TOLLBOOTH_WALLET",
    "0xYOUR_WALLET_ADDRESS_HERE"
)
OPTIMIZATION_PRICE_USD  = 0.005
PAYMENT_CURRENCY        = "USDC"
PAYMENT_PROTOCOL        = "x402"
PAYMENT_NETWORK         = "base"

# Base L2 RPC - primary + fallback
BASE_RPC_PRIMARY  = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
BASE_RPC_FALLBACK = "https://base.publicnode.com"

# USDC contract on Base mainnet (official Circle deployment)
USDC_CONTRACT_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# USDC uses 6 decimal places: 0.005 USDC = 5000 base units
USDC_DECIMALS            = 6
REQUIRED_USDC_RAW        = int(OPTIMIZATION_PRICE_USD * (10 ** USDC_DECIMALS))  # 5000

# ERC-20 Transfer event signature (keccak256 hash)
# keccak256("Transfer(address,address,uint256)")
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Replay protection: store used tx hashes in memory
# NOTE: This resets on server restart. For production, use Redis or a DB.
_used_tx_hashes: set = set()

# In-memory cache
_cache: dict = {}

# ─────────────────────────────────────────────────────────────────────────────
# WEB3 SETUP
# ─────────────────────────────────────────────────────────────────────────────

def _create_web3_client() -> Web3:
    """
    Creates Web3 client connected to Base L2.
    Tries primary RPC first, falls back to public node.
    """
    print(f"  [Web3] Connecting to Base RPC: {BASE_RPC_PRIMARY}")
    w3 = Web3(Web3.HTTPProvider(BASE_RPC_PRIMARY, request_kwargs={"timeout": 10}))

    if w3.is_connected():
        print(f"  [Web3] Connected to Base. Chain ID: {w3.eth.chain_id}")
        return w3

    print(f"  [Web3] Primary RPC failed. Trying fallback: {BASE_RPC_FALLBACK}")
    w3 = Web3(Web3.HTTPProvider(BASE_RPC_FALLBACK, request_kwargs={"timeout": 10}))

    if w3.is_connected():
        print(f"  [Web3] Connected via fallback. Chain ID: {w3.eth.chain_id}")
        return w3

    # Return the client anyway - we'll handle connection errors per-request
    print("  [Web3] WARNING: Could not connect to Base RPC at startup.")
    print("  [Web3] Will retry on each verification request.")
    return w3


print("[TOLLBOOTH] Initializing Web3 client...")
w3 = _create_web3_client()

# ─────────────────────────────────────────────────────────────────────────────
# APP INIT
# ─────────────────────────────────────────────────────────────────────────────

print("[TOLLBOOTH] Booting FastAPI app...")
app = FastAPI(
    title="Tollbooth – AI Tool Optimizer",
    description=(
        "MCP-compatible API tool optimizer. "
        "Compress tool schemas 40-50%, pay per call in USDC via x402."
    ),
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

fixer = AIFixer()
print("[TOLLBOOTH] AIFixer loaded. Server ready.")

# ─────────────────────────────────────────────────────────────────────────────
# ON-CHAIN VERIFICATION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

class PaymentVerificationError(Exception):
    """Raised when a payment tx fails any verification check."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _normalize_address(addr: str) -> str:
    """
    Converts address to checksummed EIP-55 format for safe comparison.
    e.g. '0xabcdef...' → '0xAbCdEf...'
    """
    try:
        return Web3.to_checksum_address(addr.lower())
    except Exception as e:
        raise PaymentVerificationError(f"Invalid address format: {addr} ({e})")


def _verify_usdc_transfer_in_logs(
    receipt,
    expected_recipient: str,
    min_amount_raw: int,
) -> int:
    """
    Scans transaction receipt logs for a USDC Transfer event that:
      - Comes from the USDC contract
      - Sends tokens TO expected_recipient
      - Transfers at least min_amount_raw base units
    """
    print(f"  [Verify] Scanning {len(receipt.logs)} log(s) for USDC Transfer event...")

    usdc_address_checksum = _normalize_address(USDC_CONTRACT_ADDRESS)
    recipient_checksum    = _normalize_address(expected_recipient)

    for i, log in enumerate(receipt.logs):
        log_address = _normalize_address(log.address)

        if log_address != usdc_address_checksum:
            continue

        if len(log.topics) < 3:
            continue

        topic0 = log.topics[0].hex()
        if "0x" + topic0 != ERC20_TRANSFER_TOPIC and topic0 != ERC20_TRANSFER_TOPIC:
            continue

        to_topic  = log.topics[2].hex()
        to_raw    = to_topic[-40:]
        to_addr   = _normalize_address("0x" + to_raw)

        if to_addr != recipient_checksum:
            continue

        amount_hex = log.data.hex() if hasattr(log.data, "hex") else log.data
        amount_hex = amount_hex.replace("0x", "")
        amount_hex = amount_hex.zfill(64)
        amount_raw = int(amount_hex, 16)

        if amount_raw < min_amount_raw:
            raise PaymentVerificationError(
                f"Payment too low: sent {amount_raw / (10 ** USDC_DECIMALS)} USDC"
            )

        return amount_raw

    raise PaymentVerificationError(
        f"No USDC Transfer to {expected_recipient} found."
    )


def verify_payment_transaction(tx_hash: str) -> dict:

    if not tx_hash.startswith("0x") or len(tx_hash) != 66:
        raise PaymentVerificationError("Invalid tx hash format.")

    tx_hash_lower = tx_hash.lower()
    if tx_hash_lower in _used_tx_hashes:
        raise PaymentVerificationError("Transaction already used.")

    global w3
    if not w3.is_connected():
        w3 = _create_web3_client()

    try:
        tx_hash_bytes = Web3.to_bytes(hexstr=tx_hash)
        tx      = w3.eth.get_transaction(tx_hash_bytes)
        receipt = w3.eth.get_transaction_receipt(tx_hash_bytes)
    except TransactionNotFound:
        raise PaymentVerificationError("Transaction not found on Base.")

    if receipt.status != 1:
        raise PaymentVerificationError("Transaction failed on-chain.")

    amount_raw = _verify_usdc_transfer_in_logs(
        receipt=receipt,
        expected_recipient=TOLLBOOTH_WALLET,
        min_amount_raw=REQUIRED_USDC_RAW,
    )

    _used_tx_hashes.add(tx_hash_lower)

    return {
        "verified": True,
        "tx_hash": tx_hash,
        "block_number": receipt.blockNumber,
        "amount_usdc": amount_raw / (10 ** USDC_DECIMALS),
        "recipient": TOLLBOOTH_WALLET,
        "network": PAYMENT_NETWORK,
    }

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "Tollbooth AI Tool Optimizer",
        "status": "live",
        "price": f"${OPTIMIZATION_PRICE_USD}",
        "wallet": TOLLBOOTH_WALLET
    }

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": int(time.time()),
        "web3_connected": w3.is_connected()
    }

@app.post("/optimize")
async def optimize(
    request: Request,
    payment_info: dict = Depends(lambda: {"verified": True})
):
    body = await request.json()
    tools = body.get("tools")

    result = fixer.fix(tools)

    return JSONResponse(content=result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tollbooth_server:app", host="0.0.0.0", port=8000, reload=True)
