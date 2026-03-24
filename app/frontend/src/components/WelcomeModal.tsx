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
          <h1 className="welcome-title">Azurite Archive Assistant</h1>
          <p className="welcome-subtitle">Find any SMA project using natural language</p>
        </div>

        {/* Content */}
        <div className="welcome-content">
          <div className="welcome-section">
            <h3>What can I help you find?</h3>
            <ul>
              <li><strong>Projects by name</strong> &mdash; "Find the Acomita Day School project"</li>
              <li><strong>Projects by department</strong> &mdash; "Water department projects"</li>
              <li><strong>Projects by client</strong> &mdash; "What projects did we do for NMED?"</li>
              <li><strong>Team members</strong> &mdash; "Who worked on this project?" (from Ajera timesheets)</li>
            </ul>
          </div>

          <div className="welcome-section">
            <h3>How it works</h3>
            <p style={{fontSize: '0.9rem', color: '#4b5563', lineHeight: 1.6}}>
              I search our project metadata index using AI-powered semantic matching.
              When I find matching projects, I can also pull team data from Ajera timesheets
              so you can see who logged time on each project.
            </p>
          </div>

          <div className="welcome-section highlight">
            <h3>Try these queries</h3>
            <ul style={{fontStyle: 'italic', color: '#4b5563'}}>
              <li>"Find environmental projects"</li>
              <li>"What projects did we do for NMED?"</li>
              <li>"Projects in the Water department"</li>
              <li>"Who worked on Acomita Day School?"</li>
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
