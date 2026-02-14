"""
LLM Client using llama-cpp-python.

Handles local LLM inference with support for stub mode when model is absent.
Supports both Llama-3.1 and Llama-3.2 instruct format.
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
        self.n_ctx = config["model"].get("n_ctx", 4096)
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
            n_gpu = self.config["model"]["n_gpu_layers"]
            logger.info(f"Loading LLM model: {self.model_path}")
            logger.info(f"GPU layers: {n_gpu}, Threads: {self.config['model']['n_threads']}, Context: {self.n_ctx}")
            self.llm = Llama(
                model_path=str(self.model_path),
                n_gpu_layers=n_gpu,
                n_threads=self.config["model"]["n_threads"],
                n_ctx=self.n_ctx,
                seed=42,
                verbose=False,
            )
            logger.info(f"LLM model loaded with {n_gpu} GPU layers (context: {self.n_ctx} tokens)")

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
        json_mode: bool = False,
    ) -> str:
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt
            max_tokens: Max tokens to generate (default from config)
            temperature: Sampling temperature (default from config)
            json_mode: If True, constrain output to valid JSON via grammar

        Returns:
            Generated text
        """
        if self.stub_mode:
            return self._stub_response(prompt)

        max_tokens = max_tokens or self.config["model"]["max_tokens"]
        temperature = temperature if temperature is not None else self.config["model"]["temperature"]

        try:
            # Llama-3.x instruct format (works for both 3.1 and 3.2)
            formatted_prompt = (
                "<|start_header_id|>system<|end_header_id|>\n\n"
                "You are a helpful assistant that outputs valid JSON only. "
                "Do not include explanations or markdown."
                "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
                f"{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
            )

            # Build generation kwargs
            gen_kwargs = dict(
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
                stop=["<|eot_id|>", "<|end_of_text|>"],
                echo=False,
            )

            # JSON grammar constrains output to valid JSON objects
            if json_mode and hasattr(self.llm, 'grammar'):
                try:
                    from llama_cpp import LlamaGrammar
                    json_grammar = LlamaGrammar.from_string(
                        r'''root   ::= object
value  ::= object | array | string | number | ("true" | "false" | "null") ws

object ::= "{" ws (string ":" ws value ("," ws string ":" ws value)*)? "}" ws

array  ::= "[" ws (value ("," ws value)*)? "]" ws

string ::= "\"" ([^"\\] | "\\" .)* "\"" ws

number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)? ws

ws     ::= ([ \t\n] ws)?'''
                    )
                    gen_kwargs["grammar"] = json_grammar
                except Exception as e:
                    logger.debug(f"JSON grammar not available: {e}")

            response = self.llm(formatted_prompt, **gen_kwargs)

            result_text = response["choices"][0]["text"].strip()
            logger.debug(f"LLM raw output (first 300 chars): {result_text[:300]}")
            return result_text

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
            Parsed JSON dict (never returns None or non-dict)
        """
        text = self.generate(prompt, max_tokens=max_tokens, temperature=0.0, json_mode=True)

        # Ensure text is a string
        if not isinstance(text, str):
            logger.error(f"generate() returned non-string: {type(text)}, value: {text}")
            return self._stub_json_response()

        # Try to extract JSON from response
        json_str = None
        try:
            # Find JSON block (between { and })
            start = text.find('{')
            end = text.rfind('}')

            if start == -1 or end == -1:
                logger.error(f"No JSON block found in LLM response. Full text: {text[:500]}")
                return self._stub_json_response()

            json_str = text[start:end+1]
            logger.debug(f"Extracted JSON string (first 200 chars): {json_str[:200]}")

            parsed = json.loads(json_str)
            logger.debug(f"JSON parsed successfully: type={type(parsed)}")

            # Ensure parsed is a dict
            if not isinstance(parsed, dict):
                logger.error(f"Parsed JSON is not a dict: {type(parsed)}, value: {parsed}")
                return self._stub_json_response()

            return parsed

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            logger.error(f"JSON string attempted: {json_str[:500] if json_str else 'N/A'}")
            return self._stub_json_response()
        except Exception as e:
            logger.error(f"Unexpected error in generate_json: {type(e).__name__}: {e}")
            return self._stub_json_response()

    def _stub_response(self, prompt: str) -> str:
        """Return deterministic stub response."""
        logger.debug("Returning stub response")
        return json.dumps({"answer": "Not found in indexed documents", "citations": [], "confidence": "low"})

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
