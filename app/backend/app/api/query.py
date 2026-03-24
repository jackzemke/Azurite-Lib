"""
Query endpoint for Q&A.
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import time
import json
import logging
from datetime import datetime, timezone
import re
from typing import Optional

from ..config import settings
from ..schemas.models import QueryRequest, QueryResponse, Citation, ProjectResult
from ..core.ajera_loader import get_ajera_data
from ..core.project_resolver import get_project_resolver
from ..core.query_router import classify_query, QueryIntent, RouterResult
from ..services import get_embedder, get_indexer, get_llm_client, get_reranker, get_query_expander, get_directory_index, get_metadata_indexer

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
        router_result = classify_query(request.query)

        # PROJECT_SEARCH: primary flow for metadata-based project finding
        project_search_result = _handle_project_search(request, router_result, start_time)
        if project_search_result is not None:
            _log_query(
                request,
                project_search_result,
                router_result,
                employee_id_resolved=employee_id_resolved,
                retrieval_count=len(project_search_result.projects or []),
                used_fallback=False,
            )
            return project_search_result

        is_team_query = router_result.is_team_query
        is_broad_query = router_result.is_broad_query
        retrieval_k = min(request.k * 2, 15) if is_broad_query else request.k

        # Run intent handlers early so deterministic paths can short-circuit LLM.
        personnel_data = _handle_personnel(request, router_result)
        file_location_data = _handle_file_location(request, router_result)
        duplicate_data = _handle_duplicate_detection(request, router_result)
        ajera_team_data = personnel_data  # backward compat alias

        employee_history_data = _handle_employee_history(request, router_result, employee_id_resolved, force_ajera=request.force_ajera_search)

        if employee_history_data:
            requested_count = employee_history_data["requested_count"]
            recent_projects = employee_history_data["recent_projects"]
            project_lines = "\n".join([
                f"{idx + 1}. {proj['name']}"
                + (f" [{proj['file_id']}]" if proj.get('file_id') else "")
                + (f" - last activity {proj['last_activity']}" if proj.get('last_activity') else "")
                for idx, proj in enumerate(recent_projects)
            ])

            response = QueryResponse(
                answer=(
                    f"According to Ajera timesheets, the last {min(requested_count, len(recent_projects))} "
                    f"project{'s' if min(requested_count, len(recent_projects)) != 1 else ''} worked on by "
                    f"{employee_history_data['employee_name']} {'were' if len(recent_projects) != 1 else 'was'}:\n\n"
                    f"{project_lines}"
                ),
                citations=[],
                confidence="high",
                elapsed_ms=int((time.time() - start_time) * 1000),
                stub_mode=llm_client.is_stub_mode(),
                intents=[i.value for i in router_result.intents],
                personnel_data=employee_history_data,
                file_location=file_location_data,
                duplicate_info=duplicate_data,
            )
            _log_query(
                request,
                response,
                router_result,
                employee_id_resolved=employee_id_resolved,
                retrieval_count=0,
                used_fallback=False,
            )
            return response

        # Deterministic lane first for locate queries.
        if router_result.has_file_location and file_location_data and file_location_data.get("status") == "found":
            locations = file_location_data.get("locations", [])
            location_lines = "\n".join([
                f"- {loc['path']} ({loc.get('drive_name') or loc.get('drive_letter', 'unknown drive')})"
                for loc in locations
            ])

            response = QueryResponse(
                answer=(
                    "I found matching project file locations in the directory index:\n\n"
                    f"{location_lines}"
                ),
                citations=[],
                confidence="high",
                elapsed_ms=int((time.time() - start_time) * 1000),
                stub_mode=llm_client.is_stub_mode(),
                intents=[i.value for i in router_result.intents],
                personnel_data=personnel_data,
                file_location=file_location_data,
                duplicate_info=duplicate_data,
            )
            _log_query(
                request,
                response,
                router_result,
                employee_id_resolved=employee_id_resolved,
                retrieval_count=0,
                used_fallback=False,
            )
            return response

        # Expand query for better semantic matching
        expanded_query = query_expander.expand_query(request.query)
        
        # Get document type hints for boosting relevant document types
        doc_type_hints = query_expander.get_doc_type_hints(request.query)
        if doc_type_hints:
            logger.info(f"Doc type hints for query: {doc_type_hints}")
        
        # Embed expanded query (uses search_query: prefix for nomic model)
        query_embedding = embedder.embed_query(expanded_query)

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
                _log_query(
                    request,
                    response,
                    router_result,
                    employee_id_resolved=employee_id_resolved,
                    retrieval_count=0,
                    used_fallback=True,
                )
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
            _log_query(
                request,
                response,
                router_result,
                employee_id_resolved=employee_id_resolved,
                retrieval_count=0,
                used_fallback=True,
            )
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
            f"Q: {h.get('query', '')}\nA: {h.get('answer', '')}"
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
        _log_query(
            request,
            response,
            router_result,
            employee_id_resolved=employee_id_resolved,
            retrieval_count=len(retrieved_chunks),
            used_fallback=False,
        )

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


def _handle_employee_history(request: QueryRequest, router_result: RouterResult, employee_id_resolved: str, force_ajera: Optional[bool] = None):
    """Handle employee-scoped history queries directly from Ajera timesheets."""
    if not employee_id_resolved or not _is_employee_history_query(request.query, router_result, force_ajera=force_ajera):
        return None

    try:
        ajera = get_ajera_data()
        employee_name = ajera.get_employee_name(employee_id_resolved)
        if not employee_name or not ajera.data:
            return None

        requested_count = _extract_requested_project_count(request.query)
        emp_data = ajera.data.get("employee_to_projects", {}).get(str(employee_id_resolved), {})
        timeline = emp_data.get("timeline", {})
        project_keys = emp_data.get("projects", [])

        # Build projects with deduplication.
        # Prefer business identity (file_id/name) over raw project_key to avoid
        # returning the same visible project multiple times.
        seen_keys = set()
        recent_projects = []
        for project_key in project_keys:
            entries = timeline.get(project_key, [])
            dates = [entry.get("date") for entry in entries if entry.get("date")]
            last_activity = max(dates) if dates else None

            project_info = ajera.get_project_info(project_key) or {}
            metadata = project_info.get("metadata", {})
            file_id = str(metadata.get("project_id") or "").strip()
            name = (project_info.get("name") or f"Project {project_key}").strip()

            dedupe_key = (file_id.lower(), name.lower()) if (file_id or name) else (str(project_key),)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            recent_projects.append({
                "project_key": project_key,
                "file_id": metadata.get("project_id"),
                "name": name,
                "last_activity": last_activity,
            })

        # Sort by most recent activity and limit to requested count
        recent_projects.sort(key=lambda project: project.get("last_activity") or "", reverse=True)
        recent_projects = recent_projects[:requested_count]

        if not recent_projects:
            return None

        return {
            "mode": "employee_history",
            "employee_id": employee_id_resolved,
            "employee_name": employee_name,
            "requested_count": requested_count,
            "total_projects": len(seen_keys),  # Total unique projects for employee
            "recent_projects": recent_projects,
        }
    except Exception as e:
        logger.warning(f"Error getting employee history data: {e}")
        return None


def _is_employee_history_query(query: str, router_result: RouterResult, force_ajera: Optional[bool] = None) -> bool:
    """Return True when the query is asking about an employee's project history."""
    # Allow manual override
    if force_ajera is True:
        return True
    if force_ajera is False:
        return False

    query_lower = query.lower()
    
    # Broader history patterns: asking about work DONE BY the employee
    history_patterns = [
        r"\b(last|latest|recent|most recent)\s+\d*\s*(projects?|assignments?)",
        r"\b(last|latest|recent|most recent)\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s*(projects?|assignments?)",
        r"\b(projects?|assignments?)\s+of\s+([a-z]+\s*){1,4}",
        r"\b(projects?|assignments?)\s+(this|the)\s+(person|individual|employee|workers?)\s+(worked on|was involved in|did)",
        r"(worked|has worked|did work)\s+on\s+(what|which)",
        r"\bhistory\b.*\b(projects?|assignments?)",
        r"\b(projects?|work|assignments?)\s+of\s+(this|the)\s+(person|individual|employee)",
        r"\bexperience\b.*\b(projects?|work|assignments?)",
        r"\b(what|which)\s+(projects?|work|assignments?)\s+(this|the)\s+(person|employee|individual)",
        r"\b(past|previous)\s+(projects?|work|assignments?)",
    ]

    pattern_match = any(re.search(pattern, query_lower) for pattern in history_patterns)

    # Prefer explicit pattern matches; fallback to router signal when it's already personnel intent.
    if pattern_match:
        return True

    return router_result.has_personnel and any(
        token in query_lower for token in ["project", "projects", "assignment", "assignments", "worked on", "history"]
    )


def _extract_requested_project_count(query: str, default: int = 3, maximum: int = 10) -> int:
    """Extract a small requested count from natural language such as 'last three projects'."""
    digit_match = re.search(r"\b(\d{1,2})\b", query)
    if digit_match:
        return min(max(int(digit_match.group(1)), 1), maximum)

    word_to_number = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    query_lower = query.lower()
    for word, value in word_to_number.items():
        if re.search(rf"\b{word}\b", query_lower):
            return min(value, maximum)

    return default


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


def _handle_project_search(request: QueryRequest, router_result: RouterResult, start_time: float) -> Optional[QueryResponse]:
    """Handle PROJECT_SEARCH intent: semantic search over project metadata."""
    if not router_result.has_project_search:
        return None

    try:
        embedder = get_embedder()
        metadata_indexer = get_metadata_indexer()
        llm_client = get_llm_client()
        query_expander = get_query_expander()

        is_team_query = router_result.is_team_query or router_result.has_personnel

        # Resolve conversational references like "that project" for personnel queries.
        # Prefer explicit request.project_ids; otherwise infer from the latest answer.
        resolved_project_ids = list(request.project_ids or [])
        if (
            not resolved_project_ids
            and is_team_query
            and _is_contextual_project_reference(request.query)
        ):
            inferred_project_id = _infer_project_id_from_chat_history(request.chat_history)
            if inferred_project_id:
                resolved_project_ids = [inferred_project_id]
                logger.info(
                    f"[PROJECT_SEARCH] Resolved contextual follow-up to project_id={inferred_project_id}"
                )

        # If we have one explicit project id (request or inferred), use direct lookup.
        raw_matches = []
        if len(resolved_project_ids) == 1:
            direct_match = metadata_indexer.get_project_by_id(resolved_project_ids[0])
            if direct_match:
                raw_matches = [direct_match]
            else:
                logger.info(
                    f"[PROJECT_SEARCH] Direct metadata lookup missed project_id={resolved_project_ids[0]}, falling back to semantic search"
                )

        # Semantic search fallback / default path
        if not raw_matches:
            # Expand query for metadata search (lighter expansion)
            expanded_query = query_expander.expand_for_metadata(request.query)

            # Embed and search metadata collection — fetch more candidates than needed
            query_embedding = embedder.embed_query(expanded_query)
            raw_matches = metadata_indexer.query(query_embedding=query_embedding, top_k=min(request.k * 2, 10))

        # Filter by cosine distance — only keep genuinely relevant results.
        # Cosine distance: 0 = identical, 2 = opposite.
        # With small collections, embeddings are compressed — use tighter threshold.
        DISTANCE_THRESHOLD = 0.55
        matches = [m for m in raw_matches if m.get("distance", 2.0) < DISTANCE_THRESHOLD]

        # Also drop results that are much worse than the best match.
        # E.g. best=0.30 → cut anything beyond 0.30 + 0.25 = 0.55 gap from best.
        if matches and len(matches) > 1:
            best_dist = matches[0].get("distance", 0.0)
            matches = [m for m in matches if m.get("distance", 2.0) <= best_dist + 0.25]

        # If nothing passed the threshold, keep only the single best if it's
        # at least somewhat related (< 1.0), so the user gets *something*.
        if not matches and raw_matches and raw_matches[0].get("distance", 2.0) < 1.0:
            matches = [raw_matches[0]]

        # Cap to requested k
        matches = matches[:request.k]

        raw_dists = [f"{m.get('distance', 0):.3f}" for m in raw_matches[:6]]
        kept_dists = [f"{m.get('distance', 0):.3f}" for m in matches]
        logger.info(
            f"[PROJECT_SEARCH] raw={len(raw_matches)} dists={raw_dists} | "
            f"kept={len(matches)} dists={kept_dists} (threshold={DISTANCE_THRESHOLD})"
        )

        if not matches:
            return QueryResponse(
                answer="No matching projects found in the metadata index.",
                citations=[],
                confidence="low",
                elapsed_ms=int((time.time() - start_time) * 1000),
                stub_mode=llm_client.is_stub_mode(),
                intents=[i.value for i in router_result.intents],
                projects=[],
            )

        # Build ProjectResult list and LLM candidates text
        projects_out = []
        candidates_lines = []
        team_data_all = {}

        from ..core.project_mapper import get_project_mapper
        from ..core.ajera_loader import get_ajera_data

        for match in matches:
            meta = match["metadata"]
            project_id = meta.get("project_id", "")

            # Resolve Ajera team data
            team_count = None
            try:
                mapper = get_project_mapper()
                ajera = get_ajera_data()
                project_key = mapper.get_project_key(project_id)

                resolved_team_key = None
                if project_key:
                    # Prefer direct match when parent key has time entries.
                    if ajera.data and project_key in ajera.data.get("project_to_employees", {}):
                        resolved_team_key = project_key
                    else:
                        # Fallback: some archive IDs map to parent keys while
                        # time entries live on child keys.
                        for child_key in mapper.get_children_keys(project_key):
                            if ajera.data and child_key in ajera.data.get("project_to_employees", {}):
                                resolved_team_key = child_key
                                break

                # Last resort: file ID itself may be an Ajera key.
                if not resolved_team_key and ajera.data and project_id in ajera.data.get("project_to_employees", {}):
                    resolved_team_key = project_id

                if resolved_team_key:
                    team = ajera.get_project_team_with_hours(resolved_team_key)
                    if team:
                        team_count = len(team)
                        team_data_all[project_id] = {
                            "total_employees": team_count,
                            "top_employees": [
                                {"employee_id": m["employee_id"], "name": m["name"], "total_hours": m["total_hours"]}
                                for m in team[:10]
                            ],
                        }
                elif project_key:
                    logger.debug(
                        f"Team lookup: mapped project_id={project_id} to parent key {project_key}, "
                        "but no Ajera time-bearing key found"
                    )
            except Exception as e:
                logger.debug(f"Team data lookup failed for {project_id}: {e}")

            pr = ProjectResult(
                project_id=project_id,
                project_name=meta.get("project_name", ""),
                department=meta.get("department") or None,
                client=meta.get("client") or None,
                start_date=meta.get("start_date") or None,
                end_date=meta.get("end_date") or None,
                scope_type=meta.get("scope_type") or None,
                full_path=meta.get("full_path") or None,
                team_count=team_count,
                distance=match.get("distance"),
            )
            projects_out.append(pr)

            # Build candidate text for LLM
            line = match["text"]
            if team_count:
                line += f"\nTeam: {team_count} members logged hours"
                # Include full team list for personnel queries
                if is_team_query and project_id in team_data_all:
                    team_lines = "\n".join([
                        f"  - {emp['name']} (ID {emp['employee_id']}): {emp['total_hours']} hours"
                        for emp in team_data_all[project_id]["top_employees"]
                    ])
                    line += f"\nTeam members:\n{team_lines}"
            elif is_team_query:
                # Explicitly signal absence so the LLM doesn't invent staff counts/names
                line += "\nTeam data: Not available in Ajera for this project."
            candidates_lines.append(line)

        # Build prompt for LLM
        prompt_template = load_prompt_template("project_search_prompt")

        history_text = "None" if not request.chat_history else "\n".join([
            f"Q: {h.get('query', '')}\nA: {h.get('answer', '')}"
            for h in request.chat_history[-3:]
        ])

        candidates_text = "\n\n---\n\n".join(candidates_lines)

        prompt = prompt_template.replace("<<CHAT_HISTORY>>", history_text)
        prompt = prompt.replace("<<USER_QUERY>>", request.query)
        prompt = prompt.replace("<<CANDIDATES>>", candidates_text)

        llm_output = llm_client.generate_json(prompt, max_tokens=1024)

        if not isinstance(llm_output, dict):
            llm_output = {"answer": "Found matching projects but could not generate summary.", "confidence": "medium"}

        answer = llm_output.get("answer", "Found matching projects.")
        confidence = llm_output.get("confidence", "medium")

        # Use relevant_ids from LLM to filter down to only the projects it
        # actually selected as matches. This lets the LLM do semantic filtering
        # rather than relying solely on distance thresholds.
        relevant_ids = llm_output.get("relevant_ids")
        if relevant_ids and isinstance(relevant_ids, list):
            relevant_set = set(str(rid) for rid in relevant_ids)
            filtered_projects = [p for p in projects_out if p.project_id in relevant_set]
            filtered_team = {k: v for k, v in team_data_all.items() if k in relevant_set}
            logger.info(
                f"[PROJECT_SEARCH] LLM selected {len(filtered_projects)}/{len(projects_out)} "
                f"projects via relevant_ids: {relevant_ids}"
            )
        else:
            filtered_projects = projects_out
            filtered_team = team_data_all

        response = QueryResponse(
            answer=answer,
            citations=[],
            confidence=confidence,
            elapsed_ms=int((time.time() - start_time) * 1000),
            stub_mode=llm_client.is_stub_mode(),
            intents=[i.value for i in router_result.intents],
            projects=filtered_projects,
            team_data=filtered_team if filtered_team else None,
        )

        return response

    except Exception as e:
        logger.error(f"Project search failed: {e}")
        return None


def _is_contextual_project_reference(query: str) -> bool:
    """Return True when query refers to a previously mentioned project."""
    q = (query or "").strip().lower()
    if not q:
        return False

    patterns = [
        r"\bthat project\b",
        r"\bthat one\b",
        r"\bon that project\b",
        r"\bon that one\b",
        r"\bwho worked on that\b",
        r"\bwho was on that\b",
    ]
    return any(re.search(pattern, q) for pattern in patterns)


def _infer_project_id_from_chat_history(chat_history) -> Optional[str]:
    """Infer most recent project ID from chat history answers."""
    if not chat_history:
        return None

    for turn in reversed(chat_history):
        answer = str(turn.get("answer", ""))
        # Ajera/file IDs are typically 6-8 digits in this workspace.
        ids = re.findall(r"\b\d{6,8}\b", answer)
        if ids:
            return ids[0]

    return None


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
            f"  - {loc['path']} ({loc.get('drive_name') or loc.get('drive_letter', 'unknown drive')})"
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


def _log_query(
    request: QueryRequest,
    response: QueryResponse,
    router_result: RouterResult = None,
    employee_id_resolved: str = None,
    retrieval_count: int = 0,
    used_fallback: bool = False,
):
    """Log query to queries.log."""
    try:
        log_file = settings.queries_log_path
        log_file.parent.mkdir(parents=True, exist_ok=True)

        employee_id_for_log = employee_id_resolved or request.employee_id
        intent_class = _get_primary_intent_class(router_result)

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + 'Z',
            "project_ids": request.project_ids,
            "employee_id": employee_id_for_log,
            "query": request.query,
            "intents": [i.value for i in router_result.intents] if router_result else [],
            "intent_class": intent_class,
            "top_chunk_ids": [c.chunk_id for c in response.citations],
            "retrieval_count": retrieval_count,
            "fallback_used": used_fallback,
            "confidence": response.confidence,
            "elapsed_ms": response.elapsed_ms,
            "stub_mode": response.stub_mode,
        }

        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')

    except Exception as e:
        logger.error(f"Failed to log query: {e}")


def _get_primary_intent_class(router_result: RouterResult = None) -> str:
    """Return a single primary intent class for observability dashboards."""
    if not router_result or not router_result.intents:
        return QueryIntent.DOCUMENT_QA.value

    for intent in router_result.intents:
        if intent != QueryIntent.DOCUMENT_QA:
            return intent.value

    return QueryIntent.DOCUMENT_QA.value
