import { useEffect, useMemo, useState } from 'react'
import Artwork from '../components/Artwork'
import IconButton from '../components/IconButton'
import LoadingSkeleton from '../components/LoadingSkeleton'
import PageError from '../components/PageError'
import { PlayIcon } from '../components/PlayerIcons'
import { getStationQueue, getStations, type Station } from '../api'
import { usePlayback, type QueueSource } from '../state/PlaybackContext'
import { trackToNowPlaying } from '../utils/mediaMappers'

// Station types shown in each section.
// favorites, deep_cuts, and recently_added are intentionally excluded from sections.
// They live in Library -> Playlists -> Smart Collections, while recently_added powers the hero card.
const SECTION_GROUPS: [string, string[]][] = [
  ['Genres', ['genre']],
  ['Artists', ['artist']],
  ['My Stations', ['song', 'custom', 'user']],
]

export default function RadioPage() {
  const [stations, setStations] = useState<Station[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [pageError, setPageError] = useState<string | null>(null)
  const { playQueue } = usePlayback()

  const loadStations = () => {
    setLoading(true)
    setPageError(null)
    getStations()
      .then(setStations)
      .catch(() => setPageError('Could not load stations. Check your NAS connection.'))
      .finally(() => setLoading(false))
  }

  useEffect(loadStations, [])

  const play = async (station: Station) => {
    setBusy(station.name)
    try {
      let seed: string | null = null

      if (station.type === 'song') {
        seed = station.seed_value ?? null
      } else if (station.type === 'genre' || station.type === 'artist') {
        seed = station.seed_value ?? station.name.replace(/ Radio$/, '')
      } else {
        seed = station.seed_value ?? null
      }

      const result = await getStationQueue(station.type, seed)
      const source: QueueSource = {
        kind: 'station',
        stationType: station.type,
        seedValue: seed,
        stationName: station.name,
      }
      playQueue(
        result.queue.map(track => trackToNowPlaying(track, { stationName: station.name })),
        0,
        source
      )
    } finally {
      setBusy(null)
    }
  }

  const featured = useMemo(
    () => stations.find(station => station.type === 'recently_added') ?? null,
    [stations]
  )

  if (loading) return <LoadingSkeleton rows={6} />
  if (pageError) return <PageError message={pageError} onRetry={loadStations} />

  return (
    <div style={{ width: '100%', maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: '1.6rem', fontWeight: 800, letterSpacing: '-0.03em' }}>
          Stations
        </h1>
      </div>

      {featured && (
        <button
          onClick={() => void play(featured)}
          disabled={!!busy}
          style={{
            width: '100%',
            padding: '18px 20px 18px 24px',
            borderRadius: 'var(--radius-card)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            textAlign: 'left',
            color: 'var(--text-primary)',
            marginBottom: 24,
            boxShadow: 'var(--shadow-card)',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <div style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: 4,
            background: 'var(--gradient-radio)',
            borderRadius: '4px 0 0 4px',
          }} />

          <svg
            aria-hidden="true"
            width="90"
            height="48"
            viewBox="0 0 90 48"
            style={{
              position: 'absolute',
              right: 68,
              top: '50%',
              transform: 'translateY(-50%)',
              opacity: 0.08,
              pointerEvents: 'none',
            }}
          >
            {[4, 10, 18, 6, 24, 14, 8, 20, 12, 16, 6, 22].map((height, index) => (
              <rect
                key={index}
                x={index * 8}
                y={(48 - height) / 2}
                width={4}
                height={height}
                rx={2}
                fill="var(--accent-primary)"
              />
            ))}
          </svg>

          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--accent-primary)',
              marginBottom: 6,
              opacity: 0.85,
            }}>
              Start BM Radio
            </p>
            <p style={{
              fontSize: 20,
              fontWeight: 800,
              letterSpacing: '-0.02em',
              color: 'var(--text-primary)',
              marginBottom: 4,
              lineHeight: 1.1,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              Recently Added Mix
            </p>
            <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {busy === featured.name
                ? 'Building queue...'
                : `${featured.track_count} ${featured.track_count === 1 ? 'track' : 'tracks'} ready`}
            </p>
          </div>

          <div style={{
            width: 44,
            height: 44,
            borderRadius: '50%',
            flexShrink: 0,
            background: 'var(--accent-primary)',
            display: 'grid',
            placeItems: 'center',
            boxShadow: '0 4px 16px var(--accent-primary-glow)',
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="white">
              <polygon points="5,3 19,12 5,21" />
            </svg>
          </div>
        </button>
      )}

      {SECTION_GROUPS.map(([title, types]) => {
        const list = stations.filter(station => title === 'My Stations' ? station.source === 'user' : types.includes(station.type) && station.source !== 'user' && station !== featured)

        if (title === 'My Stations' && list.length === 0) {
          return (
            <section key={title} style={{ marginBottom: 26 }}>
              <p className="section-label">{title}</p>
              <div className="card-premium" style={{ padding: '20px 18px', textAlign: 'center' }}>
                <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
                  No stations yet
                </p>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  Start a song radio from any track in your library.<br />
                  Long-press a song, then choose <strong style={{ color: 'var(--accent-primary)' }}>Start Song Radio</strong>
                </p>
              </div>
            </section>
          )
        }

        if (!list.length) return null

        return (
          <section key={title} style={{ marginBottom: 26 }}>
            <p className="section-label">{title}</p>
            <div style={{ display: 'grid', gap: 9 }}>
              {list.map(station => (
                <div
                  className="card-premium"
                  style={{
                    padding: 12,
                    display: 'grid',
                    gridTemplateColumns: '48px minmax(0,1fr) 38px',
                    alignItems: 'center',
                    gap: 12,
                    width: '100%',
                    maxWidth: '100%',
                    minWidth: 0,
                    overflow: 'hidden',
                  }}
                  key={station.id ?? station.name}
                >
                  <Artwork label={station.name} kind="station" size={48} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <strong style={{
                      display: 'block',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}>
                      {station.name}
                    </strong>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {station.track_count} {station.track_count === 1 ? 'track' : 'tracks'}
                    </span>
                  </div>
                  <IconButton
                    label={`Play ${station.name}`}
                    onClick={() => void play(station)}
                    active={busy === station.name}
                    disabled={!!busy && busy !== station.name}
                    size={38}
                  >
                    <PlayIcon />
                  </IconButton>
                </div>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}