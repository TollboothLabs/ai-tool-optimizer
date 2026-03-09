import json
import hashlib
import os
import openai

class AIFixer:

    _cache = {}

    SYSTEM_PROMPT = (
        "You are a JSON minifier for MCP tool schemas. "
        "Your ONLY goal: MINIMIZE token count.\n\n"
        "STRICT RULES:\n"
        "DESCRIPTIONS:\n"
        "- Tool description: MAX 8 words. Telegraphic style. No articles (a/an/the). "
        "No filler. Example: 'Query database records by field match.'\n"
        "- Parameter descriptions: MAX 5 words. "
        "Example: 'City name, e.g. Warsaw'\n"
        "- NEVER use phrases like: 'This tool', 'Use this to', 'Allows you to', "
        "'You can use', 'This function', 'Returns a', 'Provides'. "
        "Start with a verb or noun directly.\n\n"
        "PARAMETERS:\n"
        "- REMOVE any parameter described as: optional, unknown, deprecated, "
        "debug, maybe, might, not sure, callback, webhook, internal, legacy, "
        "verbose, trace, log, test, meta, context, priority, timeout, retry, format.\n"
        "- REMOVE any parameter NOT in the required list UNLESS it is clearly "
        "essential for the tool's primary function.\n"
        "- FLATTEN all nested objects. Convert {filters: {field: x, op: y}} "
        "to flat params: filter_field, filter_op.\n"
        "- RENAME cryptic params: q->query, s->search, p->page, sz->limit, "
        "fmt->format, srt->sort, fld->field, dir->order, op->operation, "
        "fltr->filter, tbl->table, d->data, v->version.\n"
        "- Add 'enum' arrays when valid values are mentioned in description. "
        "Then REMOVE the description entirely if enum is self-explanatory.\n"
        "- Parameter descriptions that just restate the parameter name "
        "should be removed entirely.\n\n"
        "NAME:\n"
        "- If tool name is vague (do_stuff, run_thing, manage_x), "
        "rename to specific verb_noun: search_customers, send_message, "
        "create_ticket.\n\n"
        "OUTPUT:\n"
        "- Output RAW JSON only. No markdown. No backticks. No explanation.\n"
        "- No trailing commas. No comments.\n"
        "- Use shortest valid JSON key names from the original where unambiguous.\n"
        "- Target: 50%+ token reduction from input.\n\n"
        "EXAMPLE INPUT DESCRIPTION:\n"
        "'This is the main crm tool. it does various crm operations and stuff. "
        "you can search for customers or maybe accounts or deals or something. "
        "it was built by the backend team in 2019 and then modified a bunch of times.'\n\n"
        "EXAMPLE OUTPUT DESCRIPTION:\n"
        "'Search CRM customer records.'\n\n"
        "EXAMPLE INPUT PARAMETER:\n"
        '{"q": {"type": "string", "description": "the search query or something. '
        'put the search terms here or maybe a customer name or id. it does fuzzy matching '
        'sometimes."}}\n\n'
        "EXAMPLE OUTPUT PARAMETER:\n"
        '{"query": {"type": "string", "description": "Search term or customer ID"}}\n\n'
        "EXAMPLE INPUT (full nested param):\n"
        '{"params_blob": {"type": "object", "properties": '
        '{"fltr": {"type": "object", "properties": '
        '{"f1": {"type": "string"}, "f1_op": {"type": "string"}, '
        '"f1_val": {"type": "string"}}}}}}\n\n'
        "EXAMPLE OUTPUT (flattened):\n"
        '{"filter_field": {"type": "string"}, '
        '"filter_op": {"type": "string", "enum": ["eq","gt","lt","contains"]}, '
        '"filter_value": {"type": "string"}}'
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
    def _post_process(cls, result):
        try:
            func = result.get("function", {})
            
            desc = func.get("description", "")
            if len(desc) > 60:
                cut = desc[:57].rfind(" ")
                if cut > 20:
                    desc = desc[:cut] + "..."
                else:
                    desc = desc[:57] + "..."
                func["description"] = desc

            params = func.get("parameters", {})
            props = params.get("properties", {})

            keys_to_remove = []
            for pname, pdef in props.items():
                if not isinstance(pdef, dict):
                    continue

                pdesc = pdef.get("description", "")
                if len(pdesc) > 40:
                    cut = pdesc[:37].rfind(" ")
                    if cut > 10:
                        pdef["description"] = pdesc[:cut] + "..."
                    else:
                        pdef["description"] = pdesc[:37] + "..."

                pdesc_lower = pdef.get("description", "").lower()
                pname_lower = pname.replace("_", " ").lower()
                if pdesc_lower.startswith(f"the {pname_lower}"):
                    del pdef["description"]

                if "enum" in pdef and "description" in pdef:
                    enum_str = ", ".join(str(v) for v in pdef["enum"])
                    if len(enum_str) < 40:
                        del pdef["description"]

                if pdef.get("type") == "object" and not pdef.get("properties"):
                    keys_to_remove.append(pname)

            for k in keys_to_remove:
                del props[k]

            result["function"] = func
            return result
        except Exception as e:
            print(f"  [AI_FIXER] Post-process error (non-fatal): {e}")
            return result

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
            f"MINIFY THIS MCP TOOL. Target: 50% token reduction.\n\n"
            f'{{"name":"{name}",'
            f'"description":"{description}",'
            f'"parameters":{json.dumps(parameters)}}}\n\n'
            f"RAW JSON ONLY. No markdown. No explanation."
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
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            raw_text = response.choices[0].message.content
            print(f"  [AI_FIXER] Raw response length: {len(raw_text)} chars")

        except Exception as e:
            print(f"  [AI_FIXER] OPENAI API ERROR: {type(e).__name__}: {e}")
            return None

        try:
            cleaned = cls._clean_response(raw_text)
            result = json.loads(cleaned)
            print(f"  [AI_FIXER] JSON parsed OK.")
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

            # Dodatkowe czyszczenie po AI
            validated = cls._post_process(validated)

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
