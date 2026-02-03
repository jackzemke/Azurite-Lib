import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface Citation {
  project_id: string
  file_path: string
  page: number
  chunk_id: string
  text_excerpt: string
}

interface Project {
  project_id: string
  document_count: number
  chunk_count: number
}

interface Employee {
  employee_id: string
  name: string
  project_count: number
}

interface Message {
  id: string
  type: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  confidence?: string
  elapsed_ms?: number
  stub_mode?: boolean
  timestamp: Date
}

interface SearchPageProps {
  onOpenUpload?: () => void
  onOpenHelp?: () => void
}

export default function SearchPage({ onOpenUpload, onOpenHelp }: SearchPageProps) {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjects, setSelectedProjects] = useState<string[]>([]) // Empty = all projects
  const [employees, setEmployees] = useState<Employee[]>([])
  const [selectedEmployee, setSelectedEmployee] = useState<string>('') // Empty = no employee filter
  const [employeeSearchQuery, setEmployeeSearchQuery] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState(0) // 0=embedding, 1=searching, 2=processing, 3=synthesizing
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState('')
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const [isEmployeeDropdownOpen, setIsEmployeeDropdownOpen] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    // Fetch available projects on mount
    axios.get(`${API_URL}/api/v1/projects`)
      .then(res => setProjects(res.data.projects))
      .catch(err => console.error('Failed to load projects:', err))
    
    // Fetch employees (all of them)
    axios.get(`${API_URL}/api/v1/employees?limit=500`)
      .then(res => {
        // Sort alphabetically by name
        const sorted = res.data.sort((a: Employee, b: Employee) => 
          a.name.localeCompare(b.name)
        )
        setEmployees(sorted)
      })
      .catch(err => console.error('Failed to load employees:', err))
  }, [])

  useEffect(() => {
    // Close dropdowns when clicking outside
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement
      if (!target.closest('.project-dropdown')) {
        setIsDropdownOpen(false)
      }
      if (!target.closest('.employee-dropdown')) {
        setIsEmployeeDropdownOpen(false)
      }
    }

    if (isDropdownOpen || isEmployeeDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isDropdownOpen, isEmployeeDropdownOpen])

  const handleToggleProject = (projectId: string) => {
    setSelectedProjects(prev => {
      if (prev.includes(projectId)) {
        return prev.filter(id => id !== projectId)
      } else {
        return [...prev, projectId]
      }
    })
  }

  const isAllSelected = selectedProjects.length === 0
  
  const getDisplayText = () => {
    if (selectedProjects.length === 0) return 'All Projects'
    if (selectedProjects.length === 1) return selectedProjects[0]
    return `${selectedProjects.length} Projects Selected`
  }

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (!query.trim()) {
      setError('Please enter a message')
      return
    }

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: query.trim(),
      timestamp: new Date()
    }

    setMessages(prev => [...prev, userMessage])
    setQuery('')
    setLoading(true)
    setLoadingStage(0)
    setError('')

    // Animate loading stages
    const stageInterval = setInterval(() => {
      setLoadingStage(prev => (prev < 3 ? prev + 1 : prev))
    }, 2000) // Change stage every 2 seconds

    try {
      const payload: any = {
        query: userMessage.content,
        k: 6,
      }
      
      // Include employee_id if selected (overrides project selection)
      if (selectedEmployee) {
        payload.employee_id = selectedEmployee
      } else if (selectedProjects.length > 0) {
        // Only include project_ids if specific projects are selected and no employee
        payload.project_ids = selectedProjects
      }

      const response = await axios.post(`${API_URL}/api/v1/query`, payload)
      
      // Add assistant message
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: response.data.answer,
        citations: response.data.citations,
        confidence: response.data.confidence,
        elapsed_ms: response.data.elapsed_ms,
        stub_mode: response.data.stub_mode,
        timestamp: new Date()
      }

      setMessages(prev => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to get response. Please try again.')
      // Remove the user message if the request failed
      setMessages(prev => prev.filter(m => m.id !== userMessage.id))
    } finally {
      clearInterval(stageInterval)
      setLoading(false)
      setLoadingStage(0)
      inputRef.current?.focus()
    }
  }

  const handleCitationClick = (citation: Citation) => {
    // Open document in new tab
    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
    const documentUrl = `${API_URL}/api/v1/projects/${citation.project_id}/documents/${encodeURIComponent(citation.file_path)}`
    
    console.log('Opening document:', documentUrl)
    console.log('Citation details:', citation)
    
    window.open(documentUrl, '_blank')
  }

  return (
    <div className="chat-container">
      {/* Header */}
      <div className="chat-header">
        <div style={{display: 'flex', alignItems: 'center', gap: '1rem'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
            {/* <span style={{fontSize: '1.5rem'}}>💎</span> */}
            <h2 style={{margin: 0, fontSize: '1.25rem', fontWeight: 600, background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent'}}>Azurite Archive Assistant</h2>
          </div>
          {onOpenUpload && (
            <button
              onClick={onOpenUpload}
              style={{
                padding: '0.5rem 1rem',
                backgroundColor: '#667eea',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                fontSize: '0.875rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#5568d3'
                e.currentTarget.style.transform = 'translateY(-1px)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = '#667eea'
                e.currentTarget.style.transform = 'translateY(0)'
              }}
            >
              <span style={{fontSize: '1.1rem'}}>+</span>
              Upload Documents
            </button>
          )}
          {onOpenHelp && (
            <button
              onClick={onOpenHelp}
              title="Help & Tips"
              style={{
                padding: '0.5rem 0.75rem',
                backgroundColor: 'transparent',
                color: '#667eea',
                border: '1.5px solid #667eea',
                borderRadius: '6px',
                fontSize: '1rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#667eea'
                e.currentTarget.style.color = 'white'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
                e.currentTarget.style.color = '#667eea'
              }}
            >
              ?
            </button>
          )}
        </div>
        <div>
          {projects.length > 0 && (
            <p style={{margin: '0.25rem 0 0 0', color: '#9ca3af', fontSize: '0.85rem'}}>
              {projects.reduce((sum, p) => sum + p.chunk_count, 0).toLocaleString()} chunks • {' '}
              {selectedEmployee ? `Filtered to ${employees.find(e => e.employee_id === selectedEmployee)?.name || 'employee'}` : 
               selectedProjects.length === 0 ? 'All projects' : `${selectedProjects.length} project${selectedProjects.length > 1 ? 's' : ''}`}
            </p>
          )}
          <p style={{margin: '0.35rem 0 0 0', color: '#9ca3af', fontSize: '0.75rem'}}>
            Employee filter uses Ajera timesheets • Project filter limits document search
          </p>
        </div>
        
        <div style={{display: 'flex', gap: '0.75rem'}}>
          {/* Employee selector */}
          <div className="employee-dropdown" style={{position: 'relative'}}>
            <button
              type="button"
              onClick={() => setIsEmployeeDropdownOpen(!isEmployeeDropdownOpen)}
              style={{
                padding: '0.625rem 1rem',
                textAlign: 'left',
                backgroundColor: selectedEmployee ? '#eef2ff' : 'white',
                border: '1.5px solid',
                borderColor: selectedEmployee ? '#667eea' : '#e5e7eb',
                borderRadius: '8px',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                fontSize: '0.875rem',
                transition: 'all 0.2s ease',
                fontFamily: 'inherit',
                minWidth: '180px'
              }}
              onMouseEnter={(e) => {
                if (!selectedEmployee) e.currentTarget.style.borderColor = '#667eea'
              }}
              onMouseLeave={(e) => {
                if (!selectedEmployee) e.currentTarget.style.borderColor = '#e5e7eb'
              }}
            >
              <span style={{color: selectedEmployee ? '#4338ca' : '#374151', fontWeight: selectedEmployee ? 600 : 500}}>
                {selectedEmployee ? (employees.find(e => e.employee_id === selectedEmployee)?.name || 'Employee') : 'Filter by Employee'}
              </span>
              <span style={{fontSize: '12px', color: '#9ca3af', transition: 'transform 0.2s ease', transform: isEmployeeDropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)'}}>
                ▼
              </span>
            </button>

            {isEmployeeDropdownOpen && (
              <div style={{
                position: 'absolute',
                top: 'calc(100% + 4px)',
                left: 0,
                minWidth: '300px',
                backgroundColor: 'white',
                border: '1px solid #e5e7eb',
                borderRadius: '8px',
                maxHeight: '400px',
                overflowY: 'auto',
                zIndex: 1001,
                boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)'
              }}>
                <div style={{padding: '0.75rem', borderBottom: '1px solid #f3f4f6', position: 'sticky', top: 0, backgroundColor: 'white'}}>
                  <input
                    type="text"
                    placeholder="Search employees..."
                    value={employeeSearchQuery}
                    onChange={(e) => setEmployeeSearchQuery(e.target.value)}
                    autoFocus
                    style={{
                      width: '100%',
                      padding: '0.5rem',
                      border: '1px solid #e5e7eb',
                      borderRadius: '6px',
                      fontSize: '0.875rem',
                      fontFamily: 'inherit'
                    }}
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>

                <div
                  onClick={() => {
                    setSelectedEmployee('')
                    setIsEmployeeDropdownOpen(false)
                  }}
                  style={{
                    padding: '0.875rem 1rem',
                    cursor: 'pointer',
                    backgroundColor: !selectedEmployee ? '#eef2ff' : 'transparent',
                    borderBottom: '1px solid #f3f4f6',
                    fontWeight: !selectedEmployee ? 600 : 500,
                    color: !selectedEmployee ? '#4338ca' : '#374151',
                    fontSize: '0.9rem',
                    transition: 'all 0.15s ease'
                  }}
                  onMouseEnter={(e) => {
                    if (selectedEmployee) e.currentTarget.style.backgroundColor = '#f9fafb'
                  }}
                  onMouseLeave={(e) => {
                    if (selectedEmployee) e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  No Employee Filter
                </div>

                {employees
                  .filter(emp => employeeSearchQuery ? emp.name.toLowerCase().includes(employeeSearchQuery.toLowerCase()) : true)
                  .map(employee => {
                    const isSelected = selectedEmployee === employee.employee_id
                    return (
                      <div
                        key={employee.employee_id}
                        onClick={() => {
                          setSelectedEmployee(employee.employee_id)
                          setIsEmployeeDropdownOpen(false)
                          setEmployeeSearchQuery('')
                        }}
                        style={{
                          padding: '0.875rem 1rem',
                          cursor: 'pointer',
                          backgroundColor: isSelected ? '#eef2ff' : 'transparent',
                          borderBottom: '1px solid #f3f4f6',
                          transition: 'all 0.15s ease'
                        }}
                        onMouseEnter={(e) => {
                          if (!isSelected) e.currentTarget.style.backgroundColor = '#f9fafb'
                        }}
                        onMouseLeave={(e) => {
                          if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent'
                        }}
                      >
                        <div style={{
                          fontWeight: 600,
                          color: isSelected ? '#4338ca' : '#1f2937',
                          fontSize: '0.9rem',
                          marginBottom: '0.125rem'
                        }}>
                          {employee.name}
                        </div>
                        <div style={{
                          fontSize: '0.8rem',
                          color: '#6b7280',
                          fontWeight: 500
                        }}>
                          ID: {employee.employee_id} • {employee.project_count} projects
                        </div>
                      </div>
                    )
                  })}
              </div>
            )}
          </div>

          {/* Project selector in header */}
          <div className="project-dropdown" style={{position: 'relative', opacity: selectedEmployee ? 0.5 : 1, pointerEvents: selectedEmployee ? 'none' : 'auto'}}>
          <button
            type="button"
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            style={{
              padding: '0.625rem 1rem',
              textAlign: 'left',
              backgroundColor: 'white',
              border: '1.5px solid #e5e7eb',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              fontSize: '0.875rem',
              transition: 'all 0.2s ease',
              fontFamily: 'inherit',
              minWidth: '200px'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = '#667eea'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = '#e5e7eb'
            }}
          >
            <span style={{color: '#374151', fontWeight: 500}}>{getDisplayText()}</span>
            <span style={{fontSize: '12px', color: '#9ca3af', transition: 'transform 0.2s ease', transform: isDropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)'}}>
              ▼
            </span>
          </button>

          {isDropdownOpen && (
              <div style={{
                position: 'absolute',
                top: 'calc(100% + 4px)',
                left: 0,
                right: 0,
                backgroundColor: 'white',
                border: '1px solid #e5e7eb',
                borderRadius: '8px',
                maxHeight: '320px',
                overflowY: 'auto',
                zIndex: 1000,
                boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)'
              }}>
                <div
                  onClick={() => {
                    setSelectedProjects([])
                    setIsDropdownOpen(false)
                  }}
                  style={{
                    padding: '0.875rem 1rem',
                    cursor: 'pointer',
                    backgroundColor: isAllSelected ? '#eef2ff' : 'transparent',
                    borderBottom: '1px solid #f3f4f6',
                    fontWeight: isAllSelected ? 600 : 500,
                    color: isAllSelected ? '#4338ca' : '#374151',
                    fontSize: '0.9rem',
                    transition: 'all 0.15s ease'
                  }}
                  onMouseEnter={(e) => {
                    if (selectedProjects.length !== 0) {
                      e.currentTarget.style.backgroundColor = '#f9fafb'
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (selectedProjects.length !== 0) {
                      e.currentTarget.style.backgroundColor = 'transparent'
                    }
                  }}
                >
                  All Projects <span style={{color: '#9ca3af', fontSize: '0.85rem'}}>({projects.length} total)</span>
                </div>

                {projects.map(project => {
                  const isSelected = selectedProjects.includes(project.project_id)
                  return (
                    <div
                      key={project.project_id}
                      onClick={() => handleToggleProject(project.project_id)}
                      style={{
                        padding: '0.875rem 1rem',
                        cursor: 'pointer',
                        backgroundColor: isSelected ? '#eef2ff' : 'transparent',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        borderBottom: '1px solid #f3f4f6',
                        transition: 'all 0.15s ease'
                      }}
                      onMouseEnter={(e) => {
                        if (!isSelected) {
                          e.currentTarget.style.backgroundColor = '#f9fafb'
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!isSelected) {
                          e.currentTarget.style.backgroundColor = 'transparent'
                        }
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => {}}
                        style={{
                          width: '16px',
                          height: '16px',
                          cursor: 'pointer',
                          accentColor: '#667eea'
                        }}
                      />
                      <div style={{flex: 1}}>
                        <div style={{
                          fontWeight: 600,
                          color: isSelected ? '#4338ca' : '#1f2937',
                          fontSize: '0.9rem',
                          marginBottom: '0.125rem'
                        }}>
                          {project.project_id}
                        </div>
                        <div style={{
                          fontSize: '0.8rem',
                          color: '#6b7280',
                          fontWeight: 500
                        }}>
                          {project.document_count} docs • {project.chunk_count} chunks
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Messages Area */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty-state">
            <div style={{fontSize: '3rem', marginBottom: '1rem'}}>💎</div>
            <h3 style={{color: '#374151', marginBottom: '0.5rem', fontWeight: 600}}>Ask me about your projects</h3>
            <p style={{color: '#6b7280', marginBottom: '1.5rem', maxWidth: '400px'}}>
              I can search documents and pull team info from Ajera timesheets.
            </p>
            <div style={{
              textAlign: 'left',
              backgroundColor: '#f3f4f6',
              borderRadius: '12px',
              padding: '1.5rem',
              maxWidth: '450px',
              margin: '0 auto'
            }}>
              <p style={{color: '#374151', fontWeight: 600, marginBottom: '0.75rem', fontSize: '0.9rem'}}>💡 Try asking:</p>
              <ul style={{color: '#6b7280', fontSize: '0.875rem', margin: 0, paddingLeft: '1.25rem', lineHeight: 2}}>
                <li>"Who was the client for this project?"</li>
                <li>"Who worked on this project?" <span style={{color: '#9ca3af', fontSize: '0.8rem'}}>(from Ajera)</span></li>
                <li>"What was the scope of work?"</li>
                <li>"What soil conditions were found?"</li>
              </ul>
              {selectedEmployee && (
                <p style={{color: '#667eea', fontSize: '0.8rem', marginTop: '1rem', fontWeight: 500}}>
                  ✓ Filtering to {employees.find(e => e.employee_id === selectedEmployee)?.name}'s projects
                </p>
              )}
              {selectedProjects.length > 0 && !selectedEmployee && (
                <p style={{color: '#667eea', fontSize: '0.8rem', marginTop: '1rem', fontWeight: 500}}>
                  ✓ Searching {selectedProjects.length} selected project{selectedProjects.length > 1 ? 's' : ''}
                </p>
              )}
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <div key={message.id} className={`chat-message ${message.type}`}>
                {message.type === 'user' ? (
                  <div className="message-content user-message">
                    {message.content}
                  </div>
                ) : (
                  <div className="message-content assistant-message">
                    <div className="message-text">{message.content}</div>
                    
                    {message.citations && message.citations.length > 0 && (
                      <div className="message-citations">
                        <h4 className="citations-header">Sources ({message.citations.length})</h4>
                        {message.citations.map((citation, idx) => (
                          <div
                            key={idx}
                            className="citation-item"
                            onClick={() => handleCitationClick(citation)}
                          >
                            <div className="citation-header">
                              <span className="citation-project-badge">{citation.project_id}</span>
                              <span className="citation-file">{citation.file_path.split('/').pop()}</span>
                            </div>
                            <div className="citation-meta">Page {citation.page} • {citation.chunk_id}</div>
                            <div className="citation-excerpt">"{citation.text_excerpt}"</div>
                          </div>
                        ))}
                      </div>
                    )}
                    
                    <div className="message-meta">
                      {message.confidence && (
                        <span className={`confidence-badge confidence-${message.confidence}`}>
                          {message.confidence} confidence
                        </span>
                      )}
                      {message.elapsed_ms && (
                        <span className="time-badge">{message.elapsed_ms}ms</span>
                      )}
                      {message.stub_mode && (
                        <span className="demo-badge">Demo Mode</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
            
            {/* Loading indicator with stages */}
            {loading && (
              <div className="chat-message assistant">
                <div className="message-content assistant-message loading-message">
                  <div className="loading-stages">
                    <div className="loading-spinner">
                      <div className="spinner-dot"></div>
                      <div className="spinner-dot"></div>
                      <div className="spinner-dot"></div>
                    </div>
                    <div className="loading-text">
                      {loadingStage === 0 && "Embedding query..."}
                      {loadingStage === 1 && "Searching document index..."}
                      {loadingStage === 2 && "Processing relevant chunks..."}
                      {loadingStage === 3 && "Synthesizing answer..."}
                    </div>
                  </div>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      <div className="chat-input-container">
        {error && <div className="error" style={{marginBottom: '1rem'}}>{error}</div>}
        
        <form onSubmit={handleSendMessage} className="chat-input-form">
          <textarea
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSendMessage(e)
              }
            }}
            placeholder="Ask a question about your documents..."
            disabled={loading || projects.length === 0}
            className="chat-input"
            rows={1}
            style={{
              resize: 'none',
              minHeight: '44px',
              maxHeight: '120px',
              overflowY: 'auto'
            }}
          />
          <button
            type="submit"
            className="chat-send-btn"
            disabled={loading || !query.trim() || projects.length === 0}
          >
            {loading ? (
              <span>●●●</span>
            ) : (
              <span style={{fontSize: '1.25rem'}}>➤</span>
            )}
          </button>
        </form>
        
        <div style={{fontSize: '0.75rem', color: '#9ca3af', marginTop: '0.5rem', textAlign: 'center'}}>
          Press Enter to send • Shift+Enter for new line
        </div>
      </div>
    </div>
  )
}
