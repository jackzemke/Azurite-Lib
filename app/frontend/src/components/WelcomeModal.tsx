interface WelcomeModalProps {
  onDismiss: () => void
}

export default function WelcomeModal({ onDismiss }: WelcomeModalProps) {
  return (
    <div 
      className="welcome-modal-overlay"
      onClick={onDismiss}
    >
      <div 
        className="welcome-modal"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header with gradient */}
        <div className="welcome-header">
          <div className="welcome-icon">💎</div>
          <h1 className="welcome-title">Azurite Archive Assistant</h1>
          <p className="welcome-subtitle">Your AI-powered guide to SMA project knowledge</p>
        </div>

        {/* Content */}
        <div className="welcome-content">
          <div className="welcome-section">
            <h3>🔍 What can I help you find?</h3>
            <ul>
              <li><strong>Technical details</strong> — pipe depths, soil conditions, specifications</li>
              <li><strong>Project history</strong> — past work, similar projects, timelines</li>
              <li><strong>Documents</strong> — reports, drawings, field notes with exact citations</li>
            </ul>
          </div>

          <div className="welcome-section">
            <h3>💡 Tips for best results</h3>
            <ul>
              <li><strong>Be specific</strong> — "burial depth for 8-inch water line" works better than "pipe info"</li>
              <li><strong>Filter by employee</strong> — narrow results to your project history</li>
              <li><strong>Click citations</strong> — view original source documents directly</li>
            </ul>
          </div>

          <div className="welcome-section highlight">
            <h3>🚀 Quick Start</h3>
            <p>Try asking: <em>"What were the stormwater design criteria for the Acomita Day School project?"</em></p>
          </div>
        </div>

        {/* Footer */}
        <div className="welcome-footer">
          <label className="welcome-checkbox">
            <input
              type="checkbox"
              onChange={(e) => {
                if (e.target.checked) {
                  localStorage.setItem('aaa-welcome-dismissed', 'true')
                }
              }}
            />
            <span>Don't show this again</span>
          </label>
          <button className="welcome-btn" onClick={onDismiss}>
            Get Started
          </button>
        </div>
      </div>
    </div>
  )
}
