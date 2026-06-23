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
          <div>
            <h1>Library</h1>
            <p style={{ color: 'var(--text-secondary)' }}>Library view placeholder</p>
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
