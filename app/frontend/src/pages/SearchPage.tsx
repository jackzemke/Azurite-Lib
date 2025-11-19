import React, { useState, useEffect } from 'react'
import axios from 'axios'
import ResultCard from '../components/ResultCard'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface Citation {
  project_id: string
  file_path: string
  page: number
  chunk_id: string
  text_excerpt: string
}

interface QueryResponse {
  answer: string
  citations: Citation[]
  confidence: string
  elapsed_ms: number
  stub_mode: boolean
}

interface Project {
  project_id: string
  document_count: number
  chunk_count: number
}

export default function SearchPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjects, setSelectedProjects] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<QueryResponse | null>(null)
  const [error, setError] = useState('')
  const [searchFilter, setSearchFilter] = useState('')

  useEffect(() => {
    // Fetch available projects on mount
    axios.get(`${API_URL}/api/v1/projects`)
      .then(res => setProjects(res.data.projects))
      .catch(err => console.error('Failed to load projects:', err))
  }, [])

  const handleToggleProject = (projectId: string) => {
    setSelectedProjects(prev =>
      prev.includes(projectId)
        ? prev.filter(id => id !== projectId)
        : [...prev, projectId]
    )
  }

  const handleSelectAll = () => {
    setSelectedProjects(projects.map(p => p.project_id))
  }

  const handleClearAll = () => {
    setSelectedProjects([])
  }

  const filteredProjects = projects.filter(p =>
    p.project_id.toLowerCase().includes(searchFilter.toLowerCase())
  )

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (!query.trim()) {
      setError('Please enter a query')
      return
    }

    setLoading(true)
    setError('')
    setResult(null)

    try {
      const payload: any = {
        query: query,
        k: 6,
      }
      
      // Only include project_ids if specific projects are selected
      if (selectedProjects.length > 0 && selectedProjects.length < projects.length) {
        payload.project_ids = selectedProjects
      }
      // If all projects selected or none selected, omit project_ids (searches all)

      const response = await axios.post(`${API_URL}/api/v1/query`, payload)
      setResult(response.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Query failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <h2>Search Documents</h2>

      <form onSubmit={handleSearch}>
        <div className="form-group">
          <label>
            Projects to Search 
            {selectedProjects.length === 0 || selectedProjects.length === projects.length
              ? <span style={{color: '#0066cc', marginLeft: '8px'}}>(All Projects)</span>
              : <span style={{color: '#666', marginLeft: '8px'}}>({selectedProjects.length} selected)</span>
            }
          </label>
          
          <div style={{marginBottom: '8px', display: 'flex', gap: '8px'}}>
            <button type="button" onClick={handleSelectAll} style={{fontSize: '13px', padding: '4px 12px'}}>
              Select All
            </button>
            <button type="button" onClick={handleClearAll} style={{fontSize: '13px', padding: '4px 12px'}}>
              Clear All
            </button>
            <input
              type="text"
              placeholder="Filter projects..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              style={{flex: 1, fontSize: '13px'}}
            />
          </div>

          <div style={{
            border: '1px solid #ddd',
            borderRadius: '4px',
            maxHeight: '200px',
            overflowY: 'auto',
            padding: '8px',
            backgroundColor: '#f9f9f9'
          }}>
            {filteredProjects.length === 0 ? (
              <div style={{padding: '12px', color: '#999', textAlign: 'center'}}>
                No projects available
              </div>
            ) : (
              filteredProjects.map(project => (
                <label
                  key={project.project_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '6px 8px',
                    cursor: 'pointer',
                    borderRadius: '4px',
                    transition: 'background 0.2s'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#e8f4f8'}
                  onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                >
                  <input
                    type="checkbox"
                    checked={selectedProjects.includes(project.project_id)}
                    onChange={() => handleToggleProject(project.project_id)}
                    style={{marginRight: '8px'}}
                  />
                  <span style={{flex: 1}}>
                    <strong>{project.project_id}</strong>
                    <span style={{color: '#666', fontSize: '13px', marginLeft: '8px'}}>
                      ({project.document_count} docs, {project.chunk_count} chunks)
                    </span>
                  </span>
                </label>
              ))
            )}
          </div>
        </div>

        <div className="form-group">
          <label>Query</label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g., What was the pipe diameter for drainage at Area B?"
            required
          />
        </div>

        <button type="submit" className="btn" disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {result && <ResultCard result={result} />}
    </div>
  )
}
