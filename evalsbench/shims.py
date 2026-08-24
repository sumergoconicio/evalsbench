"""
Runtime compatibility shims and error handlers for Inspect AI and OpenAI providers.
"""

import sys


def apply_inspect_openai_shims():
    """
    Applies self-healing fallback shims to inspect_ai's OpenAI provider
    to gracefully handle custom inference servers that return 405 on input_tokens count.
    """
    try:
        from inspect_ai.model._providers import openai as inspect_openai
        from openai import NotFoundError, APIStatusError

        # Wrap _count_tokens_native fallback if needed
        original_count_tokens = getattr(inspect_openai.OpenAIModelAPI, "count_tokens", None)
        if original_count_tokens:
            async def patched_count_tokens(self, input, config=None):
                if isinstance(input, str):
                    return await self.count_text_tokens(input)
                if self.responses_api:
                    try:
                        return await self._count_tokens_native(input, config)
                    except (NotFoundError, APIStatusError, Exception):
                        pass
                from inspect_ai.model._tokens import count_tokens
                return await count_tokens(input, self.count_text_tokens, self.count_media_tokens)

            inspect_openai.OpenAIModelAPI.count_tokens = patched_count_tokens
    except Exception:
        pass
