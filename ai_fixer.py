import json
import hashlib
import os
import re
import traceback
from typing import Optional

class AIFixer:
    """
    Inteligentny optymalizator opisów narzędzi MCP.
    Wersja 2 — kuloodporna z pełnym logowaniem.
    """

    # Cache w pamięci
    _cache: dict = {}

    SYSTEM_PROMPT = """You are a technical writer who optimizes API tool definitions for minimum token count.

TASK: Rewrite the given MCP tool definition to use the MINIMUM tokens while preserving ALL functionality.

STRICT RULES:
1. Description: Max 2 sentences. No filler words. No uncertainty.
2. Parameter names: Clear snake_case. Rename cryptic names like "q" to "query".
3. Parameter descriptions: Max 10 words each.
4. Remove deprecated, broken, debug-only, or useless parameters.
5. Add "enum" arrays where valid values are mentioned.
6. Flatten deeply nested objects into top-level parameters.
7. Keep only required + clearly useful optional parameters.

You MUST respond with ONLY raw JSON. No markdown. No code fences. No explanation.
Do NOT wrap the JSON in ```json``` blocks.
Do NOT add any text before or after the JSON.

The JSON must match this structure:
{"type":"function","function":{"name":"...","description":"...","parameters":{"type":"object","properties":{...},"required":[...]}}}"""

    @classmethod
    def fix(cls, name: str, description: str, parameters: dict) -> Optional[dict]:
        print(f"\n  🧠 ====== AI FIXER v2 START ======")
        print(f"  🧠 Tool name: {name}")
        
        cache_key = cls._make_cache_key(name, description, parameters)
        
        if cache_key in cls._cache:
            print(f"  🧠 ✅ CACHE HIT — zwracam cached result")
            return cls._cache[cache_key]

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print(f"  🧠 ❌ NO API KEY — returning None")
            return None

        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
        except Exception as e:
            print(f"  🧠 ❌ FAILED to create client: {type(e).__name__}: {e}")
            traceback.print_exc()
            return None

        user_message = (
            f"Optimize this MCP tool definition. "
            f"Respond with ONLY raw JSON, no markdown:\n\n"
            f"Name: {name}\n"
            f"Description: {description}\n"
            f"Parameters: {json.dumps(parameters)}"
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": cls.SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0,
                max_tokens=1500
            )
        except Exception as e:
            print(f"  🧠 ❌ API CALL FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
            return None

        try:
            raw_text = response.choices[0].message.content
        except Exception as e:
            print(f"  🧠 ❌ FAILED to extract response text: {type(e).__name__}: {e}")
            traceback.print_exc()
            return None

        result = cls._parse_ai_response(raw_text)

        if result is None:
            print(f"  🧠 ❌ ALL PARSING ATTEMPTS FAILED")
            print(f"  🧠 '''{raw_text}'''")
            return None

        result = cls._validate_and_fix_structure(result, name)

        if result is None:
            return None

        cls._cache[cache_key] = result
        print(f"  🧠 ✅ SUCCESS! Cached as {cache_key}")
        print(f"  🧠 ====== AI FIXER v2 DONE ======\n")
        return result

    @classmethod
    def _parse_ai_response(cls, raw_text: str) -> Optional[dict]:
        text = raw_text.strip()

        # PRÓBA 1: Bezpośredni JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # PRÓBA 2: Usuń markdown
        cleaned = re.sub(r'^
http://googleusercontent.com/immersive_entry_chip/0

6. Na samej górze (lub na dole) strony GitHuba kliknij zielony przycisk **Commit changes**.

Napisz mi tylko: "Pierwszy plik zrobiony". Wtedy podam Ci równie prostą instrukcję do drugiego pliku!
