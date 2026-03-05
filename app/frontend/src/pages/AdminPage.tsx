import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface ServiceStatus {
  name: string
  status: 'running' | 'stopped' | 'unknown'
  pid?: number
  details?: string
}

interface LogFile {
  name: string
  path: string
  size_bytes: number
  modified_at: string
  type: string
}

interface SystemInfo {
  hostname: string
  platform: string
  python_version: string
  cpu_count: number
  cpu_percent: number
  memory: {
    total_gb: number
    used_gb: number
    percent: number
  }
  disk: {
    total_gb: number
    used_gb: number
    free_gb: number
    percent: number
  }
  chroma_size_mb: number
}

interface AdminPageProps {
  onClose?: () => void
}

interface AnalyticsSummary {
  queries: {
    total_queries: number
    queries_last_7_days: number
    queries_last_30_days: number
    unique_projects_queried: number
    avg_response_time_ms: number
    confidence_distribution: Record<string, number>
    top_projects: { project_id: string; query_count: number }[]
    avg_citations_per_query: number
    queries_per_day: { date: string; count: number }[]
  }
  citations: {
    total_clicks: number
    clicks_last_7_days: number
    top_clicked_files: { file_path: string; click_count: number }[]
    top_clicked_projects: { project_id: string; click_count: number }[]
  }
  generated_at: string
}

interface DirectoryIndexStatus {
  configured: boolean
  available?: boolean
  message?: string
  drives?: string[]
  stats?: {
    initialized: boolean
    total_directories: number
    total_drives: number
    unique_project_ids?: number
    drives: string[]
  }
  last_scan?: {
    started_at: string
    completed_at?: string
    total_directories: number
    total_drives: number
    status: string
  } | null
}

export default function AdminPage({ onClose }: AdminPageProps) {
  const [services, setServices] = useState<ServiceStatus[]>([])
  const [logFiles, setLogFiles] = useState<LogFile[]>([])
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null)
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null)
  const [dirIndexStatus, setDirIndexStatus] = useState<DirectoryIndexStatus | null>(null)
  const [scanLoading, setScanLoading] = useState(false)
  const [selectedLog, setSelectedLog] = useState<string | null>(null)
  const [logContent, setLogContent] = useState<string>('')
  const [streamingLog, setStreamingLog] = useState<string | null>(null)
  const [streamBuffer, setStreamBuffer] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Fetch all data
  const fetchData = useCallback(async () => {
    try {
      const [servicesRes, logsRes, systemRes, analyticsRes, dirIndexRes] = await Promise.all([
        axios.get(`${API_URL}/api/v1/admin/services`),
        axios.get(`${API_URL}/api/v1/admin/logs`),
        axios.get(`${API_URL}/api/v1/admin/system`),
        axios.get(`${API_URL}/api/v1/analytics/summary`).catch(() => ({ data: null })),
        axios.get(`${API_URL}/api/v1/admin/directory-index/status`).catch(() => ({ data: null })),
      ])
      setServices(servicesRes.data)
      setLogFiles(logsRes.data)
      setSystemInfo(systemRes.data)
      setAnalytics(analyticsRes.data)
      setDirIndexStatus(dirIndexRes.data)
    } catch (err) {
      console.error('Failed to fetch admin data:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000) // Refresh every 10s
    return () => clearInterval(interval)
  }, [fetchData])

  // Service control
  const controlService = async (serviceId: string, action: 'start' | 'stop' | 'restart') => {
    setActionLoading(serviceId)
    try {
      await axios.post(`${API_URL}/api/v1/admin/services/${serviceId}`, { action })
      await fetchData()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Action failed')
    } finally {
      setActionLoading(null)
    }
  }

  // Trigger directory index scan
  const triggerScan = async () => {
    setScanLoading(true)
    try {
      await axios.post(`${API_URL}/api/v1/admin/directory-index/scan`)
      await fetchData()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Scan failed')
    } finally {
      setScanLoading(false)
    }
  }

  // View log file
  const viewLog = async (logName: string) => {
    setSelectedLog(logName)
    setStreamingLog(null)
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    
    try {
      const res = await axios.get(`${API_URL}/api/v1/admin/logs/${encodeURIComponent(logName)}?tail=1000`)
      setLogContent(res.data.content)
    } catch (err) {
      setLogContent('Failed to load log file')
    }
  }

  // Stream log file
  const streamLog = (logName: string) => {
    setSelectedLog(logName)
    setStreamingLog(logName)
    setStreamBuffer('')
    
    if (wsRef.current) {
      wsRef.current.close()
    }
    
    const wsUrl = `${API_URL.replace('http', 'ws')}/api/v1/admin/logs/${encodeURIComponent(logName)}/stream`
    const ws = new WebSocket(wsUrl)
    
    ws.onmessage = (event) => {
      setStreamBuffer(prev => {
        const newContent = prev + event.data
        // Keep last 50000 chars to prevent memory issues
        return newContent.slice(-50000)
      })
    }
    
    ws.onerror = () => {
      setStreamBuffer(prev => prev + '\n[WebSocket error]')
    }
    
    ws.onclose = () => {
      setStreamBuffer(prev => prev + '\n[Stream closed]')
      setStreamingLog(null)
    }
    
    wsRef.current = ws
  }

  // Auto-scroll log
  useEffect(() => {
    if (logEndRef.current && streamingLog) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [streamBuffer, streamingLog])

  // Cleanup WebSocket
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [])

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return '#10b981'
      case 'stopped': return '#ef4444'
      default: return '#f59e0b'
    }
  }

  const getServiceId = (name: string) => {
    // Map display name to service ID
    if (name.includes('Backend')) return 'backend'
    if (name.includes('Frontend')) return 'frontend'
    if (name.includes('Redis')) return 'redis'
    if (name.includes('RQ')) return 'rq_worker'
    return name.toLowerCase().replace(/\s+/g, '_')
  }

  if (loading) {
    return (
      <div className="admin-page">
        <div style={{ padding: '2rem', textAlign: 'center', color: '#6b7280' }}>
          Loading admin dashboard...
        </div>
      </div>
    )
  }

  return (
    <div className="admin-page">
      {/* Header */}
      <div className="admin-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ fontSize: '1.5rem' }}>⚙️</span>
          <h2 style={{ margin: 0, fontWeight: 600 }}>Admin Dashboard</h2>
        </div>
        {onClose && (
          <button onClick={onClose} className="admin-close-btn">
            ✕ Close
          </button>
        )}
      </div>

      <div className="admin-content">
        {/* Left Panel: Services & System */}
        <div className="admin-left-panel">
          {/* System Info */}
          {systemInfo && (
            <div className="admin-card">
              <h3>System</h3>
              <div className="system-stats">
                <div className="stat-row">
                  <span>Host</span>
                  <span>{systemInfo.hostname}</span>
                </div>
                <div className="stat-row">
                  <span>CPU</span>
                  <span>{systemInfo.cpu_count} cores • {systemInfo.cpu_percent.toFixed(0)}%</span>
                </div>
                <div className="stat-row">
                  <span>Memory</span>
                  <div className="stat-bar-container">
                    <div className="stat-bar" style={{ width: `${systemInfo.memory.percent}%`, backgroundColor: systemInfo.memory.percent > 80 ? '#ef4444' : '#10b981' }} />
                  </div>
                  <span>{systemInfo.memory.used_gb.toFixed(1)}/{systemInfo.memory.total_gb.toFixed(0)} GB</span>
                </div>
                <div className="stat-row">
                  <span>Disk</span>
                  <div className="stat-bar-container">
                    <div className="stat-bar" style={{ width: `${systemInfo.disk.percent}%`, backgroundColor: systemInfo.disk.percent > 80 ? '#ef4444' : '#10b981' }} />
                  </div>
                  <span>{systemInfo.disk.free_gb.toFixed(0)} GB free</span>
                </div>
                <div className="stat-row">
                  <span>ChromaDB</span>
                  <span>{systemInfo.chroma_size_mb.toFixed(1)} MB</span>
                </div>
              </div>
            </div>
          )}

          {/* Usage Metrics */}
          {analytics && (
            <div className="admin-card">
              <h3>Usage Metrics</h3>
              <div className="system-stats">
                <div className="stat-row">
                  <span>Queries</span>
                  <span>{analytics.queries.total_queries.toLocaleString()} total</span>
                </div>
                <div className="stat-row">
                  <span>Last 7d</span>
                  <span>{analytics.queries.queries_last_7_days}</span>
                </div>
                <div className="stat-row">
                  <span>Last 30d</span>
                  <span>{analytics.queries.queries_last_30_days}</span>
                </div>
                <div className="stat-row">
                  <span>Avg Time</span>
                  <span>{(analytics.queries.avg_response_time_ms / 1000).toFixed(1)}s</span>
                </div>
                <div className="stat-row">
                  <span>Avg Cites</span>
                  <span>{analytics.queries.avg_citations_per_query}</span>
                </div>
                <div className="stat-row">
                  <span>Clicks</span>
                  <span>{analytics.citations.total_clicks} citation clicks</span>
                </div>
                <div className="stat-row">
                  <span>Projects</span>
                  <span>{analytics.queries.unique_projects_queried} queried</span>
                </div>
              </div>

              {analytics.queries.confidence_distribution && Object.keys(analytics.queries.confidence_distribution).length > 0 && (
                <div style={{ marginTop: '0.75rem', fontSize: '0.8rem', color: '#94a3b8' }}>
                  <strong>Confidence: </strong>
                  {Object.entries(analytics.queries.confidence_distribution).map(([level, count]) => (
                    <span key={level} style={{ marginRight: '0.75rem' }}>
                      {level}: {count}
                    </span>
                  ))}
                </div>
              )}

              {analytics.queries.top_projects.length > 0 && (
                <div style={{ marginTop: '0.75rem' }}>
                  <strong style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Top Projects:</strong>
                  {analytics.queries.top_projects.slice(0, 5).map((p) => (
                    <div key={p.project_id} className="stat-row" style={{ fontSize: '0.8rem' }}>
                      <span style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {p.project_id}
                      </span>
                      <span>{p.query_count} queries</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Directory Index */}
          <div className="admin-card">
            <h3>Directory Index</h3>
            <div className="system-stats">
              {!dirIndexStatus || !dirIndexStatus.configured ? (
                <div style={{ fontSize: '0.85rem', color: '#94a3b8', padding: '0.25rem 0' }}>
                  Not configured. Add drives to config.yaml under network_drives.drives.
                </div>
              ) : (
                <>
                  <div className="stat-row">
                    <span>Status</span>
                    <span style={{ color: dirIndexStatus.available ? '#10b981' : '#f59e0b' }}>
                      {dirIndexStatus.available ? 'Available' : 'No scan data'}
                    </span>
                  </div>
                  {dirIndexStatus.stats && (
                    <>
                      <div className="stat-row">
                        <span>Drives</span>
                        <span>{dirIndexStatus.stats.drives.join(', ')}</span>
                      </div>
                      <div className="stat-row">
                        <span>Directories</span>
                        <span>{dirIndexStatus.stats.total_directories.toLocaleString()}</span>
                      </div>
                      {dirIndexStatus.stats.unique_project_ids !== undefined && dirIndexStatus.stats.unique_project_ids > 0 && (
                        <div className="stat-row">
                          <span>Project IDs</span>
                          <span>{dirIndexStatus.stats.unique_project_ids.toLocaleString()}</span>
                        </div>
                      )}
                    </>
                  )}
                  {dirIndexStatus.last_scan && (
                    <div className="stat-row">
                      <span>Last Scan</span>
                      <span>
                        {dirIndexStatus.last_scan.completed_at
                          ? new Date(dirIndexStatus.last_scan.completed_at).toLocaleString()
                          : dirIndexStatus.last_scan.status}
                      </span>
                    </div>
                  )}
                  <div style={{ marginTop: '0.5rem' }}>
                    <button
                      onClick={triggerScan}
                      disabled={scanLoading}
                      className="service-btn start"
                      style={{ width: '100%' }}
                    >
                      {scanLoading ? 'Scanning...' : 'Scan Now'}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Services */}
          <div className="admin-card">
            <h3>Services</h3>
            <div className="services-list">
              {services.map((service) => {
                const serviceId = getServiceId(service.name)
                const isLoading = actionLoading === serviceId
                
                return (
                  <div key={service.name} className="service-item">
                    <div className="service-info">
                      <div className="service-status-dot" style={{ backgroundColor: getStatusColor(service.status) }} />
                      <div>
                        <div className="service-name">{service.name}</div>
                        <div className="service-details">
                          {service.status}
                          {service.pid && ` • PID ${service.pid}`}
                          {service.details && ` • ${service.details}`}
                        </div>
                      </div>
                    </div>
                    <div className="service-actions">
                      {service.status === 'running' ? (
                        <button
                          onClick={() => controlService(serviceId, 'stop')}
                          disabled={isLoading}
                          className="service-btn stop"
                        >
                          {isLoading ? '...' : 'Stop'}
                        </button>
                      ) : (
                        <button
                          onClick={() => controlService(serviceId, 'start')}
                          disabled={isLoading}
                          className="service-btn start"
                        >
                          {isLoading ? '...' : 'Start'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
            <p className="services-note">
              Note: Starting services here runs them in the background. Check logs below for output.
            </p>
          </div>

          {/* Log Files */}
          <div className="admin-card">
            <h3>Log Files</h3>
            <div className="log-files-list">
              {logFiles.map((log) => (
                <div
                  key={log.name}
                  className={`log-file-item ${selectedLog === log.name ? 'selected' : ''}`}
                  onClick={() => viewLog(log.name)}
                >
                  <div className="log-file-icon">
                    {log.type === 'ingest_report' ? '📊' : log.type === 'query_log' ? '🔍' : '📄'}
                  </div>
                  <div className="log-file-info">
                    <div className="log-file-name">{log.name}</div>
                    <div className="log-file-meta">
                      {formatBytes(log.size_bytes)} • {new Date(log.modified_at).toLocaleString()}
                    </div>
                  </div>
                  {log.name.endsWith('.log') && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        streamLog(log.name)
                      }}
                      className="stream-btn"
                      title="Stream live"
                    >
                      {streamingLog === log.name ? '⏹️' : '▶️'}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Panel: Log Viewer */}
        <div className="admin-right-panel">
          <div className="admin-card log-viewer-card">
            <div className="log-viewer-header">
              <h3>{selectedLog || 'Select a log file'}</h3>
              {streamingLog && (
                <span className="streaming-badge">
                  <span className="streaming-dot" /> Live
                </span>
              )}
            </div>
            <div className="log-viewer">
              {selectedLog ? (
                <pre className="log-content">
                  {streamingLog ? streamBuffer : logContent}
                  <div ref={logEndRef} />
                </pre>
              ) : (
                <div className="log-placeholder">
                  Select a log file from the list to view its contents.
                  <br /><br />
                  Click ▶️ on .log files to stream live updates.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
