import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL ?? ''

interface ProjectResult {
  project_id: string
  project_name: string
  department?: string
  client?: string
  start_date?: string
  end_date?: string
  scope_type?: string
  full_path?: string
  team_count?: number
  distance?: number
}

interface TeamMember {
  employee_id: string
  name: string
  total_hours: number
}

interface Message {
  id: string
  type: 'user' | 'assistant'
  content: string
  projects?: ProjectResult[]
  teamData?: Record<string, {
    total_employees: number
    top_employees: TeamMember[]
  }>
  confidence?: string
  elapsed_ms?: number
  stub_mode?: boolean
  timestamp: Date
}

interface SearchPageProps {
  onOpenHelp?: () => void
}

export default function SearchPage({ onOpenHelp }: SearchPageProps) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState(0)
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState('')
  const [expandedTeams, setExpandedTeams] = useState<Set<string>>(new Set())
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const toggleTeamExpand = (projectId: string) => {
    setExpandedTeams(prev => {
      const next = new Set(prev)
      if (next.has(projectId)) {
        next.delete(projectId)
      } else {
        next.add(projectId)
      }
      return next
    })
  }

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return

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

    const stageInterval = setInterval(() => {
      setLoadingStage(prev => (prev < 2 ? prev + 1 : prev))
    }, 1500)

    try {
      // Build chat history from previous messages for context
      const chatHistory: {query: string, answer: string}[] = []
      for (let i = 0; i < messages.length - 1; i += 2) {
        const userMsg = messages[i]
        const assistantMsg = messages[i + 1]
        if (userMsg?.type === 'user' && assistantMsg?.type === 'assistant') {
          chatHistory.push({
            query: userMsg.content,
            answer: assistantMsg.content,
          })
        }
      }

      // Resolve "that project" style follow-ups to the most recent project result.
      const isContextualFollowUp = /\b(that project|that one|on that project|who worked on that|who was on that)\b/i.test(userMessage.content)
      let contextualProjectIds: string[] | undefined = undefined
      if (isContextualFollowUp) {
        const lastAssistantWithProjects = [...messages]
          .reverse()
          .find((m) => m.type === 'assistant' && m.projects && m.projects.length > 0)
        const projectId = lastAssistantWithProjects?.projects?.[0]?.project_id
        if (projectId) {
          contextualProjectIds = [projectId]
        }
      }

      const response = await axios.post(`${API_URL}/api/v1/query`, {
        query: userMessage.content,
        k: 6,
        chat_history: chatHistory.slice(-3),
        project_ids: contextualProjectIds,
      })

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: response.data.answer,
        projects: response.data.projects,
        teamData: response.data.team_data,
        confidence: response.data.confidence,
        elapsed_ms: response.data.elapsed_ms,
        stub_mode: response.data.stub_mode,
        timestamp: new Date()
      }

      setMessages(prev => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to get response. Please try again.')
      setMessages(prev => prev.filter(m => m.id !== userMessage.id))
    } finally {
      clearInterval(stageInterval)
      setLoading(false)
      setLoadingStage(0)
      inputRef.current?.focus()
    }
  }

  return (
    <div className="chat-container">
      {/* Header */}
      <div className="chat-header">
        <div style={{display: 'flex', alignItems: 'center', gap: '1rem'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
            <h2 style={{margin: 0, fontSize: '1.25rem', fontWeight: 600, background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent'}}>Azurite Archive Assistant</h2>
          </div>
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
        <p style={{margin: '0.25rem 0 0 0', color: '#9ca3af', fontSize: '0.85rem'}}>
          Project finder powered by metadata search
        </p>
      </div>

      {/* Messages Area */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty-state">
            <h3 style={{color: '#374151', marginBottom: '0.5rem', fontWeight: 600}}>Find any SMA project</h3>
            <p style={{color: '#6b7280', marginBottom: '1.5rem', maxWidth: '400px'}}>
              Search by name, department, client, or date range. I can also tell you who worked on a project using Ajera timesheet data.
            </p>
            <div style={{
              textAlign: 'left',
              backgroundColor: '#f3f4f6',
              borderRadius: '12px',
              padding: '1.5rem',
              maxWidth: '450px',
              margin: '0 auto'
            }}>
              <p style={{color: '#374151', fontWeight: 600, marginBottom: '0.75rem', fontSize: '0.9rem'}}>Try asking:</p>
              <ul style={{color: '#6b7280', fontSize: '0.875rem', margin: 0, paddingLeft: '1.25rem', lineHeight: 2}}>
                <li>"Find environmental projects"</li>
                <li>"What projects did we do for NMED?"</li>
                <li>"Projects in the Water department"</li>
                <li>"Who worked on Acomita Day School?"</li>
              </ul>
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

                    {/* Project Result Cards */}
                    {message.projects && message.projects.length > 0 && (
                      <div className="project-results">
                        {message.projects.map((project) => (
                          <div key={project.project_id} className="project-card">
                            <div className="project-card-header">
                              <span className="project-id-badge">{project.project_id}</span>
                              <strong style={{fontSize: '0.95rem'}}>{project.project_name}</strong>
                            </div>
                            <div className="project-card-fields">
                              {project.department && <span>Department: {project.department}</span>}
                              {project.client && <span>Client: {project.client}</span>}
                              {(project.start_date || project.end_date) && (
                                <span>Dates: {project.start_date || '?'} - {project.end_date || '?'}</span>
                              )}
                              {project.scope_type && <span>Scope: {project.scope_type}</span>}
                              {project.full_path && (
                                <span className="project-path" title={project.full_path}>
                                  Location: {project.full_path}
                                </span>
                              )}
                            </div>
                            {project.team_count != null && project.team_count > 0 && (
                              <button
                                className="team-badge"
                                onClick={() => toggleTeamExpand(project.project_id)}
                              >
                                {project.team_count} team member{project.team_count !== 1 ? 's' : ''}
                                {expandedTeams.has(project.project_id) ? ' \u25B2' : ' \u25BC'}
                              </button>
                            )}
                            {expandedTeams.has(project.project_id) &&
                             message.teamData?.[project.project_id] && (
                              <div className="team-list">
                                {message.teamData[project.project_id].top_employees.map(emp => (
                                  <div key={emp.employee_id} className="team-member">
                                    <span style={{fontWeight: 500}}>{emp.name}</span>
                                    <span style={{color: '#6b7280', marginLeft: '0.5rem'}}>{emp.total_hours}h</span>
                                  </div>
                                ))}
                                {message.teamData[project.project_id].total_employees > 10 && (
                                  <div style={{fontSize: '0.8rem', color: '#9ca3af', padding: '0.25rem 0'}}>
                                    ...and {message.teamData[project.project_id].total_employees - 10} more
                                  </div>
                                )}
                              </div>
                            )}
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
                      {loadingStage === 0 && "Searching projects..."}
                      {loadingStage === 1 && "Matching metadata..."}
                      {loadingStage === 2 && "Generating answer..."}
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
            placeholder="Search for a project by name, department, client, or scope..."
            disabled={loading}
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
            disabled={loading || !query.trim()}
          >
            {loading ? (
              <span>...</span>
            ) : (
              <span style={{fontSize: '1.25rem'}}>{'\u27A4'}</span>
            )}
          </button>
        </form>

        <div style={{fontSize: '0.75rem', color: '#9ca3af', marginTop: '0.5rem', textAlign: 'center'}}>
          Press Enter to send
        </div>
      </div>
    </div>
  )
}
