"""
Test LLM loading directly to debug why it's returning stub responses.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import logging

logging.basicConfig(level=logging.DEBUG)

from app.core.llm_client import LLMClient

def main():
    # Load config
    config_path = Path("/home/jack/lib/project-library/app/backend/config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    print("\n=== Testing LLM Client ===")
    print(f"Model path: {config['model']['path']}")
    print(f"Model exists: {Path(config['model']['path']).exists()}")
    print(f"GPU layers: {config['model']['n_gpu_layers']}")
    
    # Initialize client
    print("\n--- Initializing LLM Client ---")
    client = LLMClient(config)
    
    print(f"\nStub mode: {client.is_stub_mode()}")
    print(f"Model loaded: {client.llm is not None}")
    
    if client.llm:
        print("\n--- Testing simple generation ---")
        response = client.generate("Say hello in JSON: {\"greeting\":\"hello\"}", max_tokens=50)
        print(f"Response: {response}")
        
        print("\n--- Testing JSON generation ---")
        prompt = '''Output JSON only: {"test": "value", "number": 42}'''
        json_response = client.generate_json(prompt, max_tokens=100)
        print(f"JSON Response: {json_response}")
    else:
        print("\n❌ Model not loaded. Check logs above for errors.")

if __name__ == "__main__":
    main()
