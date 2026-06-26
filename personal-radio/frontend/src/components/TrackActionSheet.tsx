import { useEffect, useState } from 'react'
import { getTrackFavorite, setTrackFavorite, type Track } from '../api'
import BottomSheet from './BottomSheet'
import PlaylistPickerSheet from './PlaylistPickerSheet'

type TrackActionSheetProps = {
  open: boolean
  track: Track | null
  onClose: () => void
  onPlayNow?: () => void
  onGoToAlbum?: (track: Track) => void
  onGoToArtist?: (track: Track) => void
  onStartRadio?: (track: Track) => void
}

export default function TrackActionSheet({ open, track, onClose, onPlayNow, onGoToAlbum, onGoToArtist, onStartRadio }: TrackActionSheetProps) {
  const [favorite, setFavorite] = useState(false)
  const [showPlaylist, setShowPlaylist] = useState(false)

  useEffect(() => {
    setShowPlaylist(false)
    if (open && track) void getTrackFavorite(track.id).then(r => setFavorite(r.favorite)).catch(() => setFavorite(false))
  }, [open, track?.id])

  const toggleFavorite = () => {
    if (!track) return
    void setTrackFavorite(track.id, !favorite).then(r => setFavorite(r.favorite)).catch(() => {})
  }

  const closeAll = () => {
    setShowPlaylist(false)
    onClose()
  }

  return (
    <>
      <BottomSheet open={open && !showPlaylist} title="Track actions" onClose={onClose}>
        {track && <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 14 }}>{track.title}</p>}
        <div style={{ display: 'grid', gap: 8 }}>
          {onPlayNow && <button onClick={() => { onPlayNow(); onClose() }} className="sheet-action-button">Play now</button>}
          {onStartRadio && track && <button onClick={() => { onStartRadio(track); onClose() }} className="sheet-action-button" style={{ color: 'var(--accent-primary)', fontWeight: 700 }}>Start Song Radio</button>}
          <button onClick={() => setShowPlaylist(true)} className="sheet-action-button">Add to playlist</button>
          <button onClick={toggleFavorite} className="sheet-action-button">{favorite ? 'Unfavorite' : 'Favorite'}</button>
          {track?.album && onGoToAlbum && <button onClick={() => { onGoToAlbum(track); onClose() }} className="sheet-action-button">Go to album</button>}
          {track?.artist && onGoToArtist && <button onClick={() => { onGoToArtist(track); onClose() }} className="sheet-action-button">Go to artist</button>}
        </div>
      </BottomSheet>
      <PlaylistPickerSheet open={open && showPlaylist} trackId={track?.id ?? null} trackTitle={track?.title} onClose={closeAll} />
    </>
  )
}