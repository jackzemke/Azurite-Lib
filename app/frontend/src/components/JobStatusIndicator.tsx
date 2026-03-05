import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface JobListItem {
  job_id: string
  state: string
  project_id?: string
  progress: number
  created_at?: string
}

interface JobStatusIndicatorProps {
  onOpenUpload?: () => void
}

export default function JobStatusIndicator({ onOpenUpload }: JobStatusIndicatorProps) {
  const [activeJobs, setActiveJobs] = useState<JobListItem[]>([])

  const checkJobs = useCallback(async () => {
    try {
      const [startedRes, queuedRes] = await Promise.all([
        axios.get<JobListItem[]>(`${API_URL}/api/v1/jobs`, { params: { state: 'started' } }),
        axios.get<JobListItem[]>(`${API_URL}/api/v1/jobs`, { params: { state: 'queued' } }),
      ])

      const allActive = [...(startedRes.data || []), ...(queuedRes.data || [])]
      setActiveJobs(allActive)
    } catch {
      // Silently fail -- don't disrupt the main UI
    }
  }, [])

  useEffect(() => {
    checkJobs()
    const interval = setInterval(checkJobs, 5000)
    return () => clearInterval(interval)
  }, [checkJobs])

  if (activeJobs.length === 0) return null

  const avgProgress = Math.round(
    activeJobs.reduce((sum, j) => sum + j.progress, 0) / activeJobs.length
  )

  return (
    <div
      className="job-status-indicator"
      onClick={onOpenUpload}
      title="Click to view upload status"
    >
      <span className="job-status-spinner" />
      <span className="job-status-text">
        Processing: {activeJobs.length} job{activeJobs.length !== 1 ? 's' : ''}
        {avgProgress > 0 ? ` (${avgProgress}%)` : ''}
      </span>
    </div>
  )
}
