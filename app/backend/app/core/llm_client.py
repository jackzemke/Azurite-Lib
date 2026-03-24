"""
LLM Client using llama-cpp-python with Ollama HTTP fallback.

Tries local GGUF model first. If unavailable, falls back to Ollama API.
If neither is available, runs in stub mode.
"""

from pathlib import Path
from typing import Dict, Optional
import logging
import json
import os

logger = logging.getLogger(__name__)

# Try to import llama-cpp-python, but allow graceful fallback
try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except ImportError:
    logger.warning("llama-cpp-python not installed.")
    LLAMA_AVAILABLE = False


def _check_ollama(base_url: str) -> bool:
    """Check if Ollama is reachable."""
    try:
        import httpx
        resp = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


class LLMClient:
    """Client for local LLM inference with Ollama fallback."""

    def __init__(self, config: Dict):
        self.config = config
        self.model_path = Path(config["model"]["path"])
        self.n_ctx = config["model"].get("n_ctx", 4096)
        self.stub_mode = False
        self.use_ollama = False
        self.ollama_base_url = os.environ.get("AAA_OLLAMA_URL", "http://localhost:11434")
        self.ollama_model = os.environ.get("AAA_OLLAMA_MODEL", "llama3.2:3b")
        self.llm = None

        # Try 1: local GGUF model
        if self.model_path.exists() and LLAMA_AVAILABLE:
            self._load_model()
            if self.llm is not None:
                return

        # Try 2: Ollama HTTP API
        if _check_ollama(self.ollama_base_url):
            self.use_ollama = True
            logger.info(f"Using Ollama backend ({self.ollama_base_url}, model={self.ollama_model})")
            return

        # Fallback: stub mode
        logger.warning("No LLM backend available (no GGUF model, no Ollama). Running in STUB MODE.")
        self.stub_mode = True

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
        if self.stub_mode:
            return self._stub_response(prompt)

        if self.use_ollama:
            return self._generate_ollama(prompt, max_tokens, temperature, json_mode)

        max_tokens = max_tokens or self.config["model"]["max_tokens"]
        temperature = temperature if temperature is not None else self.config["model"]["temperature"]

        try:
            formatted_prompt = (
                "<|start_header_id|>system<|end_header_id|>\n\n"
                "You are a helpful assistant that outputs valid JSON only. "
                "Do not include explanations or markdown."
                "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
                f"{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
            )

            gen_kwargs = dict(
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
                stop=["<|eot_id|>", "<|end_of_text|>"],
                echo=False,
            )

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

    def _generate_ollama(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
    ) -> str:
        """Generate via Ollama HTTP API."""
        import httpx

        max_tokens = max_tokens or self.config["model"]["max_tokens"]
        temperature = temperature if temperature is not None else self.config["model"]["temperature"]

        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if json_mode:
            payload["format"] = "json"

        try:
            resp = httpx.post(
                f"{self.ollama_base_url}/api/generate",
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            result_text = resp.json().get("response", "").strip()
            logger.debug(f"Ollama output (first 300 chars): {result_text[:300]}")
            return result_text
        except Exception as e:
            logger.error(f"Ollama generation failed: {e}")
            return self._stub_response(prompt)

    def generate_json(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        text = self.generate(prompt, max_tokens=max_tokens, temperature=0.0, json_mode=True)

        if not isinstance(text, str):
            logger.error(f"generate() returned non-string: {type(text)}, value: {text}")
            return self._stub_json_response()

        json_str = None
        try:
            start = text.find('{')
            end = text.rfind('}')

            if start == -1 or end == -1:
                logger.error(f"No JSON block found in LLM response. Full text: {text[:500]}")
                return self._stub_json_response()

            json_str = text[start:end+1]
            logger.debug(f"Extracted JSON string (first 200 chars): {json_str[:200]}")

            parsed = json.loads(json_str)
            logger.debug(f"JSON parsed successfully: type={type(parsed)}")

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
        """Check if running in stub mode (no real LLM available)."""
        return self.stub_mode and not self.use_ollama
