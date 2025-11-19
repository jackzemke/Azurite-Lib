"""
LLM Client using llama-cpp-python.

Handles local LLM inference with support for stub mode when model is absent.
"""

from pathlib import Path
from typing import Dict, Optional
import logging
import json

logger = logging.getLogger(__name__)

# Try to import llama-cpp-python, but allow graceful fallback
try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except ImportError:
    logger.warning("llama-cpp-python not installed. Running in stub mode.")
    LLAMA_AVAILABLE = False


class LLMClient:
    """Client for local LLM inference."""

    def __init__(self, config: Dict):
        """
        Initialize LLM client.

        Args:
            config: Config dict with model path and parameters
        """
        self.config = config
        self.model_path = Path(config["model"]["path"])
        self.stub_mode = False
        self.llm = None

        # Check if model file exists
        if not self.model_path.exists():
            logger.warning(f"Model file not found: {self.model_path}")
            logger.warning("Running in STUB MODE (deterministic test responses)")
            self.stub_mode = True
        elif not LLAMA_AVAILABLE:
            logger.warning("llama-cpp-python not available")
            logger.warning("Running in STUB MODE")
            self.stub_mode = True
        else:
            self._load_model()

    def _load_model(self):
        """Load LLM model."""
        try:
            logger.info(f"Loading LLM model: {self.model_path}")
            self.llm = Llama(
                model_path=str(self.model_path),
                n_gpu_layers=self.config["model"]["n_gpu_layers"],
                n_threads=self.config["model"]["n_threads"],
                seed=42,  # Deterministic for testing
                verbose=False,
            )
            logger.info("LLM model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load LLM model: {e}")
            logger.warning("Falling back to STUB MODE")
            self.stub_mode = True
            self.llm = None

    def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt
            max_tokens: Max tokens to generate (default from config)
            temperature: Sampling temperature (default from config)

        Returns:
            Generated text
        """
        if self.stub_mode:
            return self._stub_response(prompt)

        max_tokens = max_tokens or self.config["model"]["max_tokens"]
        temperature = temperature if temperature is not None else self.config["model"]["temperature"]

        try:
            response = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
                stop=["</s>", "USER:", "SYSTEM:"],
                echo=False,
            )

            return response["choices"][0]["text"]

        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return self._stub_response(prompt)

    def generate_json(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """
        Generate JSON output from prompt.

        Args:
            prompt: Input prompt (should request JSON output)
            max_tokens: Max tokens to generate

        Returns:
            Parsed JSON dict
        """
        text = self.generate(prompt, max_tokens=max_tokens, temperature=0.0)

        # Try to extract JSON from response
        try:
            # Find JSON block (between { and })
            start = text.find('{')
            end = text.rfind('}')

            if start == -1 or end == -1:
                logger.error(f"No JSON found in LLM response: {text[:200]}")
                return self._stub_json_response()

            json_str = text[start:end+1]
            return json.loads(json_str)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM: {e}")
            logger.error(f"Response text: {text[:500]}")
            return self._stub_json_response()

    def _stub_response(self, prompt: str) -> str:
        """Return deterministic stub response."""
        logger.debug("Returning stub response")
        return '{"answer": "Not found in indexed documents", "citations": [], "confidence": "low"}'

    def _stub_json_response(self) -> Dict:
        """Return deterministic stub JSON response."""
        return {
            "answer": "Not found in indexed documents",
            "citations": [],
            "confidence": "low",
        }

    def is_stub_mode(self) -> bool:
        """Check if running in stub mode."""
        return self.stub_mode


# TODO: Add streaming support for real-time response generation
# TODO: Implement prompt caching for repeated queries
# TODO: Add support for multiple model backends (vLLM, transformers)
