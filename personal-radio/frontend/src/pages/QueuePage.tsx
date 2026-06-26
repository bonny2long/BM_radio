import { useMemo, useState } from 'react'
import Artwork from '../components/Artwork'
import BottomSheet from '../components/BottomSheet'
import TrackActionSheet from '../components/TrackActionSheet'
import { createPlaylistFromTrackList, type Track } from '../api'
import { useRadioActions } from '../hooks/useRadioActions'
import { usePlayback, type NowPlaying } from '../state/PlaybackContext'

const asTrack = (item: NowPlaying): Track => ({
  id: item.id,
  title: item.title,
  artist: item.artist ?? item.subtitle?.split(' - ')[0] ?? '',
  album: item.album ?? '',
  duration_seconds: item.durationSeconds,
  stream_url: item.streamUrl,
  cover_url: item.coverUrl,
})

export default function QueuePage({ onBack }: { onBack: () => void }) {
  const { queue, queueIndex, playQueue, nowPlaying, queueSource } = usePlayback()
  const { startSongRadio, saveSongStation } = useRadioActions()
  const [actionTrack, setActionTrack] = useState<Track | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState('Queue Mix')
  const [status, setStatus] = useState('')
  const current = queue[queueIndex] ?? nowPlaying
  const upcoming = queue.slice(Math.max(queueIndex + 1, 0))
  const musicQueue = useMemo(() => queue.filter(item => item.mode === 'music'), [queue])

  const shuffleUpcoming = () => {
    if (!current) return
    const before = queue.slice(0, queueIndex + 1)
    const rest = [...queue.slice(queueIndex + 1)]
    for (let i = rest.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[rest[i], rest[j]] = [rest[j], rest[i]]
    }
    playQueue([...before, ...rest], queueIndex, queueSource ?? undefined)
  }

  const saveQueue = async () => {
    const value = name.trim()
    if (!value || !musicQueue.length) return
    try {
      await createPlaylistFromTrackList(value, musicQueue.map(item => item.id), 'Saved from queue')
      setStatus('Saved playlist')
      window.setTimeout(() => setSaveOpen(false), 700)
    } catch {
      setStatus('Could not save queue')
    }
  }

  return (
    <div>
      <button onClick={onBack} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 0', marginBottom: 16, minHeight: 44, color: 'var(--text-secondary)', fontSize: 14, fontWeight: 500 }}>&larr; Back</button>
      <h1 style={{ fontSize: '1.8rem', fontWeight: 800, letterSpacing: '-0.03em', marginBottom: 18 }}>Queue</h1>

      {current ? (
        <div className="card-premium" style={{ width: '100%', padding: 14, marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center', textAlign: 'left', borderColor: 'var(--accent-primary)' }}>
          <Artwork src={current.coverUrl} label={current.title} size={58} kind={current.mode === 'audiobook' ? 'book' : 'music'} />
          <span style={{ flex: 1, minWidth: 0 }}>
            <span className="section-label" style={{ marginBottom: 4, color: 'var(--accent-primary)' }}>Now Playing</span>
            <strong style={{ display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{current.title}</strong>
            <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{current.subtitle}</span>
          </span>
        </div>
      ) : (
        <div className="card-premium" style={{ padding: 24, textAlign: 'center', marginBottom: 16 }}>Nothing queued yet.</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 20 }}>
        <button onClick={shuffleUpcoming} disabled={upcoming.length < 2} className="card-premium" style={{ padding: 12, color: 'var(--text-primary)', fontWeight: 800, opacity: upcoming.length < 2 ? .45 : 1 }}>Shuffle Up Next</button>
        <button onClick={() => { setStatus(''); setSaveOpen(true) }} disabled={!musicQueue.length} className="card-premium" style={{ padding: 12, color: 'var(--text-primary)', fontWeight: 800, opacity: musicQueue.length ? 1 : .45 }}>Save Queue</button>
      </div>

      <p className="section-label">Up Next</p>
      <div style={{ display: 'grid', gap: 8 }}>
        {upcoming.map((item, offset) => {
          const index = queueIndex + 1 + offset
          const track = item.mode === 'music' ? asTrack(item) : null
          return (
            <div key={`${item.id}-${index}`} className="card-premium" style={{ padding: 10, display: 'flex', gap: 10, alignItems: 'center' }}>
              <button onClick={() => playQueue(queue, index, queueSource ?? undefined)} style={{ display: 'flex', gap: 10, alignItems: 'center', flex: 1, minWidth: 0, textAlign: 'left' }}>
                <Artwork src={item.coverUrl} label={item.title} size={44} kind={item.mode === 'audiobook' ? 'book' : 'music'} />
                <span style={{ minWidth: 0 }}>
                  <strong style={{ display: 'block', fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.title}</strong>
                  <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.subtitle}</span>
                </span>
              </button>
              {track && <button className="track-overflow-button" aria-label="Track actions" onClick={() => setActionTrack(track)}>&#8943;</button>}
            </div>
          )
        })}
        {!upcoming.length && queue.length > 0 && <div className="card-premium" style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)' }}>End of queue.</div>}
      </div>

      <TrackActionSheet open={!!actionTrack} track={actionTrack} onClose={() => setActionTrack(null)} onStartRadio={startSongRadio} onSaveStation={saveSongStation} />
      <BottomSheet open={saveOpen} title="Save Queue" onClose={() => setSaveOpen(false)}>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 12 }}>Save the current music queue as a manual playlist.</p>
        <input value={name} onChange={event => setName(event.target.value)} placeholder="Playlist name" style={{ width: '100%', boxSizing: 'border-box', padding: '11px 12px', borderRadius: 'var(--radius-pill)', border: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', color: 'var(--text-primary)', marginBottom: 10 }} />
        <button onClick={() => void saveQueue()} disabled={!name.trim() || !musicQueue.length} style={{ width: '100%', padding: 12, borderRadius: 'var(--radius-pill)', background: 'var(--accent-primary)', color: '#fff', fontWeight: 800, opacity: name.trim() && musicQueue.length ? 1 : .45 }}>Save Queue</button>
        {status && <p style={{ fontSize: 12, color: status.includes('Could') ? '#ff8888' : 'var(--accent-primary)', marginTop: 10 }}>{status}</p>}
      </BottomSheet>
    </div>
  )
}