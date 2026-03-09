import openai
import json
import hashlib
import os
import re


class AIFixer:

    _cache = {}

    SYSTEM_PROMPT = (
        "You are a technical writer specializing in API documentation optimization.\n"
        "\n"
        "Your task: Rewrite MCP tool definitions to use the MINIMUM number of tokens "
        "while preserving ALL functional information.\n"
        "\n"
        "RULES:\n"
        "1. Description: Maximum 1-2 sentences. Remove ALL filler words.\n"
        "2. Parameter names: Use clear, short snake_case names.\n"
        "3. Parameter descriptions: Maximum 10 words each.\n"
        "4. Remove parameters that are deprecated, broken, or debugging-only.\n"
        "5. Add enum arrays wherever valid values are known.\n"
        "6. Flatten nested objects into flat parameters with prefixed names.\n"
        "7. Keep ONLY required and clearly useful parameters.\n"
        "8. Output ONLY valid JSON. No markdown. No explanation. No code blocks.\n"
        "\n"
        "OUTPUT SCHEMA:\n"
        '{"type":"function","function":{"name":"<name>","description":"<1-2 sentences>",'
        '"parameters":{"type":"object","properties":{"<param>":{"type":"<type>",'
        '"description":"<max 10 words>"}},"required":["<required>"]}}}'
    )

    @classmethod
    def _get_client(cls):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("  [AI FIXER] ERROR: OPENAI_API_KEY not found in environment")
            return None
        try:
            client = openai.OpenAI(api_key=api_key)
            return client
        except Exception as e:
            print(f"  [AI FIXER] ERROR creating client: {type(e).__name__}: {e}")
            return None

    @classmethod
    def _make_cache_key(cls, name, description, parameters):
        payload = json.dumps(
            {"n": name, "d": description, "p": parameters},
            sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:20]

    @classmethod
    def _clean_ai_response(cls, text):
        """
        Czyści odpowiedz AI z markdown i smieci.
        AI czesto zwraca JSON opakowany w bloki kodu.
        """
        cleaned = text.strip()

        # Usuwamy bloki kodu markdown (```json ... ``` lub ``` ... ```)
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Usun pierwsza linie (```json lub ```)
            lines = lines[1:]
            # Usun ostatnia linie jesli to ```
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # Usuwamy pojedyncze backticki na poczatku/koncu
        cleaned = cleaned.strip("`").strip()

        # Usuwamy ewentualne prefixsy typu "json" na poczatku
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

        return cleaned

    @classmethod
    def fix(cls, name, description, parameters):
        """
        Naprawia opis narzedzia przy pomocy AI.
        Zwraca naprawiony tool definition lub None.
        """
        print(f"  [AI FIXER] Starting fix for: {name}")

        # --- KROK 1: Sprawdz cache ---
        cache_key = cls._make_cache_key(name, description, parameters)
        if cache_key in cls._cache:
            print(f"  [AI FIXER] Cache HIT ({cache_key[:8]})")
            return cls._cache[cache_key]

        print(f"  [AI FIXER] Cache MISS — calling OpenAI...")

        # --- KROK 2: Sprawdz klienta ---
        client = cls._get_client()
        if client is None:
            print(f"  [AI FIXER] No client available — returning None")
            return None

        # --- KROK 3: Przygotuj wiadomosc ---
        user_message = (
            "Optimize this MCP tool definition:\n"
            "\n"
            f"Name: {name}\n"
            f"Description: {description}\n"
            f"Parameters: {json.dumps(parameters)}\n"
            "\n"
            "Return ONLY the optimized JSON object. "
            "No markdown formatting. No code blocks. No explanation."
        )

        # --- KROK 4: Wyslij do AI ---
        try:
            print(f"  [AI FIXER] Sending request to gpt-4o-mini...")

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
            print(f"  [AI FIXER] Got response, length: {len(raw_text)} chars")
            print(f"  [AI FIXER] Raw response preview: {raw_text[:200]}")

        except Exception as e:
            print(f"  [AI FIXER] API CALL ERROR: {type(e).__name__}: {e}")
            return None

        # --- KROK 5: Wyczysc odpowiedz ---
        try:
            cleaned_text = cls._clean_ai_response(raw_text)
            print(f"  [AI FIXER] Cleaned text preview: {cleaned_text[:200]}")

        except Exception as e:
            print(f"  [AI FIXER] CLEANING ERROR: {type(e).__name__}: {e}")
            return None

        # --- KROK 6: Parsuj JSON ---
        try:
            result = json.loads(cleaned_text)
            print(f"  [AI FIXER] JSON parsed OK. Keys: {list(result.keys())}")

        except json.JSONDecodeError as e:
            print(f"  [AI FIXER] JSON PARSE ERROR: {e}")
            print(f"  [AI FIXER] Problematic text: {cleaned_text[:300]}")
            return None

        # --- KROK 7: Waliduj strukture ---
        try:
            # Przypadek 1: AI zwrocilo pelna strukture
            if "type" in result and "function" in result:
                final = result
                print(f"  [AI FIXER] Structure: full (type + function)")

            # Przypadek 2: AI zwrocilo samo function body
            elif "name" in result and "description" in result:
                final = {"type": "function", "function": result}
                print(f"  [AI FIXER] Structure: partial (wrapped in function)")

            # Przypadek 3: AI zwrocilo function bez type
            elif "function" in result:
                final = {"type": "function", "function": result["function"]}
                print(f"  [AI FIXER] Structure: has function key only")

            else:
                print(f"  [AI FIXER] INVALID STRUCTURE. Keys: {list(result.keys())}")
                return None

            # Sprawdz czy function ma wymagane pola
            func = final.get("function", {})
            if "name" not in func or "description" not in func:
                print(f"  [AI FIXER] MISSING name or description in function")
                return None

            # Zapisz w cache
            cls._cache[cache_key] = final

            # Logi kosztow
            usage = response.usage
            cost = (
                usage.prompt_tokens * 0.15 / 1_000_000
                + usage.completion_tokens * 0.60 / 1_000_000
            )
            print(f"  [AI FIXER] SUCCESS! Cached as {cache_key[:8]}")
            print(f"  [AI FIXER] Cost: ${cost:.6f} | "
                  f"Tokens used: {usage.prompt_tokens}+{usage.completion_tokens}")

            return final

        except Exception as e:
            print(f"  [AI FIXER] VALIDATION ERROR: {type(e).__name__}: {e}")
            return None

    @classmethod
    def get_cache_stats(cls):
        return {
            "cached_tools": len(cls._cache),
            "cache_keys": list(cls._cache.keys())
        }
