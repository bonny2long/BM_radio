import { useEffect, useRef, useState } from 'react'
import { usePlayback } from '../state/PlaybackContext'
import Artwork from '../components/Artwork'
import IconButton from '../components/IconButton'
import MarqueeText from '../components/MarqueeText'
import ProgressBar from '../components/ProgressBar'
import {
  favoriteAudiobook,
  getAudiobook,
  getTrackFavorite,
  getTrackFeedback,
  setTrackFavorite,
  setTrackFeedback,
} from '../api'
import PlaylistPickerSheet from '../components/PlaylistPickerSheet'
import {
  HeartIcon,
  NextIcon,
  PauseIcon,
  PlayIcon,
  PreviousIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from '../components/PlayerIcons'

const AddIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <line x1="3" y1="6" x2="15" y2="6" />
    <line x1="3" y1="11" x2="12" y2="11" />
    <line x1="3" y1="16" x2="10" y2="16" />
    <line x1="17" y1="10" x2="17" y2="18" />
    <line x1="13" y1="14" x2="21" y2="14" />
  </svg>
)

const QueueIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <line x1="3" y1="6" x2="21" y2="6" />
    <line x1="3" y1="12" x2="15" y2="12" />
    <line x1="3" y1="18" x2="12" y2="18" />
  </svg>
)

const backStyle = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  padding: '10px 0',
  minHeight: 44,
  color: 'var(--text-secondary)',
  fontSize: 14,
  fontWeight: 500,
} as const

export default function NowPlayingPage({
  onBack,
  onOpenQueue,
}: {
  onBack: () => void
  onOpenQueue: () => void
}) {
  const {
    nowPlaying,
    queue,
    queueIndex,
    isPlaying,
    currentTime,
    duration,
    togglePlayPause,
    next,
    previous,
    seek,
  } = usePlayback()

  const [feedback, setFeedback] = useState('neutral')
  const [favorite, setFavorite] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const artworkZoneRef = useRef<HTMLDivElement>(null)
  const [artworkSize, setArtworkSize] = useState(240)

  useEffect(() => {
    const el = artworkZoneRef.current
    if (!el) return

    const update = () => {
      const available = Math.min(el.clientHeight, el.clientWidth)
      setArtworkSize(Math.max(180, Math.min(300, available - 16)))
    }

    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    let alive = true
    setFeedback('neutral')
    setFavorite(false)
    setShowAdd(false)
    if (!nowPlaying) return

    if (nowPlaying.mode === 'music') {
      void getTrackFeedback(nowPlaying.id)
        .then(r => { if (alive) setFeedback(r.value) })
        .catch(() => {})
      void getTrackFavorite(nowPlaying.id)
        .then(r => { if (alive) setFavorite(r.favorite) })
        .catch(() => {})
    } else if (nowPlaying.audiobookId) {
      void getAudiobook(nowPlaying.audiobookId)
        .then(r => { if (alive) setFavorite(r.favorite) })
        .catch(() => {})
    }

    return () => { alive = false }
  }, [nowPlaying?.id, nowPlaying?.mode, nowPlaying?.audiobookId])


  if (!nowPlaying) {
    return (
      <div className="np-layout">
        <div className="np-top-bar">
          <button onClick={onBack} style={backStyle}>← Back</button>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="card-premium" style={{ padding: 28, textAlign: 'center', width: '100%' }}>
            <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
              Choose a station, album, or book to begin playing.
            </p>
          </div>
        </div>
      </div>
    )
  }

  const music = nowPlaying.mode === 'music'
  const hasPrev = queueIndex > 0
  const hasNext = queueIndex < queue.length - 1
  const sourceLabel = nowPlaying.stationName ?? (music ? 'NOW PLAYING' : 'AUDIOBOOK')

  const thumb = (value: 'thumbs_up' | 'thumbs_down') => {
    if (!music) return
    const active = value === 'thumbs_up' ? 'up' : 'down'
    const nextValue = feedback === active ? 'neutral' : value
    void setTrackFeedback(nowPlaying.id, nextValue)
      .then(r => setFeedback(r.value))
      .catch(() => {})
  }

  const fav = () => {
    if (music) {
      void setTrackFavorite(nowPlaying.id, !favorite)
        .then(r => setFavorite(r.favorite))
        .catch(() => {})
    } else if (nowPlaying.audiobookId) {
      void favoriteAudiobook(nowPlaying.audiobookId)
        .then(r => setFavorite(r.favorite))
        .catch(() => {})
    }
  }


  return (
    <div className="np-layout">
      <div className="np-top-bar">
        <button onClick={onBack} style={backStyle}>← Back</button>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-muted)', maxWidth: 150, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {sourceLabel}
        </span>
        <div style={{ width: 60 }} />
      </div>

      <div className="np-artwork-zone" ref={artworkZoneRef}>
        <div style={{ filter: 'drop-shadow(0 24px 48px rgba(139,109,255,0.45))', transition: 'filter 0.4s ease' }}>
          <Artwork
            src={nowPlaying.coverUrl}
            label={nowPlaying.title}
            size={artworkSize}
            kind={music ? 'music' : 'book'}
            variant="rounded"
          />
        </div>
      </div>

      <div className="np-bottom-sheet">
        <div className="np-meta">
          <div className="np-meta-text">
            <MarqueeText
              as="h1"
              text={nowPlaying.title}
              restartKey={nowPlaying.id}
              style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-0.025em', lineHeight: 1.2, marginBottom: 4, color: 'var(--text-primary)' }}
            />
            <MarqueeText
              as="p"
              text={nowPlaying.subtitle}
              restartKey={`${nowPlaying.id}-sub`}
              style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.35, margin: 0 }}
            />
            {!music && nowPlaying.tertiary && (
              <MarqueeText
                as="p"
                text={nowPlaying.tertiary}
                restartKey={`${nowPlaying.id}-ter`}
                style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.35, marginTop: 3 }}
              />
            )}
          </div>
          <IconButton label={favorite ? 'Unfavorite' : 'Favorite'} onClick={fav} active={favorite} size={44} variant="ghost">
            <HeartIcon />
          </IconButton>
        </div>

        <div className="np-progress">
          <ProgressBar current={currentTime} duration={duration} onSeek={seek} />
        </div>

        <div className="np-controls">
          {music ? (
            <IconButton label="Thumb down" onClick={() => thumb('thumbs_down')} active={feedback === 'down'} size={42}>
              <ThumbsDownIcon />
            </IconButton>
          ) : (
            <button onClick={() => seek(Math.max(0, currentTime - 15))} className="np-skip-button">-15</button>
          )}

          <IconButton label="Previous" onClick={previous} disabled={!hasPrev} size={50}>
            <PreviousIcon />
          </IconButton>

          <IconButton label={isPlaying ? 'Pause' : 'Play'} onClick={togglePlayPause} active size={64}>
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </IconButton>

          <IconButton label="Next" onClick={next} disabled={!hasNext} size={50}>
            <NextIcon />
          </IconButton>

          {music ? (
            <IconButton label="Thumb up" onClick={() => thumb('thumbs_up')} active={feedback === 'up'} size={42}>
              <ThumbsUpIcon />
            </IconButton>
          ) : (
            <button onClick={() => seek(Math.min(duration, currentTime + 30))} className="np-skip-button">+30</button>
          )}
        </div>

        <div className="np-actions">
          {music ? (
            <IconButton label="Add to playlist" onClick={() => setShowAdd(!showAdd)} active={showAdd} size={38} variant="ghost">
              <AddIcon />
            </IconButton>
          ) : (
            <div style={{ width: 38 }} />
          )}

          <div style={{ textAlign: 'center', flex: 1, minWidth: 0 }}>
            {nowPlaying.stationName && (
              <p style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {nowPlaying.stationName}
              </p>
            )}
          </div>

          <IconButton label="Queue" onClick={onOpenQueue} size={38} variant="ghost">
            <QueueIcon />
          </IconButton>
        </div>
      </div>
      <PlaylistPickerSheet open={music && showAdd} trackId={music ? nowPlaying.id : null} trackTitle={nowPlaying.title} onClose={() => setShowAdd(false)} />
    </div>
  )
}