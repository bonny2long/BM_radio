import { useEffect, useState } from 'react'
import {
  getAlbums,
  getLibrarySummary,
  type AlbumSummary,
  type LibrarySummary,
} from '../api'

const emptySummary: LibrarySummary = { tracks: 0, artists: 0, albums: 0 }

export default function LibraryPage() {
  const [summary, setSummary] = useState<LibrarySummary>(emptySummary)
  const [albums, setAlbums] = useState<AlbumSummary[]>([])
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    void Promise.all([getLibrarySummary(), getAlbums()])
      .then(([nextSummary, nextAlbums]) => {
        setSummary(nextSummary)
        setAlbums(nextAlbums)
      })
      .catch(() => setFailed(true))
  }, [])

  if (failed) {
    return <div style={{ paddingBottom: 16 }}><h1 style={{ fontSize: '2rem', fontWeight: 800 }}>Library</h1><p style={{ color: 'var(--text-muted)' }}>BM Radio could not reach the library service.</p></div>
  }

  if (summary.tracks === 0) {
    return <div style={{ paddingBottom: 16 }}><div style={{ marginBottom: 28 }}><h1 style={{ fontSize: '2rem', fontWeight: 800 }}>Library</h1><p style={{ fontSize: 13, color: 'var(--text-muted)' }}>All your music in one place</p></div><div className="card-premium" style={{ padding: 24, textAlign: 'center' }}><p style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 5 }}>No music indexed yet</p><p style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>Run a library scan from Home to index your final music folders.</p></div></div>
  }

  return <div style={{ paddingBottom: 16 }}><div style={{ marginBottom: 28 }}><h1 style={{ fontSize: '2rem', fontWeight: 800 }}>Library</h1><p style={{ fontSize: 13, color: 'var(--text-muted)' }}>{summary.tracks} tracks · {summary.artists} artists · {summary.albums} albums</p></div><p className="section-label">Albums</p><div style={{ display: 'grid', gap: 10 }}>{albums.map((album) => <div className="card-premium" style={{ padding: 16 }} key={`${album.artist}-${album.title}`}><strong style={{ display: 'block', color: 'var(--text-primary)' }}>{album.title}</strong><span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{album.artist} · {album.track_count} tracks</span></div>)}</div></div>
}