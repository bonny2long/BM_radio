import { useEffect, useState } from 'react'
import { getAudiobookSummary, getLibrarySummary, scanAudiobooks, scanMusic, type AudiobookSummary, type LibrarySummary } from '../api'
const emptyBooks: AudiobookSummary = { available: 0, not_started: 0, in_progress: 0, finished: 0, favorites: 0, total_listening_seconds: 0 }
type ScanResult = { tracks_scanned?: number; audiobooks_scanned?: number; errors?: string[] }
export default function HomePage() {
  const [library, setLibrary] = useState<LibrarySummary>({ tracks: 0, artists: 0, albums: 0 }); const [books, setBooks] = useState(emptyBooks); const [scanning, setScanning] = useState(false); const [scanMessage, setScanMessage] = useState<string | null>(null)
  const load = () => Promise.all([getLibrarySummary(), getAudiobookSummary()]).then(([l, b]) => { setLibrary(l); setBooks(b) }).catch(() => {})
  useEffect(() => { void load() }, [])
  const scan = async () => {
    setScanning(true); setScanMessage(null)
    try {
      const [music, audiobooks] = await Promise.all([scanMusic() as Promise<ScanResult>, scanAudiobooks() as Promise<ScanResult>])
      const total = (music.tracks_scanned ?? 0) + (audiobooks.audiobooks_scanned ?? 0)
      const errors = [...(music.errors ?? []), ...(audiobooks.errors ?? [])]
      setScanMessage(errors.length ? `Scan completed with ${errors.length} issue${errors.length === 1 ? '' : 's'}.` : total ? `Scan complete — found ${music.tracks_scanned ?? 0} tracks and ${audiobooks.audiobooks_scanned ?? 0} audiobooks.` : 'Scan complete — no supported media files were found in the approved final-library folders.')
      await load()
    } catch { setScanMessage('Scan could not reach the BM Radio backend. Confirm it is running on port 8094.') } finally { setScanning(false) }
  }
  return <div style={{ paddingBottom: 16 }}><div style={{ marginBottom: 28 }}><p className="section-label">Your personal library</p><h1 style={{ fontSize: '2rem', fontWeight: 800 }}>BM Radio</h1></div><section className="card-premium" style={{ padding: 24, marginBottom: 28, background: 'var(--gradient-radio)' }}><h3 style={{ fontSize: 20, marginBottom: 8 }}>Ready to listen</h3><p style={{ color: 'rgba(255,255,255,.75)', marginBottom: 18 }}>Scan your final music and audiobook libraries. Media files are never changed.</p><button onClick={() => void scan()} disabled={scanning} style={{ padding: '10px 15px', borderRadius: 20, background: '#fff', color: '#30276b', fontWeight: 700 }}>{scanning ? 'Scanning…' : 'Scan library'}</button>{scanMessage && <p style={{ color: '#fff', fontSize: 12, lineHeight: 1.5, marginTop: 14 }}>{scanMessage}</p>}</section><p className="section-label">Library at a glance</p><div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>{[['Tracks', library.tracks], ['Artists', library.artists], ['Albums', library.albums], ['Books Available', books.available], ['Books In Progress', books.in_progress]].map(([label, value]) => <div className="card-premium" style={{ padding: 16 }} key={String(label)}><strong style={{ display: 'block', fontSize: 28 }}>{value}</strong><span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{label}</span></div>)}</div></div>
}
