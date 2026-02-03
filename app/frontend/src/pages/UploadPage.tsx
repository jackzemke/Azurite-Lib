import { useState, useRef, useEffect, useCallback } from 'react'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface UploadPageProps {
  onClose?: () => void
}

type UploadStep = 'select' | 'uploading' | 'processing' | 'complete' | 'error'

interface ProjectInfo {
  folderName: string
  fileCount: number
  totalSizeMB: number
  detectedId?: string
}

interface JobStatus {
  job_id: string
  state: 'queued' | 'started' | 'processing' | 'finished' | 'failed' | 'cancelled' | 'unknown'
  project_id?: string
  progress: number
  message: string
  files_total: number
  files_processed: number
  chunks_created: number
  errors: string[]
  created_at?: string
  started_at?: string
  ended_at?: string
  duration_seconds?: number
  result?: any
}

interface UploadProgress {
  phase: 'preparing' | 'uploading' | 'processing'
  filesUploaded: number
  totalFiles: number
  bytesUploaded: number
  totalBytes: number
  currentFile: string
  currentBatch: number
  totalBatches: number
  startTime: number
  processingStage: string
  elapsedSeconds: number
  // New async fields
  jobId?: string
  jobProgress: number
  jobMessage: string
  chunksCreated: number
}

export default function UploadPage({ onClose }: UploadPageProps) {
  const [step, setStep] = useState<UploadStep>('select')
  const [files, setFiles] = useState<File[]>([])
  const [projectInfo, setProjectInfo] = useState<ProjectInfo | null>(null)
  const [progress, setProgress] = useState<UploadProgress>({
    phase: 'preparing',
    filesUploaded: 0,
    totalFiles: 0,
    bytesUploaded: 0,
    totalBytes: 0,
    currentFile: '',
    currentBatch: 0,
    totalBatches: 0,
    startTime: 0,
    processingStage: '',
    elapsedSeconds: 0,
    jobId: undefined,
    jobProgress: 0,
    jobMessage: '',
    chunksCreated: 0
  })
  const [result, setResult] = useState<{ success: boolean; message: string; details?: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Elapsed time timer
  useEffect(() => {
    if (step === 'uploading' || step === 'processing') {
      timerRef.current = setInterval(() => {
        setProgress(prev => ({
          ...prev,
          elapsedSeconds: Math.floor((Date.now() - prev.startTime) / 1000)
        }))
      }, 1000)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [step])

  // Poll job status
  const pollJobStatus = useCallback(async (jobId: string) => {
    try {
      const response = await axios.get<JobStatus>(`${API_URL}/api/v1/jobs/${jobId}`)
      const status = response.data

      setProgress(prev => ({
        ...prev,
        jobProgress: status.progress,
        jobMessage: status.message,
        filesUploaded: status.files_processed,
        totalFiles: status.files_total,
        chunksCreated: status.chunks_created
      }))

      if (status.state === 'finished') {
        // Job completed successfully
        if (pollRef.current) clearInterval(pollRef.current)
        const totalTime = status.duration_seconds || progress.elapsedSeconds
        setResult({
          success: true,
          message: `Indexed "${projectInfo?.folderName}"`,
          details: `${status.files_processed} docs • ${status.chunks_created} chunks • ${formatTime(Math.round(totalTime))}`
        })
        setStep('complete')
      } else if (status.state === 'failed') {
        // Job failed
        if (pollRef.current) clearInterval(pollRef.current)
        setResult({
          success: false,
          message: 'Processing failed',
          details: status.errors.length > 0 ? status.errors[0] : status.message
        })
        setStep('error')
      } else if (status.state === 'cancelled') {
        if (pollRef.current) clearInterval(pollRef.current)
        setResult({
          success: false,
          message: 'Job was cancelled',
          details: 'The ingestion job was cancelled.'
        })
        setStep('error')
      }
      // Otherwise keep polling (queued, started, processing)
    } catch (err: any) {
      console.error('Error polling job status:', err)
      // Don't stop polling on transient errors
    }
  }, [projectInfo])

  const formatTime = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}m ${secs}s`
  }

  const formatBytes = (bytes: number): string => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const estimateTimeRemaining = (): string => {
    if (progress.phase === 'uploading' && progress.bytesUploaded > 0 && progress.elapsedSeconds > 2) {
      const rate = progress.bytesUploaded / progress.elapsedSeconds
      const remaining = (progress.totalBytes - progress.bytesUploaded) / rate
      if (remaining < 60) return `~${Math.ceil(remaining)}s left`
      return `~${Math.ceil(remaining / 60)}m left`
    }
    return ''
  }

  const extractProjectId = (folderName: string): string | undefined => {
    const parenMatch = folderName.match(/\((\d{5,8})\)/)
    if (parenMatch) return parenMatch[1]
    const prefixMatch = folderName.match(/^(\d{5,8})\s*[-]?\s/)
    if (prefixMatch) return prefixMatch[1]
    return undefined
  }

  const handleDirectorySelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return
    const fileList = Array.from(e.target.files)
    const supportedExts = ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'png', 'jpg', 'jpeg', 'tiff', 'bmp']
    const supportedFiles = fileList.filter(file => {
      const ext = file.name.toLowerCase().split('.').pop()
      return supportedExts.includes(ext || '') && !file.name.startsWith('~$')
    })
    if (supportedFiles.length === 0) {
      setResult({ success: false, message: 'No supported documents found.' })
      setStep('error')
      return
    }
    const firstPath = supportedFiles[0].webkitRelativePath || supportedFiles[0].name
    const folderName = firstPath.split('/')[0]
    const totalSize = supportedFiles.reduce((sum, f) => sum + f.size, 0) / 1024 / 1024
    setFiles(supportedFiles)
    setProjectInfo({ folderName, fileCount: supportedFiles.length, totalSizeMB: totalSize, detectedId: extractProjectId(folderName) })
  }

  const handleUploadAndIngest = async () => {
    if (!projectInfo || files.length === 0) return
    const startTime = Date.now()
    const totalBytes = files.reduce((sum, f) => sum + f.size, 0)
    const BATCH_SIZE = 5
    const totalBatches = Math.ceil(files.length / BATCH_SIZE)
    setStep('uploading')
    setProgress({ 
      phase: 'uploading', 
      filesUploaded: 0, 
      totalFiles: files.length, 
      bytesUploaded: 0, 
      totalBytes, 
      currentFile: files[0]?.name || '', 
      currentBatch: 1, 
      totalBatches, 
      startTime, 
      processingStage: '', 
      elapsedSeconds: 0,
      jobId: undefined,
      jobProgress: 0,
      jobMessage: '',
      chunksCreated: 0
    })
    
    try {
      const projectId = projectInfo.folderName
      let uploadedCount = 0
      let bytesUploaded = 0
      
      // Phase 1: Upload files in batches
      for (let i = 0; i < files.length; i += BATCH_SIZE) {
        const batch = files.slice(i, i + BATCH_SIZE)
        const batchNum = Math.floor(i / BATCH_SIZE) + 1
        const batchBytes = batch.reduce((sum, f) => sum + f.size, 0)
        setProgress(prev => ({ ...prev, currentBatch: batchNum, currentFile: batch[0]?.name || '' }))
        
        const formData = new FormData()
        batch.forEach(file => formData.append('files', file))
        
        await axios.post(`${API_URL}/api/v1/projects/${encodeURIComponent(projectId)}/upload`, formData, { 
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 300000,
          onUploadProgress: (e) => {
            const batchProgress = e.loaded / (e.total || batchBytes)
            setProgress(prev => ({ 
              ...prev, 
              bytesUploaded: bytesUploaded + (batchBytes * batchProgress), 
              currentFile: batch[Math.min(Math.floor(batchProgress * batch.length), batch.length - 1)]?.name || prev.currentFile 
            }))
          }
        })
        uploadedCount += batch.length
        bytesUploaded += batchBytes
        setProgress(prev => ({ ...prev, filesUploaded: uploadedCount, bytesUploaded }))
      }
      
      // Phase 2: Start async ingestion
      setStep('processing')
      const procStart = Date.now()
      setProgress(prev => ({ 
        ...prev, 
        phase: 'processing', 
        processingStage: 'Queuing ingestion job...', 
        startTime: procStart, 
        elapsedSeconds: 0,
        jobProgress: 0,
        filesUploaded: 0,
        totalFiles: files.length
      }))
      
      // Call async ingest endpoint
      const ingestResponse = await axios.post(
        `${API_URL}/api/v1/projects/${encodeURIComponent(projectId)}/ingest/async`,
        {},
        { timeout: 30000 }
      )
      
      const jobId = ingestResponse.data.job_id
      setProgress(prev => ({ ...prev, jobId, processingStage: 'Processing queued...' }))
      
      // Start polling for job status
      pollRef.current = setInterval(() => {
        pollJobStatus(jobId)
      }, 2000) // Poll every 2 seconds
      
      // Initial poll
      pollJobStatus(jobId)
      
    } catch (err: any) {
      if (pollRef.current) clearInterval(pollRef.current)
      setResult({ 
        success: false, 
        message: err.response?.data?.detail || 'Processing failed.', 
        details: err.code === 'ECONNABORTED' ? 'Request timed out.' : 'Check files and try again.' 
      })
      setStep('error')
    }
  }

  const handleReset = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    setStep('select')
    setFiles([])
    setProjectInfo(null)
    setProgress({ 
      phase: 'preparing', 
      filesUploaded: 0, 
      totalFiles: 0, 
      bytesUploaded: 0, 
      totalBytes: 0, 
      currentFile: '', 
      currentBatch: 0, 
      totalBatches: 0, 
      startTime: 0, 
      processingStage: '', 
      elapsedSeconds: 0,
      jobId: undefined,
      jobProgress: 0,
      jobMessage: '',
      chunksCreated: 0
    })
    setResult(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const uploadPct = progress.totalBytes > 0 ? Math.round((progress.bytesUploaded / progress.totalBytes) * 100) : 0
  const processingPct = Math.round(progress.jobProgress)

  return (
    <div className="upload-page">
      <div className="upload-header">
        <div className="upload-header-icon">📁</div>
        <h2>Add Project Documents</h2>
        <p>Select a project folder to make its documents searchable</p>
      </div>

      {step === 'select' && (
        <div className="upload-content">
          {!projectInfo ? (
            <div className="upload-dropzone" onClick={() => fileInputRef.current?.click()}>
              <input ref={fileInputRef} type="file" onChange={handleDirectorySelect} style={{ display: 'none' }} {...{ webkitdirectory: '', directory: '' } as any} />
              <div className="dropzone-icon">📂</div>
              <div className="dropzone-text"><strong>Click to select a project folder</strong><span>Supported: PDF, DOCX, XLSX, Images</span></div>
            </div>
          ) : (
            <div className="upload-preview">
              <div className="preview-card">
                <div className="preview-icon">📁</div>
                <div className="preview-info">
                  <h3>{projectInfo.folderName}</h3>
                  <div className="preview-meta">
                    <span>📄 {projectInfo.fileCount} docs</span>
                    <span>💾 {projectInfo.totalSizeMB.toFixed(1)} MB</span>
                    {projectInfo.detectedId && <span className="preview-id">🔗 {projectInfo.detectedId}</span>}
                  </div>
                </div>
                <button className="preview-change" onClick={handleReset}>Change</button>
              </div>
              <div className="upload-actions">
                <button className="btn btn-primary btn-large" onClick={handleUploadAndIngest}><span>🚀</span> Upload & Index</button>
                <p className="upload-hint">{projectInfo.totalSizeMB > 100 ? `⚠️ Large upload - may take 10+ minutes` : projectInfo.fileCount > 50 ? 'May take a few minutes' : 'Ready to upload'}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {step === 'uploading' && (
        <div className="upload-content">
          <div className="progress-container">
            <div className="progress-icon uploading">☁️</div>
            <h3>Uploading Documents</h3>
            <div className="progress-bar-container"><div className="progress-bar" style={{ width: `${uploadPct}%` }} /></div>
            <div className="progress-stats"><span>{uploadPct}%</span><span>•</span><span>{progress.filesUploaded}/{progress.totalFiles} files</span><span>•</span><span>{formatBytes(progress.bytesUploaded)}/{formatBytes(progress.totalBytes)}</span></div>
            <div className="progress-current"><span className="label">📄</span><span className="value">{progress.currentFile}</span></div>
            <div className="progress-time"><span>⏱️ {formatTime(progress.elapsedSeconds)}</span><span>{estimateTimeRemaining()}</span></div>
            <div className="activity-pulse"><div className="pulse-dot"></div><span>Batch {progress.currentBatch}/{progress.totalBatches}</span></div>
          </div>
        </div>
      )}

      {step === 'processing' && (
        <div className="upload-content">
          <div className="progress-container">
            <div className="progress-icon processing">⚙️</div>
            <h3>Processing Documents</h3>
            {processingPct > 0 ? (
              <>
                <div className="progress-bar-container"><div className="progress-bar" style={{ width: `${processingPct}%` }} /></div>
                <div className="progress-stats">
                  <span>{processingPct}%</span>
                  <span>•</span>
                  <span>{progress.filesUploaded}/{progress.totalFiles} files</span>
                  {progress.chunksCreated > 0 && <><span>•</span><span>{progress.chunksCreated} chunks</span></>}
                </div>
              </>
            ) : (
              <div className="progress-bar-container"><div className="progress-bar indeterminate" /></div>
            )}
            <p className="progress-text">{progress.jobMessage || progress.processingStage}</p>
            <div className="progress-time"><span>⏱️ {formatTime(progress.elapsedSeconds)}</span></div>
            <div className="activity-pulse"><div className="pulse-dot"></div><span>Processing in background</span></div>
            <p className="progress-hint">
              {progress.jobId 
                ? "You can close this window - processing will continue in the background." 
                : "Queuing job..."}
            </p>
          </div>
        </div>
      )}

      {step === 'complete' && result && (
        <div className="upload-content">
          <div className="result-container success">
            <div className="result-icon">✅</div>
            <h3>{result.message}</h3>
            <p className="result-details">{result.details}</p>
            <div className="result-actions"><button className="btn btn-primary" onClick={onClose}>Start Searching</button><button className="btn btn-secondary" onClick={handleReset}>Add Another</button></div>
          </div>
        </div>
      )}

      {step === 'error' && result && (
        <div className="upload-content">
          <div className="result-container error">
            <div className="result-icon">❌</div>
            <h3>{result.message}</h3>
            {result.details && <p className="result-details">{result.details}</p>}
            <div className="result-actions"><button className="btn btn-primary" onClick={handleReset}>Try Again</button></div>
          </div>
        </div>
      )}
    </div>
  )
}
