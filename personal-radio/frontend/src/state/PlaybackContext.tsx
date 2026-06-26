import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { getStationQueue, logPlaybackEvent, updateAudiobookProgress } from '../api'
import { trackToNowPlaying } from '../utils/mediaMappers'

export type QueueSource =
  | { kind: 'station'; stationType: string; seedValue?: string | null; stationName: string }
  | { kind: 'album' }
  | { kind: 'playlist' }
  | { kind: 'manual' }

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

export function PlaybackProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const queueRef = useRef<NowPlaying[]>([])
  const indexRef = useRef(-1)
  const itemRef = useRef<NowPlaying | null>(null)
  const sourceRef = useRef<QueueSource | null>(null)
  const lastSaved = useRef(0)
  const pendingStart = useRef(0)

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

  const advance = useCallback((step: number) => {
    const next = indexRef.current + step
    if (next < 0 || next >= queueRef.current.length) return
    if (step > 0) event('skip')
    indexRef.current = next
    setQueueIndex(next)
    load(queueRef.current[next])
  }, [event, load])

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

      const nextIndex = indexRef.current + 1
      if (nextIndex < queueRef.current.length) {
        advance(1)
        return
      }

      const src = sourceRef.current
      if (src?.kind !== 'station') return

      const excludeIds = queueRef.current.map(item => item.id)
      void getStationQueue(src.stationType, src.seedValue ?? null, 50, excludeIds)
        .then(result => {
          if (!result.queue.length) return
          const newItems = result.queue.map(track => trackToNowPlaying(track, { stationName: src.stationName }))
          sourceRef.current = src
          setQueueSource(src)
          queueRef.current = newItems
          indexRef.current = 0
          setQueue(newItems)
          setQueueIndex(0)
          load(newItems[0])
        })
        .catch(() => {})
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
  }, [advance, event, load, saveProgress])

  useEffect(() => {
    if (!nowPlaying || nowPlaying.mode !== 'audiobook' || currentTime - lastSaved.current < 15) return
    lastSaved.current = currentTime
    saveProgress()
  }, [currentTime, nowPlaying, saveProgress])

  const playQueue = (items: NowPlaying[], index = 0, source?: QueueSource) => {
    if (!items.length) return
    const safeIndex = Math.max(0, Math.min(index, items.length - 1))
    const src = source ?? ({ kind: 'manual' } as QueueSource)
    sourceRef.current = src
    setQueueSource(src)
    queueRef.current = items
    indexRef.current = safeIndex
    setQueue(items)
    setQueueIndex(safeIndex)
    load(items[safeIndex])
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
      next: () => advance(1),
      previous: () => advance(-1),
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