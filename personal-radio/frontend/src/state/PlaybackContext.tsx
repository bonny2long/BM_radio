import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { getStationQueue, logPlaybackEvent, updateAudiobookProgress } from '../api'
import { trackToNowPlaying } from '../utils/mediaMappers'

export type QueueSource =
  | { kind: 'station'; stationType: string; seedValue?: string | null; stationName: string; canContinue: true; exhausted?: boolean }
  | { kind: 'artist-shuffle'; artist: string; canContinue: false }
  | { kind: 'album'; artist?: string; album?: string; canContinue: false }
  | { kind: 'smart-playlist'; key: string; canContinue: false }
  | { kind: 'playlist'; playlistId?: number; canContinue: false }
  | { kind: 'saved-queue'; playlistId?: number; canContinue: false }
  | { kind: 'manual'; canContinue: false }

export type NowPlaying = {
  mode: 'music' | 'audiobook'
  id: number
  title: string
  subtitle: string
  tertiary?: string | null
  streamUrl: string
  coverUrl?: string | null
  artist?: string | null
  album?: string | null
  stationName?: string | null
  durationSeconds?: number
  audiobookId?: number
  chapterId?: number
  startPositionSeconds?: number | null
}

type Playback = {
  nowPlaying: NowPlaying | null
  queue: NowPlaying[]
  queueIndex: number
  isPlaying: boolean
  currentTime: number
  duration: number
  error: string | null
  queueSource: QueueSource | null
  playItem: (item: NowPlaying, queue?: NowPlaying[]) => void
  playQueue: (items: NowPlaying[], index?: number, source?: QueueSource) => void
  togglePlayPause: () => void
  next: () => void
  previous: () => void
  seek: (seconds: number) => void
}

const Context = createContext<Playback | null>(null)
const REFILL_THRESHOLD = 5
const REFILL_LIMIT = 50

const normalizeSource = (source?: QueueSource): QueueSource => {
  if (!source) return { kind: 'manual', canContinue: false }
  if (source.kind === 'station') return { ...source, canContinue: true, exhausted: source.exhausted ?? false }
  return { ...source, canContinue: false } as QueueSource
}

export function PlaybackProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const queueRef = useRef<NowPlaying[]>([])
  const indexRef = useRef(-1)
  const itemRef = useRef<NowPlaying | null>(null)
  const sourceRef = useRef<QueueSource | null>(null)
  const lastSaved = useRef(0)
  const pendingStart = useRef(0)
  const refillInFlight = useRef(false)

  const [nowPlaying, setNowPlaying] = useState<NowPlaying | null>(null)
  const [queue, setQueue] = useState<NowPlaying[]>([])
  const [queueIndex, setQueueIndex] = useState(-1)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [queueSource, setQueueSource] = useState<QueueSource | null>(null)

  const event = useCallback((event_type: string, item = itemRef.current, extra?: Record<string, unknown>) => {
    if (!item) return
    void logPlaybackEvent({
      event_type,
      mode: item.mode,
      track_id: item.mode === 'music' ? item.id : undefined,
      audiobook_id: item.audiobookId,
      audiobook_chapter_id: item.chapterId,
      station_name: item.stationName ?? undefined,
      position_seconds: audioRef.current?.currentTime,
      completed_percent: audioRef.current?.duration
        ? (audioRef.current.currentTime / audioRef.current.duration) * 100
        : undefined,
      ...extra,
    }).catch(() => {})
  }, [])

  const saveProgress = useCallback(() => {
    const item = itemRef.current
    const el = audioRef.current
    if (!item || item.mode !== 'audiobook' || !item.audiobookId || !item.chapterId || !el) return
    void updateAudiobookProgress(item.audiobookId, {
      chapter_id: item.chapterId,
      position_seconds: el.currentTime,
      progress_percent: el.duration ? (el.currentTime / el.duration) * 100 : 0,
    }).catch(() => {})
  }, [])

  const load = useCallback((item: NowPlaying) => {
    const el = audioRef.current
    if (!el) return
    itemRef.current = item
    pendingStart.current = item.mode === 'audiobook' ? Math.max(0, item.startPositionSeconds ?? 0) : 0
    lastSaved.current = pendingStart.current
    setNowPlaying(item)
    setCurrentTime(0)
    setDuration(0)
    setError(null)
    el.src = item.streamUrl
    el.load()
    event('start', item)
    void el.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false))
  }, [event])

  const markStationExhausted = useCallback(() => {
    const src = sourceRef.current
    if (src?.kind !== 'station') return
    const exhausted: QueueSource = { ...src, canContinue: true, exhausted: true }
    sourceRef.current = exhausted
    setQueueSource(exhausted)
  }, [])

  const refillStationQueue = useCallback(async (startWhenReady = false): Promise<boolean> => {
    const src = sourceRef.current
    if (src?.kind !== 'station' || src.exhausted || refillInFlight.current) return false

    const excludeIds = queueRef.current.filter(item => item.mode === 'music').map(item => item.id).slice(-200)
    refillInFlight.current = true
    try {
      const result = await getStationQueue(src.stationType, src.seedValue ?? null, REFILL_LIMIT, excludeIds)
      const existing = new Set(queueRef.current.map(item => item.id))
      const newItems = result.queue
        .filter(track => !existing.has(track.id))
        .map(track => trackToNowPlaying(track, { stationName: src.stationName }))

      if (!newItems.length) {
        if (result.exhausted !== false) markStationExhausted()
        return false
      }

      const startIndex = queueRef.current.length
      const merged = [...queueRef.current, ...newItems]
      const updatedSource: QueueSource = { ...src, canContinue: true, exhausted: Boolean(result.exhausted) && !newItems.length }
      queueRef.current = merged
      sourceRef.current = updatedSource
      setQueue(merged)
      setQueueSource(updatedSource)

      if (startWhenReady) {
        indexRef.current = startIndex
        setQueueIndex(startIndex)
        load(merged[startIndex])
      }
      return true
    } catch {
      return false
    } finally {
      refillInFlight.current = false
    }
  }, [load, markStationExhausted])

  const maybePrefetchStation = useCallback((index: number) => {
    const src = sourceRef.current
    if (src?.kind === 'station' && !src.exhausted && queueRef.current.length - index - 1 <= REFILL_THRESHOLD) {
      void refillStationQueue(false)
    }
  }, [refillStationQueue])

  const continueOrEnd = useCallback(async (step: number, userInitiated = false) => {
    const next = indexRef.current + step
    if (next < 0) return

    if (next < queueRef.current.length) {
      if (step > 0 && userInitiated) event('skip')
      indexRef.current = next
      setQueueIndex(next)
      load(queueRef.current[next])
      if (step > 0) maybePrefetchStation(next)
      return
    }

    const src = sourceRef.current
    if (step > 0 && src?.kind === 'station' && !src.exhausted) {
      if (userInitiated) event('skip')
      const continued = await refillStationQueue(true)
      if (continued) return
    }

    setIsPlaying(false)
  }, [event, load, maybePrefetchStation, refillStationQueue])

  useEffect(() => {
    const el = new Audio()
    audioRef.current = el

    const time = () => setCurrentTime(el.currentTime)
    const meta = () => {
      setDuration(el.duration || 0)
      const start = pendingStart.current
      if (start > 0 && Number.isFinite(el.duration)) {
        el.currentTime = Math.min(start, Math.max(0, el.duration - 1))
        setCurrentTime(el.currentTime)
        pendingStart.current = 0
      }
    }
    const play = () => setIsPlaying(true)
    const pause = () => {
      setIsPlaying(false)
      event('pause')
      saveProgress()
    }
    const ended = () => {
      event('finish')
      saveProgress()
      void continueOrEnd(1, false)
    }
    const fail = () => {
      setIsPlaying(false)
      setError('Unable to play this file')
    }

    el.addEventListener('timeupdate', time)
    el.addEventListener('loadedmetadata', meta)
    el.addEventListener('play', play)
    el.addEventListener('pause', pause)
    el.addEventListener('ended', ended)
    el.addEventListener('error', fail)

    return () => {
      el.pause()
      el.removeEventListener('timeupdate', time)
      el.removeEventListener('loadedmetadata', meta)
      el.removeEventListener('play', play)
      el.removeEventListener('pause', pause)
      el.removeEventListener('ended', ended)
      el.removeEventListener('error', fail)
    }
  }, [continueOrEnd, event, saveProgress])

  useEffect(() => {
    if (!nowPlaying || nowPlaying.mode !== 'audiobook' || currentTime - lastSaved.current < 15) return
    lastSaved.current = currentTime
    saveProgress()
  }, [currentTime, nowPlaying, saveProgress])

  const playQueue = (items: NowPlaying[], index = 0, source?: QueueSource) => {
    if (!items.length) return
    const safeIndex = Math.max(0, Math.min(index, items.length - 1))
    const src = normalizeSource(source)
    refillInFlight.current = false
    sourceRef.current = src
    setQueueSource(src)
    queueRef.current = items
    indexRef.current = safeIndex
    setQueue(items)
    setQueueIndex(safeIndex)
    load(items[safeIndex])
    maybePrefetchStation(safeIndex)
  }

  const playItem = (item: NowPlaying, items?: NowPlaying[]) => {
    const list = items?.length ? items : [item]
    playQueue(list, Math.max(0, list.findIndex(x => x.id === item.id)))
  }

  const togglePlayPause = () => {
    const el = audioRef.current
    if (!el || !itemRef.current) return
    if (el.paused) void el.play()
    else el.pause()
  }

  return (
    <Context.Provider value={{
      nowPlaying,
      queue,
      queueIndex,
      isPlaying,
      currentTime,
      duration,
      error,
      queueSource,
      playItem,
      playQueue,
      togglePlayPause,
      next: () => { void continueOrEnd(1, true) },
      previous: () => { void continueOrEnd(-1, true) },
      seek: (seconds) => {
        if (audioRef.current) {
          audioRef.current.currentTime = seconds
          event('seek')
        }
      },
    }}>
      {children}
    </Context.Provider>
  )
}

export const usePlayback = () => {
  const context = useContext(Context)
  if (!context) throw new Error('PlaybackProvider missing')
  return context
}
