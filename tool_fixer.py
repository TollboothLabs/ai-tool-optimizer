import json
import re
from typing import Any

class RadicalToolFixer:
    FILLER_PATTERNS = [
        r"\bi\s*guess\b", r"\bidk\b", r"\bi\s*think\b",
        r"\bmaybe\b", r"\bprobably\b", r"\bor\s+something\b",
        r"\bnot\s+sure\b", r"\bhonestly\b", r"\blol\b",
        r"\btbh\b", r"\bi\s*don'?t\s+remember\b",
        r"\bnot\s+100%\s+sure\b", r"\bmight\s+be\b",
        r"\bcould\s+be\b", r"\bwhatever\b", r"\bjust\s+try\b",
        r"\bno\s+idea\b", r"\bsomehow\b", r"\banyway\b",
        r"\bbasically\b", r"\bkind\s+of\b", r"\bsort\s+of\b",
        r"\band\s+stuff\b", r"\bor\s+stuff\b",
        r"\byou\s+know\b", r"\bi\s+cant\s+remember\b",
        r"\boh\s+and\b", r"\boh\s+also\b",
        r"\bmight\s+also\b", r"\bmight\s+not\b",
        r"\bim\s+leaving\s+it\b",
        r"\bjust\s+leave\s+it\s+empty\s+if\s+unsure\b",
        r"\bmight\s+be\s+useful\b",
        r"\bit\s+was\s+in\s+the\s+original\s+spec\s+so\b",
        r"\bdepends\s+on\s+the\b",
        r"\bi\s+forget\b", r"\bi\s+forgot\b",
    ]
    
    PARAM_RENAMES = {
        "q": "query", "s": "search", "p": "page",
        "sz": "page_size", "pg": "pagination",
        "srt": "sort", "fld": "field", "dir": "direction",
        "fmt": "format", "fltr": "filter", "v": "version",
        "f1": "filter_field_1", "f1_op": "filter_op_1",
        "f1_val": "filter_value_1", "f2": "filter_field_2",
        "f2_op": "filter_op_2", "f2_val": "filter_value_2",
        "thing1": "primary_input", "thing2": "secondary_input",
        "thing3": "tertiary_input", "d": "data",
        "cb": "callback", "ts": "timestamp", "ctx": "context",
        "tid": "tenant_id", "src": "source",
        "req_id": "request_id", "op_type": "operation",
        "tbl": "table_name",
    }
    
    JUNK_PARAM_INDICATORS = [
        "callback_url", "webhook", "debug", "debug_mode",
        "verbose", "trace", "log_level", "deprecated",
        "legacy", "internal", "test", "testing",
        "auth_override", "extra_conditions",
    ]

    @classmethod
    def fix(cls, name: str, description: str, parameters: dict, level: str = "radical") -> dict:
        fixed_name = cls._fix_name(name)
        fixed_desc = cls._fix_description(description, level)
        fixed_params = cls._fix_parameters(parameters, level)
        return {
            "type": "function",
            "function": {
                "name": fixed_name,
                "description": fixed_desc,
                "parameters": fixed_params
            }
        }

    @classmethod
    def _fix_name(cls, name: str) -> str:
        fixed = name.strip().lower()
        fixed = re.sub(r"[^a-z0-9_]", "_", fixed)
        while "__" in fixed:
            fixed = fixed.replace("__", "_")
        fixed = fixed.strip("_")
        return fixed or "unnamed_tool"

    @classmethod
    def _fix_description(cls, description: str, level: str) -> str:
        text = description
        for pattern in cls.FILLER_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\.\s*\.", ".", text)
        text = re.sub(r",\s*,", ",", text)
        text = re.sub(r"\?\s*", ". ", text)
        text = text.strip().strip(".,;:!").strip()
        
        if level in ("standard", "radical"):
            sentences = re.split(r"(?<=[.!])\s+", text)
            confident_sentences = []
            uncertainty_words = ["not sure", "might", "maybe", "possibly", "i think", "i guess", "probably", "idk", "not certain", "unclear", "don't know", "depends", "sometimes", "could also"]
            for sentence in sentences:
                if not any(uw in sentence.lower() for uw in uncertainty_words):
                    confident_sentences.append(sentence)
            text = " ".join(confident_sentences)
            
        if level == "radical":
            sentences = re.split(r"(?<=[.!])\s+", text)
            sentences = [s for s in sentences if len(s.strip()) > 10]
            text = " ".join(sentences[:2])
            if len(text) > 200:
                text = text[:197] + "..."
                
        if text and not text.endswith("."):
            text += "."
        if text:
            text = text[0].upper() + text[1:]
        return text or "Tool with unspecified function."

    @classmethod
    def _fix_parameters(cls, parameters: dict, level: str) -> dict:
        if not parameters or not isinstance(parameters, dict):
            return {"type": "object", "properties": {}}
        
        properties = parameters.get("properties", {})
        required = set(parameters.get("required", []))
        new_properties = {}
        new_required = []
        
        for param_name, param_def in properties.items():
            if not isinstance(param_def, dict):
                continue
            new_name = cls.PARAM_RENAMES.get(param_name, param_name)
            
            if level == "radical" and param_name not in required:
                if any(junk in param_name.lower() for junk in cls.JUNK_PARAM_INDICATORS):
                    continue
                desc = param_def.get("description", "").lower()
                if any(junk in desc for junk in ["no idea", "dont know", "deprecated", "might not", "leave it empty", "not sure if", "does anything", "broken", "ignore"]):
                    continue
                    
            new_def = {}
            if "type" in param_def: new_def["type"] = param_def["type"]
            if "description" in param_def:
                new_desc = cls._fix_description(param_def["description"], level)
                if level == "radical" and len(new_desc) > 80: new_desc = new_desc[:77] + "..."
                new_def["description"] = new_desc
            else:
                new_def["description"] = f"The {new_name} value."
                
            if "enum" in param_def: new_def["enum"] = param_def["enum"]
            
            if param_def.get("type") == "object" and "properties" in param_def:
                if level in ("standard", "radical"):
                    nested_props = param_def.get("properties", {})
                    for nested_name, nested_def in nested_props.items():
                        if not isinstance(nested_def, dict): continue
                        flat_name = f"{new_name}_{cls.PARAM_RENAMES.get(nested_name, nested_name)}"
                        flat_def = {}
                        if "type" in nested_def: flat_def["type"] = nested_def["type"]
                        if "description" in nested_def:
                            flat_def["description"] = cls._fix_description(nested_def["description"], level)
                        else:
                            flat_def["description"] = f"The {flat_name} value."
                        if "enum" in nested_def: flat_def["enum"] = nested_def["enum"]
                        
                        if level == "radical":
                            nested_required = set(param_def.get("required", []))
                            if nested_name not in nested_required:
                                nd = nested_def.get("description", "").lower()
                                if any(w in nd for w in ["no idea", "optional", "not sure", "deprecated", "broken"]):
                                    continue
                        if level == "radical" and len(flat_def.get("description", "")) > 80:
                            flat_def["description"] = flat_def["description"][:77] + "..."
                        new_properties[flat_name] = flat_def
                    continue
                else:
                    nested_fixed = cls._fix_parameters(param_def, level)
                    new_def["properties"] = nested_fixed.get("properties", {})
                    if "required" in nested_fixed: new_def["required"] = nested_fixed["required"]
                    
            new_properties[new_name] = new_def
            if param_name in required: new_required.append(new_name)
            
        result = {"type": "object", "properties": new_properties}
        if new_required: result["required"] = new_required
        return result