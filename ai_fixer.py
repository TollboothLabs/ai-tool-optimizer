# ai_fixer.py
# Bulletproof AI tool description optimizer for Tollbooth
# Uses gpt-4o-mini with ultra-aggressive compression prompt

import json
import os
from openai import OpenAI

# ── Ultra-aggressive compression prompt ──────────────────────────────────────
SYSTEM_PROMPT = """You are a token-minimization engine for LLM tool schemas.
Your ONLY job: rewrite JSON tool definitions to use the absolute minimum tokens
while preserving 100% of machine-parseable semantics.

RULES (non-negotiable):
1. DESCRIPTIONS: Compress to telegraphic keywords. Strip ALL of:
   - Politeness ("This function allows you to...")
   - Redundancy ("The name parameter is the name of...")
   - Articles (a, an, the)
   - Filler words (basically, simply, just, easily, allows, enables, provides)
   - Full sentences → 3-7 keyword phrase max
   - Example bad:  "Retrieves a list of all available products from the catalog"
   - Example good: "fetch product list"
2. PARAMETER NAMES: Keep exactly as-is (breaking change if renamed).
3. PARAMETER DESCRIPTIONS: Max 5 words. Noun phrases only. No verbs unless critical.
   - Bad:  "The unique identifier for the user account"
   - Good: "user account ID"
4. NESTING: Flatten wherever schema still validates. Merge single-child objects.
5. ENUM VALUES: Keep all values, strip any enum-level description if values are self-explanatory.
6. REQUIRED ARRAYS: Keep intact, no changes.
7. TYPES: Keep intact, no changes.
8. REMOVE ENTIRELY: Any field named "title" at parameter level, "externalDocs",
   "deprecated" (if false), "default" (if null), "examples", "x-*" vendor extensions.
9. OUTPUT: Return ONLY a valid JSON object. No markdown. No code fences. No commentary.
    No trailing commas. Must parse with json.loads() or you have failed.
10. TOKEN BUDGET: Your output MUST be at least 35% fewer tokens than the input.
    If you cannot reach 35%, you have not compressed hard enough. Try again.

COMPRESSION CHECKLIST (apply in order):
  [x] Strip all articles from all string values
  [x] Replace verb phrases with noun equivalents
  [x] Truncate descriptions to ≤8 words
  [x] Remove redundant type hints embedded in descriptions (already in "type" field)
  [x] Collapse verbose enums descriptions to null if values speak for themselves
  [x] Delete empty or null optional fields
"""

class AIFixer:
    """
    Calls gpt-4o-mini to compress tool definitions.
    Robust JSON extraction without complex regex.
    """
    def __init__(self):
        print("  [AIFixer] Initializing OpenAI client...")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("  [AIFixer] WARNING: OPENAI_API_KEY not set in environment!")
        
        self.client = OpenAI(api_key=api_key)
        print("  [AIFixer] Client ready.")

    def fix(self, tools: list) -> dict:
        """
        Takes a list of tool definitions, returns compressed version.
        Returns dict with keys: optimized_tools, original_tokens, optimized_tokens
        """
        print(f"  [AIFixer] fix() called with {len(tools)} tool(s).")
        
        # Serialize input for token counting and prompt injection
        raw_json = json.dumps(tools, separators=(",", ":"))
        original_token_estimate = len(raw_json.split()) * 1.3  # rough estimate
        print(f"  [AIFixer] Input size: {len(raw_json)} chars, "
              f"~{int(original_token_estimate)} tokens (rough)")

        user_message = (
            "Compress these tool definitions following all rules. "
            "Return ONLY the compressed JSON array.\n\n"
            f"{raw_json}"
        )

        print("  [AIFixer] Calling gpt-4o-mini...")
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0.0,       # deterministic - we want compression not creativity
                max_tokens=4096,
            )
        except Exception as e:
            print(f"  [AIFixer] ERROR calling OpenAI: {e}")
            raise

        raw_output = response.choices[0].message.content
        print(f"  [AIFixer] Raw response received ({len(raw_output)} chars).")
        print(f"  [AIFixer] Raw preview: {raw_output[:120]}...")

        # ── Safe JSON extraction (NO complex regex - learned from past bugs) ──
        cleaned = raw_output.strip()

        # Strip markdown code fences if model disobeyed instructions
        if cleaned.startswith("```"):
            # Find the first newline after the opening fence
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            # Strip closing fence
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            print("  [AIFixer] Stripped markdown code fences from response.")

        # Strip any leading/trailing single-line commentary before the JSON
        if cleaned.startswith("[") or cleaned.startswith("{"):
            pass  # already clean
        else:
            bracket_pos = cleaned.find("[")
            brace_pos   = cleaned.find("{")
            
            # Find whichever comes first
            positions = [p for p in [bracket_pos, brace_pos] if p != -1]
            if positions:
                start = min(positions)
                cleaned = cleaned[start:]
                print(f"  [AIFixer] Stripped {start} chars of preamble.")

        # Parse JSON
        try:
            optimized_tools = json.loads(cleaned)
            print("  [AIFixer] JSON parsed successfully.")
        except json.JSONDecodeError as e:
            print(f"  [AIFixer] JSON parse failed: {e}")
            print(f"  [AIFixer] Problematic content: {cleaned[:300]}")
            # Fallback: return original tools unmodified rather than crash
            print("  [AIFixer] Falling back to original tools (no compression).")
            optimized_tools = tools

        # Ensure we always return a list
        if isinstance(optimized_tools, dict):
            optimized_tools = [optimized_tools]

        optimized_json  = json.dumps(optimized_tools, separators=(",", ":"))
        optimized_token_estimate = len(optimized_json.split()) * 1.3
        
        savings_pct = (
            (1 - len(optimized_json) / len(raw_json)) * 100
            if len(raw_json) > 0 else 0
        )

        print(f"  [AIFixer] Compression result: "
              f"{len(raw_json)} → {len(optimized_json)} chars "
              f"({savings_pct:.1f}% reduction)")

        return {
            "optimized_tools":   optimized_tools,
            "original_tokens":   int(original_token_estimate),
            "optimized_tokens":  int(optimized_token_estimate),
            "savings_percent":   round(savings_pct, 2),
        }
