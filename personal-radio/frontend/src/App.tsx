import { useState } from 'react'
import AppShell from './components/AppShell'
import HomePage from './pages/HomePage'
import RadioPage from './pages/RadioPage'
import BookshelfPage from './pages/BookshelfPage'
import './styles/tokens.css'
import './styles/base.css'

function App() {
  const [currentPage, setCurrentPage] = useState('home')

  const renderPage = () => {
    switch (currentPage) {
      case 'home':
        return <HomePage />
      case 'radio':
        return <RadioPage />
      case 'bookshelf':
        return <BookshelfPage />
      case 'library':
        return (
          <div style={{ paddingBottom: '16px' }}>
            <div style={{ marginBottom: '28px' }}>
              <h1 style={{ 
                fontSize: '2rem', 
                fontWeight: 800, 
                letterSpacing: '-0.03em',
                marginBottom: '4px',
              }}>
                Library
              </h1>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                All your music in one place
              </p>
            </div>
            <div style={{
              borderRadius: 'var(--radius-l)',
              background: 'var(--bg-card)',
              border: '1px dashed rgba(255,255,255,0.06)',
              padding: '48px 24px',
              textAlign: 'center',
            }}>
              <div style={{
                width: '56px',
                height: '56px',
                borderRadius: '50%',
                background: 'var(--accent-primary-dim)',
                border: '1px solid var(--border-accent)',
                margin: '0 auto 14px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent-primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 18V5l12-2v13"/>
                  <circle cx="6" cy="18" r="3"/>
                  <circle cx="18" cy="16" r="3"/>
                </svg>
              </div>
              <p style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '5px' }}>
                Library not scanned
              </p>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Run a library scan to see your albums,<br />artists, and tracks here.
              </p>
            </div>
          </div>
        )
      default:
        return <HomePage />
    }
  }

  return (
    <AppShell currentPage={currentPage} onPageChange={setCurrentPage}>
      {renderPage()}
    </AppShell>
  )
}

export default App
