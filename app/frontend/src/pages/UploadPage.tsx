import React, { useState } from 'react'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function UploadPage() {
  const [projectId, setProjectId] = useState('proj_demo')
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files))
    }
  }

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault()

    if (files.length === 0) {
      setError('Please select files to upload')
      return
    }

    setUploading(true)
    setError('')
    setMessage('')

    try {
      const formData = new FormData()
      files.forEach((file) => {
        formData.append('files', file)
      })

      const response = await axios.post(
        `${API_URL}/api/v1/projects/${projectId}/upload`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        }
      )

      setMessage(`Successfully uploaded ${response.data.saved.length} files`)
      setFiles([])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Upload failed. Please try again.')
    } finally {
      setUploading(false)
    }
  }

  const handleIngest = async () => {
    setIngesting(true)
    setError('')
    setMessage('')

    try {
      const response = await axios.post(
        `${API_URL}/api/v1/projects/${projectId}/ingest`,
        {}
      )

      setMessage(
        `Ingestion complete! Processed ${response.data.files_processed} files, created ${response.data.chunks_created} chunks`
      )
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ingestion failed. Please try again.')
    } finally {
      setIngesting(false)
    }
  }

  return (
    <div className="page">
      <h2>Upload Documents</h2>

      <form onSubmit={handleUpload}>
        <div className="form-group">
          <label>Project ID</label>
          <input
            type="text"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="e.g., proj_demo"
            required
          />
        </div>

        <div className="form-group">
          <label>Select Files</label>
          <input
            type="file"
            onChange={handleFileChange}
            multiple
            accept=".pdf,.docx,.doc,.xlsx,.xls,.png,.jpg,.jpeg,.tiff"
          />
        </div>

        {files.length > 0 && (
          <div className="file-list">
            <h4>Selected Files:</h4>
            {files.map((file, index) => (
              <div key={index} className="file-item">
                <span>{file.name}</span>
                <span>{(file.size / 1024 / 1024).toFixed(2)} MB</span>
              </div>
            ))}
          </div>
        )}

        <button type="submit" className="btn" disabled={uploading}>
          {uploading ? 'Uploading...' : 'Upload Files'}
        </button>
      </form>

      <div style={{ marginTop: '2rem', paddingTop: '2rem', borderTop: '1px solid #ddd' }}>
        <h3>Ingest Project</h3>
        <p style={{ marginBottom: '1rem', color: '#555' }}>
          After uploading files, click here to process and index them.
        </p>
        <button
          className="btn btn-secondary"
          onClick={handleIngest}
          disabled={ingesting}
        >
          {ingesting ? 'Ingesting...' : 'Ingest Project'}
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}
    </div>
  )
}
