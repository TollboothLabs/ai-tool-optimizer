import openai
import json
import hashlib
import os
from typing import Optional

class AIFixer:
    _cache: dict = {}
    SYSTEM_PROMPT = """You are a technical writer. Rewrite MCP tool definitions to use MINIMUM tokens while preserving ALL functional information. Output ONLY valid JSON."""

    @classmethod
    def fix(cls, name, description, parameters):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        
        client = openai.OpenAI(api_key=api_key)
        user_message = f"Optimize this: Name: {name}, Desc: {description}, Params: {json.dumps(parameters)}"
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": cls.SYSTEM_PROMPT}, {"role": "user", "content": user_message}],
                temperature=0.0
            )
            return json.loads(response.choices[0].message.content.strip())
        except:
            return None