import { useEffect, useState } from 'react'
import { addTrackToPlaylist, createPlaylist, getPlaylist, getPlaylists, type PlaylistSummary } from '../api'
import BottomSheet from './BottomSheet'

type PlaylistPickerSheetProps = {
  open: boolean
  trackId: number | null
  trackTitle?: string
  onClose: () => void
  onAdded?: () => void
  embedded?: boolean
  onBack?: () => void
}

function PlaylistPickerContent({ open, trackId, trackTitle, onClose, onAdded, onBack }: PlaylistPickerSheetProps) {
  const [playlists, setPlaylists] = useState<PlaylistSummary[]>([])
  const [newPlaylist, setNewPlaylist] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    void getPlaylists()
      .then(setPlaylists)
      .catch(() => setStatus('Could not load playlists.'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!open) return
    setStatus('')
    setNewPlaylist('')
    load()
  }, [open, trackId])

  const addTo = async (playlist: PlaylistSummary) => {
    if (!trackId || typeof playlist.id !== 'number') return
    setBusy(true)
    setStatus('')
    try {
      const detail = await getPlaylist(playlist.id)
      if (detail.tracks.some(track => track.id === trackId)) {
        setStatus('Already added')
        return
      }
      await addTrackToPlaylist(playlist.id, trackId)
      setStatus('Added to playlist')
      onAdded?.()
      load()
    } catch {
      setStatus('Could not add track')
    } finally {
      setBusy(false)
    }
  }

  const createAndAdd = async () => {
    const name = newPlaylist.trim()
    if (!name || !trackId) return
    setBusy(true)
    setStatus('')
    try {
      const playlist = await createPlaylist(name)
      if (typeof playlist.id === 'number') await addTrackToPlaylist(playlist.id, trackId)
      setNewPlaylist('')
      setStatus('Added to playlist')
      onAdded?.()
      load()
    } catch {
      setStatus('Could not add track')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {onBack && <button onClick={onBack} style={{ color: 'var(--text-secondary)', fontSize: 13, fontWeight: 700, marginBottom: 12 }}>← Back to actions</button>}
      {trackTitle && <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 16, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{trackTitle}</p>}
      <p className="section-label" style={{ marginBottom: 8 }}>Existing playlists</p>
      <div style={{ display: 'grid', gap: 8, marginBottom: 16 }}>
        {loading && <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading playlists…</p>}
        {!loading && playlists.map(playlist => (
          <button
            key={playlist.id}
            disabled={busy || !trackId}
            onClick={() => void addTo(playlist)}
            className="card-premium"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, textAlign: 'left', padding: '12px 13px', color: 'var(--text-primary)', opacity: busy ? .7 : 1 }}
          >
            <span style={{ minWidth: 0 }}>
              <strong style={{ display: 'block', fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{playlist.name}</strong>
              <span style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{playlist.track_count} {playlist.track_count === 1 ? 'track' : 'tracks'}</span>
            </span>
            <span style={{ fontSize: 12, color: 'var(--accent-primary)', fontWeight: 800, flexShrink: 0 }}>Add</span>
          </button>
        ))}
        {!loading && !playlists.length && <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>No playlists yet.</p>}
      </div>
      <p className="section-label" style={{ marginBottom: 8 }}>Create new playlist</p>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={newPlaylist}
          onChange={event => setNewPlaylist(event.target.value)}
          onKeyDown={event => event.key === 'Enter' && void createAndAdd()}
          placeholder="Playlist name"
          style={{ flex: 1, minWidth: 0, padding: '11px 12px', borderRadius: 'var(--radius-pill)', border: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
        />
        <button
          onClick={() => void createAndAdd()}
          disabled={busy || !newPlaylist.trim() || !trackId}
          style={{ padding: '10px 14px', borderRadius: 'var(--radius-pill)', background: 'var(--accent-primary)', color: '#fff', fontWeight: 800, opacity: newPlaylist.trim() ? 1 : .45 }}
        >
          Create
        </button>
      </div>
      {status && <p style={{ fontSize: 12, color: status.includes('Could') ? '#ff8888' : 'var(--accent-primary)', marginTop: 12 }}>{status}</p>}
      <button onClick={onClose} style={{ width: '100%', padding: 12, marginTop: 14, borderRadius: 'var(--radius-pill)', background: 'var(--bg-surface)', color: 'var(--text-primary)', fontWeight: 800 }}>Done</button>
    </div>
  )
}

export default function PlaylistPickerSheet(props: PlaylistPickerSheetProps) {
  if (props.embedded) return <PlaylistPickerContent {...props} />

  return (
    <BottomSheet open={props.open} title="Add to playlist" onClose={props.onClose}>
      <PlaylistPickerContent {...props} />
    </BottomSheet>
  )
}

