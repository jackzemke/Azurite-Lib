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
from ..core.ajera_loader import get_ajera_data
from ..core.query_expander import QueryExpander
from ..core.project_resolver import get_project_resolver

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
        query_expander = QueryExpander()

        # Determine which projects to search
        project_ids_to_search = request.project_ids
        employee_name = None
        employee_id_resolved = request.employee_id
        
        if request.employee_id:
            ajera = get_ajera_data()
            resolver = get_project_resolver()
            
            # Check if employee_id is actually a name (contains letters/spaces)
            if not request.employee_id.isdigit():
                # Try to resolve name to ID
                resolved_id = ajera.get_employee_id_by_name(request.employee_id)
                if resolved_id:
                    employee_id_resolved = resolved_id
                    logger.info(f"Resolved employee name '{request.employee_id}' to ID {resolved_id}")
                else:
                    # Name not found
                    logger.warning(f"Could not resolve employee name: {request.employee_id}")
                    raise HTTPException(
                        status_code=404,
                        detail=f"Employee '{request.employee_id}' not found. Try searching by ID or check spelling."
                    )
            
            # Get employee's projects from Ajera and resolve to folder names for ChromaDB
            employee_name = ajera.get_employee_name(employee_id_resolved)
            employee_project_keys = ajera.get_employee_projects(employee_id_resolved)
            
            if not employee_project_keys:
                logger.warning(f"No projects found for employee {employee_id_resolved}")
            else:
                # Use resolver to convert Ajera ProjectKeys to folder names (what ChromaDB indexes)
                folder_names = resolver.get_employee_folder_names(employee_id_resolved)
                
                if folder_names:
                    project_ids_to_search = folder_names
                    logger.info(f"Filtering to {len(folder_names)} indexed folders for employee {employee_name} ({employee_id_resolved})")
                else:
                    # Employee has projects in Ajera but none are indexed in the file system
                    logger.warning(f"Employee {employee_name} has {len(employee_project_keys)} projects in Ajera but none are indexed")
                    # Fall back to searching all projects but note the limitation
                    project_ids_to_search = None
        
        # Expand query for better semantic matching
        expanded_query = query_expander.expand_query(request.query)
        
        # Get document type hints for boosting relevant document types
        doc_type_hints = query_expander.get_doc_type_hints(request.query)
        if doc_type_hints:
            logger.info(f"Doc type hints for query: {doc_type_hints}")
        
        # Embed expanded query
        query_embedding = embedder.model.encode([expanded_query])[0].tolist()

        # Detect team/people queries for hybrid search (include Ajera time tracking)
        query_lower = request.query.lower()
        team_keywords = ["who worked", "who's working", "who is working", "team", "staff", 
                         "people", "employees", "worked on", "working on", "personnel",
                         "engineer", "engineers", "manager", "pm", "project manager",
                         "architect", "designer", "who was", "who did", "who is"]
        is_team_query = any(keyword in query_lower for keyword in team_keywords)
        
        # For broad queries, retrieve more chunks for better synthesis
        is_broad_query = any(term in query_lower for term in ["summary", "overview", "purpose", "about", "describe", "explain", "what was"])
        retrieval_k = min(request.k * 2, 15) if is_broad_query else request.k
        
        # Retrieve chunks with doc type boosting
        retrieved_chunks = indexer.query(
            query_embedding=query_embedding,
            project_ids=project_ids_to_search,
            top_k=retrieval_k,
            doc_type_hints=doc_type_hints,
        )
        
        # If no results with expanded query, try alternative formulations
        if not retrieved_chunks:
            logger.info("No results with expanded query, trying alternatives...")
            for alt_query in query_expander.rewrite_query(request.query):
                alt_embedding = embedder.model.encode([alt_query])[0].tolist()
                retrieved_chunks = indexer.query(
                    query_embedding=alt_embedding,
                    project_ids=project_ids_to_search,
                    top_k=retrieval_k,
                    doc_type_hints=doc_type_hints,
                )
                if retrieved_chunks:
                    logger.info(f"Found results with alternative query: '{alt_query}'")
                    break

        # Enhanced debug logging for failure isolation
        scope = f"projects={request.project_ids}" if request.project_ids else "all projects"
        logger.info(f"[RETRIEVAL] Query: '{request.query}' | Scope: {scope} | Results: {len(retrieved_chunks)}")
        
        if retrieved_chunks:
            # Log retrieval quality metrics (chunk_ids only, not text - privacy)
            chunk_summary = []
            for i, chunk in enumerate(retrieved_chunks[:5]):
                dist = chunk.get('distance', 0)
                fname = Path(chunk['metadata'].get('file_path', '')).name[:30]
                chunk_summary.append(f"[{i+1}] d={dist:.3f} {fname}")
            logger.info(f"[RETRIEVAL] Top chunks: {'; '.join(chunk_summary)}")
        else:
            logger.warning(f"[RETRIEVAL] No chunks found for query: '{request.query}'")
        
        # For team queries, get Ajera data if project_id available
        ajera_team_data = None
        if is_team_query and request.project_ids and len(request.project_ids) == 1:
            try:
                resolver = get_project_resolver()
                project_folder = request.project_ids[0]
                
                # Use resolver to get team data (handles folder -> Ajera key mapping)
                team = resolver.get_project_team_from_folder(project_folder)
                if team:
                    # Top 10 employees by hours
                    top_team = team[:10]
                    ajera_team_data = {
                        "total_employees": len(team),
                        "top_employees": top_team,
                        "project_folder": project_folder
                    }
                    logger.info(f"Team query: Found {len(team)} employees for project folder '{project_folder}'")
                else:
                    logger.info(f"Team query: No Ajera records found for folder '{project_folder}'")
            except Exception as e:
                logger.warning(f"Error getting Ajera team data: {e}")

        if not retrieved_chunks:
            # For team queries with no docs, return Ajera team if available
            if is_team_query and ajera_team_data:
                team_list = "\n".join([
                    f"  • {emp['name']} (Employee {emp['employee_id']}): {emp['total_hours']} hours"
                    for emp in ajera_team_data['top_employees']
                ])
                total = ajera_team_data['total_employees']
                showing = len(ajera_team_data['top_employees'])
                more = f" (showing top {showing} of {total})" if total > showing else ""
                
                response = QueryResponse(
                    answer=(
                        f"No team information found in indexed documents. "
                        f"However, Ajera records show {total} employees logged time on this project{more}:\n\n"
                        f"{team_list}"
                    ),
                    citations=[],
                    confidence="medium",
                    elapsed_ms=int((time.time() - start_time) * 1000),
                    stub_mode=llm_client.is_stub_mode(),
                )
                _log_query(config, request, response)
                return response
            
            # No chunks found - provide fallback with Ajera project info
            fallback_msg = "Not found in indexed documents."
            
            if employee_id_resolved and project_ids_to_search:
                # Return project IDs the employee worked on as fallback
                ajera = get_ajera_data()
                
                # Try metadata search first (searches location, marketing fields, etc.)
                matching_projects = ajera.search_projects_by_metadata(request.query, limit=5)
                
                # Filter to employee's projects
                matching_projects = [p for p in matching_projects if p['project_id'] in project_ids_to_search]
                
                # If no metadata matches, try simple name search
                if not matching_projects:
                    matching_projects = ajera.search_projects_by_name(request.query, limit=5)
                
                if matching_projects:
                    project_list = "\n".join([
                        f"- Project {p['project_id']}: {p['name']}" + 
                        (f" ({p['location']})" if p.get('location') else "") +
                        (f" - Type: {p['project_type']}" if p.get('project_type') else "")
                        for p in matching_projects
                    ])
                    
                    fallback_msg += f"\n\nHowever, {employee_name or 'this employee'} has worked on these potentially relevant projects:\n{project_list}\n\nNo documents are indexed for these projects yet. Check the file server or Ajera database for more details."
                else:
                    fallback_msg += f"\n\n{employee_name or 'This employee'} has worked on {len(project_ids_to_search)} projects. No documents matching your query were found. Try uploading project documents or check the file server."
            
            response = QueryResponse(
                answer=fallback_msg,
                citations=[],
                confidence="low",
                elapsed_ms=int((time.time() - start_time) * 1000),
                stub_mode=llm_client.is_stub_mode(),
            )
            _log_query(config, request, response)
            return response

        # Build QA prompt
        qa_template = load_prompt_template("qa_prompt")

        # Convert absolute paths to relative for LLM (cleaner, prevents path leakage)
        base_docs_path = Path(config["paths"]["raw_docs"])
        candidates = []
        for chunk in retrieved_chunks[:6]:  # Limit chunks to prevent token overflow
            file_path_abs = Path(chunk["metadata"]["file_path"])
            project_id = chunk["metadata"]["project_id"]
            
            # Make path relative to project directory
            try:
                file_path_rel = str(file_path_abs.relative_to(base_docs_path / project_id))
            except ValueError:
                # Fallback: use just the filename if relative conversion fails
                file_path_rel = file_path_abs.name
            
            # Extract document name from filename for better context
            doc_name = Path(file_path_rel).stem.replace("_", " ").replace("-", " ")
            
            candidates.append({
                "chunk_id": chunk["chunk_id"],
                "file_path": file_path_rel,
                "doc_name": doc_name,
                "project": project_id,
                "page": chunk["metadata"]["page_number"],
                "text": chunk["text"][:800],
            })

        # Format chat history
        history_text = "None" if not request.chat_history else "\n".join([
            f"Q: {h['query']}\nA: {h['answer']}"
            for h in request.chat_history[-3:]  # Last 3 exchanges
        ])
        
        # Format candidates with better document context
        candidates_text = "\n\n".join([
            f"[Chunk {i+1}]\n"
            f"Chunk ID: {c['chunk_id']}\n"
            f"Document: {c['doc_name']}\n"
            f"Project: {c['project']}\n"
            f"Page: {c['page']}\n"
            f"Content:\n{c['text']}"
            for i, c in enumerate(candidates)
        ])
        
        # Add Ajera team data to context for team queries
        if is_team_query and ajera_team_data:
            team_list = "\n".join([
                f"  - {emp['name']} (Employee {emp['employee_id']}): {emp['total_hours']} hours logged"
                for emp in ajera_team_data['top_employees']
            ])
            total = ajera_team_data['total_employees']
            showing = len(ajera_team_data['top_employees'])
            more = f" (showing top {showing} by hours)" if total > showing else ""
            
            candidates_text += f"\n\n[AJERA TIME TRACKING DATA]\nTotal employees who logged time: {total}{more}\n{team_list}"
            logger.info(f"Added Ajera team context for {total} employees")

        # Replace placeholders
        prompt = qa_template.replace("<<CHAT_HISTORY>>", history_text)
        prompt = prompt.replace("<<USER_QUERY>>", request.query)
        prompt = prompt.replace("<<CANDIDATES>>", candidates_text)

        # Generate answer
        logger.info(f"Generating answer for query: {request.query[:50]}")
        llm_output = llm_client.generate_json(prompt, max_tokens=3500)  # Very high limit to prevent JSON truncation with many chunks

        # Log what LLM returned for debugging
        logger.debug(f"LLM output type: {type(llm_output)}, keys: {llm_output.keys() if isinstance(llm_output, dict) else 'N/A'}")
        
        # Parse response (with defensive type checking)
        if not isinstance(llm_output, dict):
            logger.error(f"llm_output is not a dict: type={type(llm_output)}, value={str(llm_output)[:500]}")
            llm_output = {"answer": "Not found in indexed documents", "citations": [], "confidence": "low"}
        
        answer = llm_output.get("answer", "Not found in indexed documents")
        citations_raw = llm_output.get("citations", [])
        confidence = llm_output.get("confidence", "low")
        
        # Ensure citations is always a list
        if not isinstance(citations_raw, list):
            logger.error(f"citations_raw is not a list: type={type(citations_raw)}, value={citations_raw}")
            citations_raw = []

        # Build citations using chunk metadata as source of truth
        # LLM only provides chunk_ids, we fill in all other fields from metadata
        citations = []
        chunk_map = {chunk["chunk_id"]: chunk for chunk in retrieved_chunks}
        base_docs_path = Path(config["paths"]["raw_docs"])
        
        for cit in citations_raw:
            # Handle both formats: {"chunk_id": "..."} or just "chunk_id_string"
            if isinstance(cit, dict):
                chunk_id = cit.get("chunk_id", "unknown")
            elif isinstance(cit, str):
                chunk_id = cit
                logger.debug(f"Citation was string, not dict: {cit}")
            else:
                logger.warning(f"Unexpected citation format: type={type(cit)}, value={cit}")
                continue
            
            chunk = chunk_map.get(chunk_id)
            
            if not chunk:
                logger.warning(f"Citation references unknown chunk_id: {chunk_id}")
                continue
            
            # Use chunk metadata as source of truth (don't trust any LLM values except chunk_id)
            project_id = chunk["metadata"]["project_id"]
            file_path_abs = Path(chunk["metadata"]["file_path"])
            
            # Convert to relative path for API endpoint
            try:
                file_path_rel = str(file_path_abs.relative_to(base_docs_path / project_id))
            except ValueError:
                # Fallback: use filename if path is weird
                file_path_rel = file_path_abs.name
                logger.warning(f"Could not make path relative: {file_path_abs}")
            
            # Generate text excerpt from chunk (first 100 chars)
            text_excerpt = chunk["text"][:100].strip()
            
            citations.append(Citation(
                project_id=project_id,
                file_path=file_path_rel,
                page=chunk["metadata"]["page_number"],
                chunk_id=chunk_id,
                text_excerpt=text_excerpt,
            ))

        # Deduplicate citations by file+page (keep first occurrence)
        seen_file_pages = set()
        unique_citations = []
        for cit in citations:
            key = (cit.file_path, cit.page)
            if key not in seen_file_pages:
                seen_file_pages.add(key)
                unique_citations.append(cit)
        
        if len(unique_citations) < len(citations):
            logger.debug(f"Deduplicated citations: {len(citations)} -> {len(unique_citations)}")
        citations = unique_citations

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

        # Get employee_id_resolved from outer scope if available
        employee_id_for_log = getattr(query_documents, '_employee_id_resolved', request.employee_id)
        
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "project_ids": request.project_ids,
            "employee_id": employee_id_for_log,
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
