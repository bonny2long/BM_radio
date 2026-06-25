import { useRef, useState } from 'react'
import AppShell from './components/AppShell'
import HomePage from './pages/HomePage'
import RadioPage from './pages/RadioPage'
import BookshelfPage from './pages/BookshelfPage'
import LibraryPage from './pages/LibraryPage'
import NowPlayingPage from './pages/NowPlayingPage'
import QueuePage from './pages/QueuePage'
import AlbumDetailPage from './pages/AlbumDetailPage'
import { PlaybackProvider } from './state/PlaybackContext'
import type { AlbumSummary } from './api'
import './styles/tokens.css'
import './styles/base.css'

function App(){const [currentPage,setCurrentPage]=useState('home');const [album,setAlbum]=useState<AlbumSummary|null>(null);const previousPage=useRef('home');const navigate=(page:string)=>setCurrentPage(page);const openNowPlaying=()=>{if(currentPage!=='nowPlaying'&&currentPage!=='queue')previousPage.current=currentPage;setCurrentPage('nowPlaying')};const backFromNowPlaying=()=>setCurrentPage(previousPage.current);const page=()=>{switch(currentPage){case'radio':return <RadioPage/>;case'bookshelf':return <BookshelfPage/>;case'library':return <LibraryPage onOpenAlbum={a=>{setAlbum(a);navigate('albumDetail')}} onOpenArtist={()=>{}}/>;case'albumDetail':return album?<AlbumDetailPage album={album} onBack={()=>navigate('library')}/>:null;case'nowPlaying':return <NowPlayingPage onBack={backFromNowPlaying} onOpenQueue={()=>navigate('queue')}/>;case'queue':return <QueuePage onBack={()=>navigate('nowPlaying')}/>;default:return <HomePage/>}};return <PlaybackProvider><AppShell currentPage={currentPage} onPageChange={navigate} onOpenNowPlaying={openNowPlaying} onOpenQueue={()=>navigate('queue')}>{page()}</AppShell></PlaybackProvider>}
export default App