import React, { useState, useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import SearchPage from './pages/SearchPage'
import UploadPage from './pages/UploadPage'
import WelcomeModal from './components/WelcomeModal'
import './styles.css'

function App() {
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [showWelcome, setShowWelcome] = useState(false)

  useEffect(() => {
    // Check if user has dismissed welcome before
    const dismissed = localStorage.getItem('aaa-welcome-dismissed')
    if (!dismissed) {
      setShowWelcome(true)
    }
  }, [])

  const handleDismissWelcome = () => {
    setShowWelcome(false)
  }

  const handleOpenHelp = () => {
    setShowWelcome(true)
  }

  return (
    <div className="app">
      {/* Welcome Modal (first-time users) */}
      {showWelcome && (
        <WelcomeModal onDismiss={handleDismissWelcome} />
      )}

      {/* Main Chat Interface */}
      <SearchPage 
        onOpenUpload={() => setShowUploadModal(true)} 
        onOpenHelp={handleOpenHelp}
      />

      {/* Upload Modal Overlay */}
      {showUploadModal && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            backdropFilter: 'blur(4px)'
          }}
          onClick={() => setShowUploadModal(false)}
        >
          <div 
            style={{
              backgroundColor: 'white',
              borderRadius: '16px',
              maxWidth: '800px',
              width: '90%',
              maxHeight: '90vh',
              overflow: 'auto',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.3)',
              position: 'relative'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close button */}
            <button
              onClick={() => setShowUploadModal(false)}
              style={{
                position: 'absolute',
                top: '1rem',
                right: '1rem',
                background: 'none',
                border: 'none',
                fontSize: '1.5rem',
                cursor: 'pointer',
                color: '#6b7280',
                padding: '0.25rem 0.5rem',
                borderRadius: '6px',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#f3f4f6'
                e.currentTarget.style.color = '#111827'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
                e.currentTarget.style.color = '#6b7280'
              }}
            >
              ✕
            </button>

            {/* Upload Page Content */}
            <UploadPage onClose={() => setShowUploadModal(false)} />
          </div>
        </div>
      )}
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
