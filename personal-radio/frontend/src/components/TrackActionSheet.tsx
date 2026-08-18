import { useEffect, useState } from 'react'
import { clearRecordingPreferredTrack, getRecordingSourceControl, getTrackFavorite, setRecordingPreferredTrack, setTrackFavorite, type RecordingSourceControl, type Track } from '../api'
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

type SheetMode = 'actions' | 'playlist' | 'sources'

export default function TrackActionSheet({ open, track, onClose, onPlayNow, onGoToAlbum, onGoToArtist, onStartRadio, onSaveStation }: TrackActionSheetProps) {
  const [favorite, setFavorite] = useState(false)
  const [mode, setMode] = useState<SheetMode>('actions')
  const [sourceControl, setSourceControl] = useState<RecordingSourceControl | null>(null)
  const [sourceError, setSourceError] = useState<string | null>(null)

  useEffect(() => {
    setMode('actions')
    setSourceControl(null)
    setSourceError(null)
    if (open && track) void getTrackFavorite(track.id).then(r => setFavorite(r.favorite)).catch(() => setFavorite(false))
  }, [open, track?.id])

  const openSources = () => {
    if (!track?.recording_id) return
    setMode('sources')
    setSourceError(null)
    void getRecordingSourceControl(track.recording_id).then(setSourceControl).catch(() => setSourceError('Source details are unavailable right now.'))
  }

  const chooseSource = (trackId: number) => {
    if (!track?.recording_id) return
    setSourceError(null)
    void setRecordingPreferredTrack(track.recording_id, trackId).then(setSourceControl).catch(() => setSourceError('Could not change the preferred source.'))
  }

  const useAutomaticSource = () => {
    if (!track?.recording_id) return
    setSourceError(null)
    void clearRecordingPreferredTrack(track.recording_id).then(setSourceControl).catch(() => setSourceError('Could not restore automatic source selection.'))
  }

  const toggleFavorite = () => {
    if (!track) return
    void setTrackFavorite(track.id, !favorite).then(r => setFavorite(r.favorite)).catch(() => {})
  }

  const closeAll = () => {
    setMode('actions')
    onClose()
  }

  return (
    <BottomSheet open={open} title={mode === 'playlist' ? 'Add to playlist' : mode === 'sources' ? 'Source details' : 'Track actions'} onClose={closeAll}>
      {mode === 'playlist' ? (
        <PlaylistPickerSheet
          embedded
          open={open}
          trackId={track?.id ?? null}
          trackTitle={track?.title}
          onBack={() => setMode('actions')}
          onClose={closeAll}
        />
      ) : mode === 'sources' ? (
        <div style={{ display: 'grid', gap: 10 }}>
          <button onClick={() => setMode('actions')} className="sheet-action-button">Back to track actions</button>
          {!sourceControl && !sourceError && <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>Loading available sources…</p>}
          {sourceError && <p role="alert" style={{ color: 'var(--danger, #e57373)', fontSize: 13 }}>{sourceError}</p>}
          {sourceControl && (
            <>
              <p style={{ color: 'var(--text-secondary)', fontSize: 13, margin: 0 }}>
                Automatic quality selection is used unless you choose a copy. {sourceControl.candidates.length} physical {sourceControl.candidates.length === 1 ? 'source' : 'sources'} are preserved for this one song.
              </p>
              {sourceControl.candidates.map(candidate => {
                const technical = candidate.technical
                const format = (candidate.track.file_ext || technical?.codec || 'unknown').toUpperCase()
                const quality = technical?.is_lossless === true ? 'lossless' : technical?.is_lossless === false ? 'lossy' : 'quality unknown'
                const selected = candidate.preference_flags.is_effective_source
                return (
                  <button key={candidate.track_id} onClick={() => chooseSource(candidate.track_id)} className="sheet-action-button" aria-pressed={candidate.preference_flags.is_user_preferred}>
                    {format} · {quality}{selected ? ' · playing source' : ''}{candidate.preference_flags.is_auto_preferred ? ' · automatic pick' : ''}
                  </button>
                )
              })}
              <button onClick={useAutomaticSource} className="sheet-action-button" disabled={!sourceControl.preference?.user_preferred_track_id}>Use automatic source selection</button>
            </>
          )}
        </div>
      ) : (
        <>
          {track && <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{track.title}</p>}
          <div style={{ display: 'grid', gap: 8 }}>
            {onPlayNow && <button onClick={() => { onPlayNow(); closeAll() }} className="sheet-action-button">Play now</button>}
            {onStartRadio && track && <button onClick={() => { onStartRadio(track); closeAll() }} className="sheet-action-button" style={{ color: 'var(--accent-primary)', fontWeight: 700 }}>Start Song Radio</button>}
            {onSaveStation && track && <button onClick={() => { onSaveStation(track); closeAll() }} className="sheet-action-button">Save as Station</button>}
            <button onClick={() => setMode('playlist')} className="sheet-action-button">Add to playlist</button>
            <button onClick={toggleFavorite} className="sheet-action-button">{favorite ? 'Unfavorite' : 'Favorite'}</button>
            {track?.recording_id && <button onClick={openSources} className="sheet-action-button">Source details</button>}
            {track?.album && onGoToAlbum && <button onClick={() => { onGoToAlbum(track); closeAll() }} className="sheet-action-button">Go to album</button>}
            {track?.artist && onGoToArtist && <button onClick={() => { onGoToArtist(track); closeAll() }} className="sheet-action-button">Go to artist</button>}
          </div>
        </>
      )}
    </BottomSheet>
  )
}
