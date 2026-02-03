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

export default function AdminPage({ onClose }: AdminPageProps) {
  const [services, setServices] = useState<ServiceStatus[]>([])
  const [logFiles, setLogFiles] = useState<LogFile[]>([])
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null)
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
      const [servicesRes, logsRes, systemRes] = await Promise.all([
        axios.get(`${API_URL}/api/v1/admin/services`),
        axios.get(`${API_URL}/api/v1/admin/logs`),
        axios.get(`${API_URL}/api/v1/admin/system`),
      ])
      setServices(servicesRes.data)
      setLogFiles(logsRes.data)
      setSystemInfo(systemRes.data)
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
