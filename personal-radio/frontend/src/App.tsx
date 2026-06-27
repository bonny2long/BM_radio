import { useEffect, useRef, useState } from 'react'
import { PlaybackProvider } from './state/PlaybackContext'
import AppShell from './components/AppShell'
import PageTransition from './components/PageTransition'
import HomePage from './pages/HomePage'
import RadioPage from './pages/RadioPage'
import LibraryPage from './pages/LibraryPage'
import BookshelfPage from './pages/BookshelfPage'
import NowPlayingPage from './pages/NowPlayingPage'
import QueuePage from './pages/QueuePage'
import AlbumDetailPage from './pages/AlbumDetailPage'
import ArtistDetailPage from './pages/ArtistDetailPage'
import PlaylistDetailPage from './pages/PlaylistDetailPage'
import type { AlbumSummary, ArtistSummary } from './api'
import './styles/tokens.css'
import './styles/base.css'
import './App.css'

const MODAL_PAGES = new Set(['nowPlaying', 'queue'])
const DETAIL_PAGES = new Set(['albumDetail', 'artistDetail', 'playlistDetail'])
const TAB_PAGES = new Set(['home', 'radio', 'library', 'bookshelf'])

function App() {
  const [currentPage, setCurrentPage] = useState('home')
  const [navType, setNavType] = useState<'tab' | 'push' | 'pop'>('tab')
  const [album, setAlbum] = useState<AlbumSummary | null>(null)
  const [artist, setArtist] = useState<string | null>(null)
  const [bookId, setBookId] = useState<number | null>(null)
  const [playlistId, setPlaylistId] = useState<number | null>(null)
  const [albumBack, setAlbumBack] = useState('library')
  const previousPage = useRef('home')
  const scrollMemory = useRef<Record<string, number>>({})

  const saveScroll = (page = currentPage) => {
    if (!MODAL_PAGES.has(page)) scrollMemory.current[page] = window.scrollY
  }

  const navigate = (page: string, type?: 'tab' | 'push' | 'pop') => {
    saveScroll()
    const inferredType = type ?? (
      DETAIL_PAGES.has(page) ? 'push' :
      TAB_PAGES.has(page) || MODAL_PAGES.has(page) ? 'tab' :
      'pop'
    )
    setNavType(inferredType)
    setCurrentPage(page)
  }

  useEffect(() => {
    if (MODAL_PAGES.has(currentPage)) return
    const y = scrollMemory.current[currentPage] ?? 0
    requestAnimationFrame(() => window.scrollTo({ top: y, behavior: 'instant' as ScrollBehavior }))
  }, [currentPage])

  const openAlbum = (a: AlbumSummary, back = 'library') => {
    setAlbum(a)
    setAlbumBack(back)
    navigate('albumDetail', 'push')
  }

  const openArtist = (a: ArtistSummary | string) => {
    setArtist(typeof a === 'string' ? a : a.name)
    navigate('artistDetail', 'push')
  }

  const openBook = (id: number) => {
    setBookId(id)
    navigate('bookshelf')
  }

  const openPlaylist = (id: number) => {
    setPlaylistId(id)
    navigate('playlistDetail', 'push')
  }

  const openNowPlaying = () => {
    if (currentPage !== 'nowPlaying' && currentPage !== 'queue') {
      saveScroll()
      previousPage.current = currentPage
    }
    setNavType('tab')
    setCurrentPage('nowPlaying')
  }

  const backFromNowPlaying = () => { setNavType('tab'); setCurrentPage(previousPage.current) }

  const page = () => {
    switch (currentPage) {
      case 'radio':
        return <RadioPage />
      case 'bookshelf':
        return <BookshelfPage initialBookId={bookId} />
      case 'library':
        return <LibraryPage onOpenAlbum={a => openAlbum(a, 'library')} onOpenArtist={openArtist} onOpenBook={openBook} onOpenPlaylist={openPlaylist} />
      case 'artistDetail':
        return artist ? <ArtistDetailPage artist={artist} onBack={() => navigate('library', 'pop')} onOpenAlbum={a => openAlbum(a, 'artistDetail')} /> : null
      case 'albumDetail':
        return album ? <AlbumDetailPage album={album} onBack={() => navigate(albumBack, 'pop')} /> : null
      case 'playlistDetail':
        return playlistId ? <PlaylistDetailPage playlistId={playlistId} onBack={() => navigate('library', 'pop')} /> : null
      case 'nowPlaying':
        return <NowPlayingPage onBack={backFromNowPlaying} onOpenQueue={() => navigate('queue', 'tab')} />
      case 'queue':
        return <QueuePage onBack={() => navigate('nowPlaying', 'tab')} />
      default:
        return <HomePage onOpenAlbum={a => openAlbum(a, 'home')} onOpenBookshelf={() => navigate('bookshelf')} onOpenBook={openBook} onOpenNowPlaying={openNowPlaying} />
    }
  }

  return (
    <PlaybackProvider>
      <AppShell currentPage={currentPage} onPageChange={navigate} onOpenNowPlaying={openNowPlaying} onOpenQueue={() => navigate('queue', 'tab')}>
        <PageTransition key={currentPage} pageKey={currentPage} navType={navType}>{page()}</PageTransition>
      </AppShell>
    </PlaybackProvider>
  )
}

export default App
