import { useState } from 'react'
import AppShell from './components/AppShell'
import HomePage from './pages/HomePage'
import RadioPage from './pages/RadioPage'
import BookshelfPage from './pages/BookshelfPage'
import LibraryPage from './pages/LibraryPage'
import NowPlayingPage from './pages/NowPlayingPage'
import { PlaybackProvider } from './state/PlaybackContext'
import './styles/tokens.css'
import './styles/base.css'
function App(){const [currentPage,setCurrentPage]=useState('home');const page=()=>{switch(currentPage){case'radio':return <RadioPage/>;case'bookshelf':return <BookshelfPage/>;case'library':return <LibraryPage/>;case'nowPlaying':return <NowPlayingPage onBack={()=>setCurrentPage('home')}/>;default:return <HomePage/>}};return <PlaybackProvider><AppShell currentPage={currentPage} onPageChange={setCurrentPage} onOpenNowPlaying={()=>setCurrentPage('nowPlaying')}>{page()}</AppShell></PlaybackProvider>}
export default App
