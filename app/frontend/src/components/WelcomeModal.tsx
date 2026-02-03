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
              <li><strong>Project details</strong> — "Who was the client?" "What was the scope?"</li>
              <li><strong>Technical specs</strong> — pipe depths, soil conditions, design criteria</li>
              <li><strong>Team info</strong> — "Who worked on this project?" (pulls from Ajera timesheets)</li>
              <li><strong>Documents</strong> — reports, proposals, field notes with citations</li>
            </ul>
          </div>

          <div className="welcome-section">
            <h3>👤 Filter Options</h3>
            <ul>
              <li><strong>By Employee</strong> — Select yourself to see only your project history</li>
              <li><strong>By Project</strong> — Focus on specific indexed projects</li>
            </ul>
            <p style={{fontSize: '0.85rem', color: '#6b7280', marginTop: '0.5rem'}}>
              💡 When you select an employee, results are filtered to projects they've logged time on in Ajera.
            </p>
          </div>

          <div className="welcome-section highlight">
            <h3>🚀 Try These Questions</h3>
            <ul style={{fontStyle: 'italic', color: '#4b5563'}}>
              <li>"Who was the client for this project?"</li>
              <li>"Who worked on this project?" (uses Ajera data)</li>
              <li>"What was the project about?"</li>
              <li>"What soil conditions were found?"</li>
            </ul>
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
