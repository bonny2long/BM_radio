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
  onSaveStation?: (track: Track) => void
}

type SheetMode = 'actions' | 'playlist'

export default function TrackActionSheet({ open, track, onClose, onPlayNow, onGoToAlbum, onGoToArtist, onStartRadio, onSaveStation }: TrackActionSheetProps) {
  const [favorite, setFavorite] = useState(false)
  const [mode, setMode] = useState<SheetMode>('actions')

  useEffect(() => {
    setMode('actions')
    if (open && track) void getTrackFavorite(track.id).then(r => setFavorite(r.favorite)).catch(() => setFavorite(false))
  }, [open, track?.id])

  const toggleFavorite = () => {
    if (!track) return
    void setTrackFavorite(track.id, !favorite).then(r => setFavorite(r.favorite)).catch(() => {})
  }

  const closeAll = () => {
    setMode('actions')
    onClose()
  }

  return (
    <BottomSheet open={open} title={mode === 'playlist' ? 'Add to playlist' : 'Track actions'} onClose={closeAll}>
      {mode === 'playlist' ? (
        <PlaylistPickerSheet
          embedded
          open={open}
          trackId={track?.id ?? null}
          trackTitle={track?.title}
          onBack={() => setMode('actions')}
          onClose={closeAll}
        />
      ) : (
        <>
          {track && <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{track.title}</p>}
          <div style={{ display: 'grid', gap: 8 }}>
            {onPlayNow && <button onClick={() => { onPlayNow(); closeAll() }} className="sheet-action-button">Play now</button>}
            {onStartRadio && track && <button onClick={() => { onStartRadio(track); closeAll() }} className="sheet-action-button" style={{ color: 'var(--accent-primary)', fontWeight: 700 }}>Start Song Radio</button>}
            {onSaveStation && track && <button onClick={() => { onSaveStation(track); closeAll() }} className="sheet-action-button">Save as Station</button>}
            <button onClick={() => setMode('playlist')} className="sheet-action-button">Add to playlist</button>
            <button onClick={toggleFavorite} className="sheet-action-button">{favorite ? 'Unfavorite' : 'Favorite'}</button>
            {track?.album && onGoToAlbum && <button onClick={() => { onGoToAlbum(track); closeAll() }} className="sheet-action-button">Go to album</button>}
            {track?.artist && onGoToArtist && <button onClick={() => { onGoToArtist(track); closeAll() }} className="sheet-action-button">Go to artist</button>}
          </div>
        </>
      )}
    </BottomSheet>
  )
}
