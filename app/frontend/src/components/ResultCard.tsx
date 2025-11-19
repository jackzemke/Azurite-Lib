import React from 'react'

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
    console.log('Citation clicked:', citation)
    // TODO: Implement PDF viewer navigation
    alert(`Opening: ${citation.file_path}\nPage: ${citation.page}`)
  }

  return (
    <div className="result-card">
      <div className="answer">{result.answer}</div>

      <div>
        <span className={`confidence confidence-${result.confidence}`}>
          {result.confidence.toUpperCase()} CONFIDENCE
        </span>
        <span style={{ marginLeft: '1rem', color: '#7f8c8d', fontSize: '0.85rem' }}>
          {result.elapsed_ms}ms
        </span>
        {result.stub_mode && (
          <span
            style={{
              marginLeft: '1rem',
              padding: '0.25rem 0.5rem',
              background: '#ffeaa7',
              color: '#856404',
              fontSize: '0.75rem',
              borderRadius: '4px',
            }}
          >
            STUB MODE
          </span>
        )}
      </div>

      {result.citations.length > 0 && (
        <div className="citations">
          <h4>Citations ({result.citations.length})</h4>
          {result.citations.map((citation, index) => (
            <div
              key={index}
              className="citation"
              onClick={() => handleCitationClick(citation)}
            >
              <div className="file">
                <strong style={{color: '#0066cc', marginRight: '8px'}}>[{citation.project_id}]</strong>
                {citation.file_path.split('/').pop()}
              </div>
              <div className="page">Page {citation.page} • {citation.chunk_id}</div>
              <div className="excerpt">"{citation.text_excerpt}"</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
