import json
import hashlib
import os
import re
import openai

class AIFixer:

    _cache = {}

    SYSTEM_PROMPT = (
        "You are a technical writer specializing in API documentation optimization. "
        "Your task: Rewrite MCP tool definitions to use the MINIMUM number of tokens "
        "while preserving ALL functional information.\n\n"
        "RULES:\n"
        "1. Description: Maximum 1-2 sentences. Remove ALL filler words and uncertainty.\n"
        "2. Parameter names: Use clear, short but descriptive snake_case names.\n"
        "3. Parameter descriptions: Maximum 10 words each.\n"
        "4. Remove parameters that are: deprecated, broken, debugging-only, "
        "or described as uncertain.\n"
        "5. Add enum arrays wherever valid values are mentioned.\n"
        "6. Flatten nested objects into flat parameters with prefixed names.\n"
        "7. Keep ONLY required parameters and clearly useful optional ones.\n"
        "8. Output ONLY valid JSON. No markdown fences. No explanation.\n\n"
        "OUTPUT FORMAT:\n"
        '{"type":"function","function":{"name":"<name>",'
        '"description":"<1-2 sentences>",'
        '"parameters":{"type":"object","properties":{...},"required":[...]}}}'
    )

    @classmethod
    def _get_client(cls):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("  [AI_FIXER] ERROR: OPENAI_API_KEY not found in environment")
            return None
        try:
            client = openai.OpenAI(api_key=api_key)
            return client
        except Exception as e:
            print(f"  [AI_FIXER] ERROR creating client: {e}")
            return None

    @classmethod
    def _make_cache_key(cls, name, description, parameters):
        payload = json.dumps(
            {"n": name, "d": description, "p": parameters},
            sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:20]

    @classmethod
    def _clean_response(cls, text):
        cleaned = text.strip()

        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        cleaned = cleaned.strip("`").strip()

        first_brace = cleaned.find("{")
        if first_brace > 0:
            cleaned = cleaned[first_brace:]

        last_brace = cleaned.rfind("}")
        if last_brace != -1 and last_brace < len(cleaned) - 1:
            cleaned = cleaned[: last_brace + 1]

        return cleaned

    @classmethod
    def fix(cls, name, description, parameters):
        print(f"  [AI_FIXER] fix() called for tool: {name}")

        cache_key = cls._make_cache_key(name, description, parameters)
        if cache_key in cls._cache:
            print(f"  [AI_FIXER] Cache HIT: {cache_key[:8]}")
            return cls._cache[cache_key]

        print(f"  [AI_FIXER] Cache MISS: {cache_key[:8]}")

        client = cls._get_client()
        if client is None:
            print(f"  [AI_FIXER] No client available, returning None")
            return None

        user_message = (
            f"Optimize this MCP tool definition:\n\n"
            f"Name: {name}\n"
            f"Description: {description}\n"
            f"Parameters: {json.dumps(parameters, indent=2)}\n\n"
            f"Return ONLY the optimized JSON object. "
            f"Do NOT wrap it in markdown code fences."
        )

        try:
            print(f"  [AI_FIXER] Calling gpt-4o-mini...")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": cls.SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0,
                max_tokens=1000
            )

            raw_text = response.choices[0].message.content
            print(f"  [AI_FIXER] Raw response length: {len(raw_text)} chars")

        except Exception as e:
            print(f"  [AI_FIXER] OPENAI API ERROR: {type(e).__name__}: {e}")
            return None

        try:
            cleaned = cls._clean_response(raw_text)
            result = json.loads(cleaned)
            print(f"  [AI_FIXER] JSON parsed OK. Keys: {list(result.keys())}")

        except json.JSONDecodeError as e:
            print(f"  [AI_FIXER] JSON PARSE ERROR: {e}")
            return None

        try:
            if "function" in result:
                validated = result
            elif "name" in result and "description" in result:
                validated = {
                    "type": "function",
                    "function": result
                }
            elif "type" in result and result.get("type") == "function":
                validated = result
            else:
                print(f"  [AI_FIXER] VALIDATION ERROR: Unexpected structure")
                return None

            func = validated.get("function", {})
            if "name" not in func or "description" not in func:
                print(f"  [AI_FIXER] VALIDATION ERROR: Missing name or description")
                return None

            cls._cache[cache_key] = validated
            print(f"  [AI_FIXER] SUCCESS! Cached as {cache_key[:8]}. ")
            return validated

        except Exception as e:
            print(f"  [AI_FIXER] VALIDATION EXCEPTION: {type(e).__name__}: {e}")
            return None

    @classmethod
    def clear_cache(cls):
        count = len(cls._cache)
        cls._cache = {}
        print(f"  [AI_FIXER] Cache cleared ({count} entries removed)")
        return count

    @classmethod
    def get_cache_stats(cls):
        return {
            "cached_tools": len(cls._cache),
            "cache_keys": list(cls._cache.keys())
        }
