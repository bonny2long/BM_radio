import { useEffect, useState } from 'react'
import Artwork from '../components/Artwork'
import TrackActionSheet from '../components/TrackActionSheet'
import useLongPress from '../hooks/useLongPress'
import { getAlbumQueue, getAlbumTracks, mediaUrl, type AlbumSummary, type Track } from '../api'
import { useRadioActions } from '../hooks/useRadioActions'
import { usePlayback } from '../state/PlaybackContext'
import { trackToNowPlaying } from '../utils/mediaMappers'

export default function AlbumDetailPage({ album, onBack }: { album: AlbumSummary; onBack: () => void }) {
  const [tracks, setTracks] = useState<Track[]>([])
  const [actionTrack, setActionTrack] = useState<Track | null>(null)
  const { playQueue } = usePlayback()
  const { startSongRadio, saveSongStation } = useRadioActions()
  useEffect(() => { void getAlbumTracks(album.artist, album.title).then(setTracks) }, [album])
  const queue = tracks.map(track => trackToNowPlaying(track))
  const playAlbum = (shuffle = false) => void getAlbumQueue(album.artist, album.title, 500, shuffle).then(r => playQueue(r.queue.map(track => trackToNowPlaying(track))))
  return <div><button onClick={onBack} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 0', marginBottom: 16, minHeight: 44, color: 'var(--text-secondary)', fontSize: 14, fontWeight: 500 }}>&larr; Back to Library</button><div className="page-title-centered"><div style={{ display: 'grid', placeItems: 'center', width: '100%' }}><Artwork src={mediaUrl('/api/media/albums/cover?artist=' + encodeURIComponent(album.artist) + '&album=' + encodeURIComponent(album.title))} label={album.title} size={150} /></div><h1 style={{ marginTop: 16 }}>{album.title}</h1><p style={{ color: 'var(--text-muted)', fontSize: 13 }}>{album.artist} {'\u00b7'} {album.track_count} {album.track_count === 1 ? 'track' : 'tracks'}</p><div style={{ display: 'flex', justifyContent: 'center', gap: 10, marginTop: 20, padding: '0 8px' }}><button onClick={() => playAlbum(false)} style={{ flex: 1, maxWidth: 180, height: 46, borderRadius: 'var(--radius-m)', background: 'var(--accent-primary)', color: '#fff', fontWeight: 700, fontSize: 14, boxShadow: '0 4px 16px var(--accent-primary-glow)' }}>Play Album</button><button onClick={() => playAlbum(true)} style={{ flex: 1, maxWidth: 180, height: 46, borderRadius: 'var(--radius-m)', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)', fontWeight: 700, fontSize: 14 }}>Shuffle</button></div></div><p className="section-label" style={{ marginTop: 28 }}>Tracks</p>{tracks.map((track, i) => <AlbumTrackRow key={track.id} track={track} index={i} onPlay={() => playQueue(queue, i)} onAction={() => setActionTrack(track)} />)}<TrackActionSheet open={!!actionTrack} track={actionTrack} onClose={() => setActionTrack(null)} onStartRadio={startSongRadio} onSaveStation={saveSongStation} /></div>
}
function AlbumTrackRow({ track, onPlay, onAction }: { track: Track; index: number; onPlay: () => void; onAction: () => void }) { const longPress = useLongPress(onAction); return <div className="card-premium" style={{ width: '100%', padding: 12, marginBottom: 7, textAlign: 'left', display: 'flex', alignItems: 'center', gap: 8 }} {...longPress}><button onClick={onPlay} style={{ flex: 1, minWidth: 0, textAlign: 'left' }}><strong>{track.title}</strong><span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)' }}>{track.artist}</span></button><button className="track-overflow-button" aria-label="Track actions" onClick={(event) => { event.stopPropagation(); onAction() }}>&#8943;</button></div> }
