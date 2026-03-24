import React, { useState, useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import SearchPage from './pages/SearchPage'
import AdminPage from './pages/AdminPage'
import WelcomeModal from './components/WelcomeModal'
import './styles.css'

function App() {
  const [showAdminModal, setShowAdminModal] = useState(false)
  const [showWelcome, setShowWelcome] = useState(false)

  useEffect(() => {
    // Check if user has dismissed welcome before
    const dismissed = localStorage.getItem('aaa-welcome-dismissed')
    if (!dismissed) {
      setShowWelcome(true)
    }

    // Keyboard shortcut for admin panel (Ctrl+Shift+A)
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'A') {
        e.preventDefault()
        setShowAdminModal(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
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
      <SearchPage onOpenHelp={handleOpenHelp} />

      {/* Admin Dashboard Modal */}
      {showAdminModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 10000,
          }}
        >
          <AdminPage onClose={() => setShowAdminModal(false)} />
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
