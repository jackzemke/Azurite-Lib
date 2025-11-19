"""
Query endpoint for Q&A.
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import time
import json
import logging
from datetime import datetime

from ..schemas.models import QueryRequest, QueryResponse, Citation
from ..core.embedder import Embedder
from ..core.indexer import Indexer
from ..core.llm_client import LLMClient

logger = logging.getLogger(__name__)
router = APIRouter()


def get_config():
    """Load config."""
    import yaml
    config_path = Path("/home/jack/lib/project-library/app/backend/config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_prompt_template(name: str) -> str:
    """Load prompt template."""
    prompt_path = Path("/home/jack/lib/project-library/app/backend/app/prompts") / f"{name}.txt"
    with open(prompt_path) as f:
        return f.read()


@router.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """
    Query indexed documents and return answer with citations.

    Steps:
    1. Embed query
    2. Retrieve top-K similar chunks from Chroma
    3. Generate answer with LLM using QA prompt
    4. Parse and validate response
    5. Log query
    """
    start_time = time.time()

    try:
        config = get_config()

        # Initialize components
        embedder = Embedder(model_name=config["embedding"]["model_name"])
        indexer = Indexer(chroma_db_path=Path(config["paths"]["chroma_db"]))
        llm_client = LLMClient(config)

        # Embed query
        query_embedding = embedder.model.encode([request.query])[0].tolist()

        # Retrieve chunks
        retrieved_chunks = indexer.query(
            query_embedding=query_embedding,
            project_ids=request.project_ids,
            top_k=request.k,
        )

        # Debug logging
        scope = f"projects={request.project_ids}" if request.project_ids else "all projects"
        logger.info(f"Query '{request.query}' for {scope} returned {len(retrieved_chunks)} chunks")
        if retrieved_chunks:
            logger.info(f"First chunk: {retrieved_chunks[0].get('chunk_id', 'no_id')}")

        if not retrieved_chunks:
            # No chunks found
            response = QueryResponse(
                answer="Not found in indexed documents",
                citations=[],
                confidence="low",
                elapsed_ms=int((time.time() - start_time) * 1000),
                stub_mode=llm_client.is_stub_mode(),
            )
            _log_query(config, request, response)
            return response

        # Build QA prompt
        qa_template = load_prompt_template("qa_prompt")

        candidates = [
            {
                "chunk_id": chunk["chunk_id"],
                "file_path": chunk["metadata"]["file_path"],
                "page": chunk["metadata"]["page_number"],
                "text": chunk["text"][:500],  # Truncate for context window
            }
            for chunk in retrieved_chunks
        ]

        # Replace placeholders
        user_input = json.dumps({
            "query": request.query,
            "candidates": candidates,
        })

        prompt = qa_template.replace("<<USER_QUERY>>", request.query)
        prompt = prompt.replace(
            '{ "query": "<<USER_QUERY>>", "candidates": [ { "chunk_id":"...", "file_path":"...", "page":n, "text":"..." }, ... ] }',
            user_input
        )

        # Generate answer
        logger.info(f"Generating answer for query: {request.query[:50]}")
        llm_output = llm_client.generate_json(prompt, max_tokens=512)

        # Parse response
        answer = llm_output.get("answer", "Not found in indexed documents")
        citations_raw = llm_output.get("citations", [])
        confidence = llm_output.get("confidence", "low")

        # Build citations with project_id from chunk metadata
        citations = []
        chunk_map = {chunk["chunk_id"]: chunk for chunk in retrieved_chunks}
        
        for cit in citations_raw:
            chunk_id = cit.get("chunk_id", "unknown")
            chunk = chunk_map.get(chunk_id, {})
            project_id = chunk.get("metadata", {}).get("project_id", "unknown")
            
            citations.append(Citation(
                project_id=project_id,
                file_path=cit.get("file_path", "unknown"),
                page=cit.get("page", 0),
                chunk_id=chunk_id,
                text_excerpt=cit.get("text_excerpt", "")[:500],
            ))

        elapsed_ms = int((time.time() - start_time) * 1000)

        response = QueryResponse(
            answer=answer,
            citations=citations,
            confidence=confidence,
            elapsed_ms=elapsed_ms,
            stub_mode=llm_client.is_stub_mode(),
        )

        # Log query
        _log_query(config, request, response)

        return response

    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


def _log_query(config: dict, request: QueryRequest, response: QueryResponse):
    """Log query to queries.log."""
    try:
        log_file = Path(config["logging"]["queries_log"])
        log_file.parent.mkdir(parents=True, exist_ok=True)

        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "project_id": request.project_id,
            "query": request.query,
            "top_chunk_ids": [c.chunk_id for c in response.citations],
            "confidence": response.confidence,
            "elapsed_ms": response.elapsed_ms,
            "stub_mode": response.stub_mode,
        }

        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')

    except Exception as e:
        logger.error(f"Failed to log query: {e}")
