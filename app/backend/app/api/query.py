"""
Query endpoint for Q&A.
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import time
import json
import logging
from datetime import datetime

from ..config import settings
from ..schemas.models import QueryRequest, QueryResponse, Citation
from ..core.ajera_loader import get_ajera_data
from ..core.project_resolver import get_project_resolver
from ..core.query_router import classify_query, QueryIntent, RouterResult
from ..services import get_embedder, get_indexer, get_llm_client, get_reranker, get_query_expander, get_directory_index

logger = logging.getLogger(__name__)
router = APIRouter()


def load_prompt_template(name: str) -> str:
    """Load prompt template."""
    prompt_path = settings.prompts_dir / f"{name}.txt"
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
        # Use singleton services (initialized once, reused across requests)
        embedder = get_embedder()
        indexer = get_indexer()
        llm_client = get_llm_client()
        query_expander = get_query_expander()
        reranker = get_reranker()

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
        
        # Embed expanded query (uses search_query: prefix for nomic model)
        query_embedding = embedder.embed_query(expanded_query)

        # Classify query intent (rule-based, ~0ms)
        router_result = classify_query(request.query)
        is_team_query = router_result.is_team_query
        is_broad_query = router_result.is_broad_query
        retrieval_k = min(request.k * 2, 15) if is_broad_query else request.k

        # Fetch extra candidates for cross-encoder reranking
        fetch_k = max(retrieval_k * 3, 20)

        # Retrieve chunks with doc type boosting
        try:
            retrieved_chunks = indexer.query(
                query_embedding=query_embedding,
                project_ids=project_ids_to_search,
                top_k=fetch_k,
                diversity=False,  # Diversity applied after reranking
                doc_type_hints=doc_type_hints,
            )
        except Exception as e:
            err_msg = str(e)
            if "Error finding id" in err_msg or "Error executing plan" in err_msg:
                logger.error(f"ChromaDB index corrupted: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "The search index is corrupted and needs to be rebuilt. "
                        "POST /api/v1/admin/index/rebuild to fix this."
                    ),
                )
            raise

        # If no results with expanded query, try alternative formulations
        if not retrieved_chunks:
            logger.info("No results with expanded query, trying alternatives...")
            for alt_query in query_expander.rewrite_query(request.query):
                alt_embedding = embedder.embed_query(alt_query)
                retrieved_chunks = indexer.query(
                    query_embedding=alt_embedding,
                    project_ids=project_ids_to_search,
                    top_k=fetch_k,
                    diversity=False,
                    doc_type_hints=doc_type_hints,
                )
                if retrieved_chunks:
                    logger.info(f"Found results with alternative query: '{alt_query}'")
                    break

        # Cross-encoder reranking: rerank top candidates to top-10
        if len(retrieved_chunks) > 1:
            retrieved_chunks = reranker.rerank(
                query=request.query,
                chunks=retrieved_chunks,
                top_k=max(retrieval_k * 2, 10),
            )

        # Apply diversity filtering after reranking
        if len(retrieved_chunks) > retrieval_k:
            retrieved_chunks = indexer._apply_diversity(
                retrieved_chunks, retrieval_k, max_per_document=2
            )

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
        
        # Run intent handlers
        personnel_data = _handle_personnel(request, router_result)
        file_location_data = _handle_file_location(request, router_result)
        duplicate_data = _handle_duplicate_detection(request, router_result)
        ajera_team_data = personnel_data  # backward compat alias

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
                    intents=[i.value for i in router_result.intents],
                    personnel_data=personnel_data,
                    file_location=file_location_data,
                    duplicate_info=duplicate_data,
                )
                _log_query(request, response, router_result)
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
                intents=[i.value for i in router_result.intents],
                personnel_data=personnel_data,
                file_location=file_location_data,
                duplicate_info=duplicate_data,
            )
            _log_query(request, response, router_result)
            return response

        # Build QA prompt
        qa_template = load_prompt_template("qa_prompt")

        # Convert absolute paths to relative for LLM (cleaner, prevents path leakage)
        base_docs_path = settings.raw_docs_path
        candidates = []
        for chunk in retrieved_chunks[:8]:  # Increased from 6 — more context for 8K model
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
                "text": chunk["text"][:1500],
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
        
        # Merge supplementary context from intent handlers
        candidates_text = _merge_supplementary_context(
            candidates_text, personnel_data, file_location_data, duplicate_data
        )

        # Replace placeholders
        prompt = qa_template.replace("<<CHAT_HISTORY>>", history_text)
        prompt = prompt.replace("<<USER_QUERY>>", request.query)
        prompt = prompt.replace("<<CANDIDATES>>", candidates_text)

        # Generate answer
        logger.info(f"Generating answer for query: {request.query[:50]}")
        llm_output = llm_client.generate_json(prompt, max_tokens=1024)

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
        base_docs_path = settings.raw_docs_path
        
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
            intents=[i.value for i in router_result.intents],
            personnel_data=personnel_data,
            file_location=file_location_data,
            duplicate_info=duplicate_data,
        )

        # Log query
        _log_query(request, response, router_result)

        return response

    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------

def _handle_personnel(request: QueryRequest, router_result: RouterResult):
    """Handle PERSONNEL intent: fetch Ajera team data for the project."""
    if not router_result.has_personnel:
        return None

    if not request.project_ids or len(request.project_ids) != 1:
        return None

    try:
        resolver = get_project_resolver()
        project_folder = request.project_ids[0]

        team = resolver.get_project_team_from_folder(project_folder)
        if team:
            top_team = team[:10]
            result = {
                "total_employees": len(team),
                "top_employees": top_team,
                "project_folder": project_folder,
            }
            logger.info(f"Team query: Found {len(team)} employees for project folder '{project_folder}'")
            return result
        else:
            logger.info(f"Team query: No Ajera records found for folder '{project_folder}'")
    except Exception as e:
        logger.warning(f"Error getting Ajera team data: {e}")

    return None


def _handle_file_location(request: QueryRequest, router_result: RouterResult):
    """Handle FILE_LOCATION intent: find where project files are stored on network drives."""
    if not router_result.has_file_location:
        return None

    directory_index = get_directory_index()
    if directory_index is None:
        logger.info("[ROUTER] FILE_LOCATION intent detected but directory_index not available")
        return {
            "status": "not_available",
            "message": "File location search is not yet configured.",
            "detected_drive": router_result.drive_mention,
        }

    if not directory_index.is_available():
        return {
            "status": "not_available",
            "message": "Directory index has no scan data. An admin needs to run a drive scan first.",
            "detected_drive": router_result.drive_mention,
        }

    # Use project_id from request if available, otherwise search by query text
    project_id = request.project_ids[0] if request.project_ids and len(request.project_ids) == 1 else None

    results = directory_index.search_project_location(
        query=request.query,
        project_id=project_id,
        limit=5,
    )

    if results:
        return {
            "status": "found",
            "locations": results,
            "detected_drive": router_result.drive_mention,
        }
    else:
        return {
            "status": "not_found",
            "message": "No matching project directories found in the directory index.",
            "detected_drive": router_result.drive_mention,
        }


def _handle_duplicate_detection(request: QueryRequest, router_result: RouterResult):
    """Handle DUPLICATE_DETECTION intent: check for duplicate project directories."""
    if not router_result.has_duplicate_detection:
        return None

    directory_index = get_directory_index()
    if directory_index is None:
        logger.info("[ROUTER] DUPLICATE_DETECTION intent detected but directory_index not available")
        return {
            "status": "not_available",
            "message": "Duplicate detection is not yet configured.",
        }

    if not directory_index.is_available():
        return {
            "status": "not_available",
            "message": "Directory index has no scan data. An admin needs to run a drive scan first.",
        }

    # Check for duplicates
    project_id = request.project_ids[0] if request.project_ids and len(request.project_ids) == 1 else None

    results = directory_index.find_duplicates(
        query=request.query,
        project_id=project_id,
        limit=10,
    )

    if results:
        return {
            "status": "checked",
            "duplicates": results,
        }
    else:
        return {
            "status": "checked",
            "duplicates": [],
            "message": "No duplicate project directories found.",
        }


def _merge_supplementary_context(
    candidates_text: str,
    personnel_data,
    file_location_data,
    duplicate_data,
) -> str:
    """
    Merge supplementary data from secondary intents into the LLM context.

    Follows the existing pattern where Ajera team data is appended as a
    labeled section in the candidates text.
    """
    # Personnel data
    if personnel_data and personnel_data.get("top_employees"):
        team_list = "\n".join([
            f"  - {emp['name']} (Employee {emp['employee_id']}): {emp['total_hours']} hours logged"
            for emp in personnel_data["top_employees"]
        ])
        total = personnel_data["total_employees"]
        showing = len(personnel_data["top_employees"])
        more = f" (showing top {showing} by hours)" if total > showing else ""

        candidates_text += (
            f"\n\n[AJERA TIME TRACKING DATA]\n"
            f"Total employees who logged time: {total}{more}\n{team_list}"
        )
        logger.info(f"Added Ajera team context for {total} employees")

    # File location data (phase 2)
    if file_location_data and file_location_data.get("status") == "found":
        locations = file_location_data.get("locations", [])
        loc_text = "\n".join([
            f"  - {loc['path']} ({loc.get('drive', 'unknown drive')})"
            for loc in locations
        ])
        candidates_text += f"\n\n[PROJECT FILE LOCATIONS]\n{loc_text}"

    # Duplicate data (phase 2)
    if duplicate_data and duplicate_data.get("status") == "checked":
        duplicates = duplicate_data.get("duplicates", [])
        if duplicates:
            dup_text = "\n".join([
                f"  - {d['path']} (matches: {d.get('match_reason', 'name')})"
                for d in duplicates
            ])
            candidates_text += (
                f"\n\n[DUPLICATE DIRECTORY DETECTION]\n"
                f"Found {len(duplicates)} potential duplicates:\n{dup_text}"
            )
        else:
            candidates_text += "\n\n[DUPLICATE DIRECTORY DETECTION]\nNo duplicates found."

    return candidates_text


def _log_query(request: QueryRequest, response: QueryResponse, router_result: RouterResult = None):
    """Log query to queries.log."""
    try:
        log_file = settings.queries_log_path
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Get employee_id_resolved from outer scope if available
        employee_id_for_log = getattr(query_documents, '_employee_id_resolved', request.employee_id)

        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "project_ids": request.project_ids,
            "employee_id": employee_id_for_log,
            "query": request.query,
            "intents": [i.value for i in router_result.intents] if router_result else [],
            "top_chunk_ids": [c.chunk_id for c in response.citations],
            "confidence": response.confidence,
            "elapsed_ms": response.elapsed_ms,
            "stub_mode": response.stub_mode,
        }

        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')

    except Exception as e:
        logger.error(f"Failed to log query: {e}")
