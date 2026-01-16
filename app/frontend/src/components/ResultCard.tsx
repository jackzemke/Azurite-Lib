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

interface Props {
  result: QueryResponse
}

export default function ResultCard({ result }: Props) {
  const handleCitationClick = (citation: Citation) => {
    // Open document in new tab
    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
    const documentUrl = `${API_URL}/api/v1/projects/${citation.project_id}/documents/${encodeURIComponent(citation.file_path)}`
    
    console.log('Opening document:', documentUrl)
    console.log('Citation details:', citation)
    
    window.open(documentUrl, '_blank')
  }

  return (
    <div className="result-card">
      <div className="answer">{result.answer}</div>

      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        gap: '1rem', 
        flexWrap: 'wrap',
        marginBottom: '0.5rem'
      }}>
        <span className={`confidence confidence-${result.confidence}`}>
          {result.confidence} confidence
        </span>
        <span style={{ 
          color: '#9ca3af', 
          fontSize: '0.8rem',
          fontWeight: 500
        }}>
          {result.elapsed_ms}ms response time
        </span>
        {result.stub_mode && (
          <span
            style={{
              padding: '0.375rem 0.75rem',
              background: '#fef3c7',
              color: '#92400e',
              fontSize: '0.75rem',
              fontWeight: 600,
              borderRadius: '20px',
              border: '1px solid #fcd34d',
              letterSpacing: '0.5px',
              textTransform: 'uppercase'
            }}
          >
            Demo Mode
          </span>
        )}
      </div>

      {result.citations.length > 0 && (
        <div className="citations">
          <h4>Sources ({result.citations.length}) - Click to view document</h4>
          {result.citations.map((citation, index) => (
            <div
              key={index}
              className="citation"
              onClick={() => handleCitationClick(citation)}
              style={{ cursor: 'pointer' }}
              title="Click to open document"
            >
              <div className="file">
                <span style={{
                  display: 'inline-block',
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  color: 'white',
                  padding: '0.25rem 0.625rem',
                  borderRadius: '6px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  marginRight: '0.625rem',
                  letterSpacing: '0.3px'
                }}>
                  {citation.project_id}
                </span>
                {citation.file_path.split('/').pop()}
              </div>
              <div className="page">
                Page {citation.page} • {citation.chunk_id}
              </div>
              <div className="excerpt">"{citation.text_excerpt}"</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
