from typing import Protocol, Optional, Dict, Any
import pandas as pd

class OpenRouterTool(Protocol):

    def create_writable_df_for_async_chat_completion(self, arg_async_map: dict) -> pd.DataFrame:
        """Create DataFrame for async chat completion results"""
        ...

    def generate_simple_text_output(
        self,
        model: str,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        ...

    async def generate_simple_text_output_async(
        self,
        model: str,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        ...

    async def create_single_chat_completion(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0
    ) -> Dict[str, Any]:
        """
        Create a single chat completion with system and user prompts.
        
        Args:
            model: The model to use (e.g., "anthropic/claude-3.5-sonnet")
            system_prompt: The system prompt to set context
            user_prompt: The user's prompt/question
            temperature: Sampling temperature (default: 0 for deterministic output)
            
        Returns:
            Dict containing the completion response
        """