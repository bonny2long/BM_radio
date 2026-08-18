import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { getStationQueue, logPlaybackEvent, updateAudiobookProgress } from '../api'
import { trackToNowPlaying } from '../utils/mediaMappers'
import { appendUniqueQueueItems, clampVolume, moveQueueEntry, nextQueueIndex, playbackIdentity, playEventForIdentity, previousQueueIndex, removeQueueEntry, shouldAdvanceForEnded, shouldPrefetchStation, stationExcludeIds, STATION_REFILL_LIMIT } from './playbackInvariants'

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
  volume: number
  playbackRate: number
  error: string | null
  queueSource: QueueSource | null
  playItem: (item: NowPlaying, queue?: NowPlaying[]) => void
  playQueue: (items: NowPlaying[], index?: number, source?: QueueSource) => void
  togglePlayPause: () => void
  next: () => void
  previous: () => void
  seek: (seconds: number) => void
  setVolume: (volume: number) => void
  setPlaybackRate: (rate: number) => void
  removeQueueItem: (index: number) => void
  clearQueue: () => void
  moveQueueItem: (from: number, to: number) => void
}

const Context = createContext<Playback | null>(null)
const LATENCY_ACCEPTANCE_QUERY = 'bm_latency_acceptance'
const LATENCY_EVENTS = ['loadstart', 'durationchange', 'loadedmetadata', 'loadeddata', 'canplay', 'playing', 'waiting', 'stalled', 'seeking', 'seeked', 'error'] as const

type LatencyEvent = {
  event: string
  elapsedMs: number
  currentTime: number
  readyState: number
  networkState: number
}

type LatencyLoad = {
  loadId: number
  mode: NowPlaying['mode']
  itemId: number
  title: string
  startedAt: number
  events: LatencyEvent[]
}

type LatencyAcceptanceWindow = Window & {
  __BM_RADIO_LATENCY__?: { loads: LatencyLoad[] }
  __BM_RADIO_LATENCY_CONTROL__?: {
    playQueue: Playback['playQueue']
    next: Playback['next']
    previous: Playback['previous']
    seek: Playback['seek']
    setPlaybackRate: Playback['setPlaybackRate']
    togglePlayPause: Playback['togglePlayPause']
    snapshot: () => Pick<Playback, 'nowPlaying' | 'queueIndex' | 'isPlaying' | 'currentTime' | 'duration' | 'playbackRate'>
  }
}

const latencyAcceptanceEnabled = () => new URLSearchParams(window.location.search).get(LATENCY_ACCEPTANCE_QUERY) === '1'

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
  const sourceTransition = useRef(false)
  const startedIdentity = useRef<string | null>(null)
  const endedIdentity = useRef<string | null>(null)
  const latencyLoadId = useRef(0)
  const activeLatencyLoad = useRef<LatencyLoad | null>(null)
  const volumeRef = useRef(clampVolume(Number(window.localStorage.getItem('bm-radio-volume') ?? .8)))
  const storedAudiobookRate = Number(window.localStorage.getItem('bm-radio-audiobook-rate') ?? 1)
  const audiobookRateRef = useRef([0.75, 1, 1.25, 1.5, 1.75, 2].includes(storedAudiobookRate) ? storedAudiobookRate : 1)

  const [nowPlaying, setNowPlaying] = useState<NowPlaying | null>(null)
  const [queue, setQueue] = useState<NowPlaying[]>([])
  const [queueIndex, setQueueIndex] = useState(-1)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolumeState] = useState(volumeRef.current)
  const [playbackRate, setPlaybackRateState] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [queueSource, setQueueSource] = useState<QueueSource | null>(null)

  const recordLatencyEvent = useCallback((eventName: string) => {
    if (!latencyAcceptanceEnabled()) return
    const el = audioRef.current
    const active = activeLatencyLoad.current
    if (!el || !active) return
    active.events.push({
      event: eventName,
      elapsedMs: Number((performance.now() - active.startedAt).toFixed(3)),
      currentTime: Number(el.currentTime.toFixed(3)),
      readyState: el.readyState,
      networkState: el.networkState,
    })
  }, [])

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
      checkpointed_at: new Date().toISOString(),
    }).catch(() => {})
  }, [])

  const load = useCallback((item: NowPlaying) => {
    const el = audioRef.current
    if (!el) return
    sourceTransition.current = true
    el.pause()
    if (latencyAcceptanceEnabled()) {
      const acceptanceWindow = window as LatencyAcceptanceWindow
      const store = acceptanceWindow.__BM_RADIO_LATENCY__ ?? { loads: [] }
      acceptanceWindow.__BM_RADIO_LATENCY__ = store
      const active = {
        loadId: ++latencyLoadId.current,
        mode: item.mode,
        itemId: item.id,
        title: item.title,
        startedAt: performance.now(),
        events: [],
      } satisfies LatencyLoad
      store.loads.push(active)
      activeLatencyLoad.current = active
    }
    itemRef.current = item
    startedIdentity.current = null
    endedIdentity.current = null
    pendingStart.current = item.mode === 'audiobook' ? Math.max(0, item.startPositionSeconds ?? 0) : 0
    lastSaved.current = pendingStart.current
    setNowPlaying(item)
    setCurrentTime(0)
    setDuration(0)
    setError(null)
    el.src = item.streamUrl
    el.volume = volumeRef.current
    el.playbackRate = item.mode === 'audiobook' ? audiobookRateRef.current : 1
    setPlaybackRateState(el.playbackRate)
    el.load()
    sourceTransition.current = false
    void el.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false))
  }, [])

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

    const excludeIds = stationExcludeIds(queueRef.current)
    refillInFlight.current = true
    try {
      const result = await getStationQueue(src.stationType, src.seedValue ?? null, STATION_REFILL_LIMIT, excludeIds)
      const mapped = result.queue.map(track => trackToNowPlaying(track, { stationName: src.stationName }))
      const { queue: merged, appended: newItems } = appendUniqueQueueItems(queueRef.current, mapped)

      if (!newItems.length) {
        if (result.exhausted !== false) markStationExhausted()
        return false
      }

      const startIndex = queueRef.current.length
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
    if (src?.kind === 'station' && shouldPrefetchStation(queueRef.current.length, index, src.exhausted)) {
      void refillStationQueue(false)
    }
  }, [refillStationQueue])

  const continueOrEnd = useCallback(async (step: number, userInitiated = false) => {
    const next = step > 0
      ? nextQueueIndex(indexRef.current, queueRef.current.length)
      : previousQueueIndex(indexRef.current, queueRef.current.length)

    if (step < 0 && next < 0) return

    if (next >= 0) {
      if (step > 0 && userInitiated) event('skip')
      saveProgress()
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
  }, [event, load, maybePrefetchStation, refillStationQueue, saveProgress])

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
    const play = () => {
      setIsPlaying(true)
      const item = itemRef.current
      if (!item) return
      const identity = playbackIdentity(item.mode, item.id, item.chapterId)
      const historyEvent = playEventForIdentity(identity, startedIdentity.current)
      if (historyEvent === 'start') {
        startedIdentity.current = identity
        event('start', item)
      } else {
        event('resume', item)
      }
    }
    const pause = () => {
      setIsPlaying(false)
      if (sourceTransition.current || el.ended) return
      event('pause')
      saveProgress()
    }
    const ended = () => {
      const item = itemRef.current
      if (!item) return
      const identity = playbackIdentity(item.mode, item.id, item.chapterId)
      if (!shouldAdvanceForEnded(identity, endedIdentity.current)) return
      endedIdentity.current = identity
      event('finish')
      saveProgress()
      void continueOrEnd(1, false)
    }
    const fail = () => {
      setIsPlaying(false)
      setError('Unable to play this file')
    }
    const checkpointSeek = () => {
      if (itemRef.current?.mode !== 'audiobook') return
      lastSaved.current = el.currentTime
      saveProgress()
    }
    const latencyHandlers = Object.fromEntries(
      LATENCY_EVENTS.map(eventName => [eventName, () => recordLatencyEvent(eventName)]),
    ) as Record<(typeof LATENCY_EVENTS)[number], () => void>

    el.addEventListener('timeupdate', time)
    el.addEventListener('loadedmetadata', meta)
    el.addEventListener('play', play)
    el.addEventListener('pause', pause)
    el.addEventListener('ended', ended)
    el.addEventListener('seeked', checkpointSeek)
    el.addEventListener('error', fail)
    for (const eventName of LATENCY_EVENTS) el.addEventListener(eventName, latencyHandlers[eventName])

    return () => {
      el.pause()
      el.removeEventListener('timeupdate', time)
      el.removeEventListener('loadedmetadata', meta)
      el.removeEventListener('play', play)
      el.removeEventListener('pause', pause)
      el.removeEventListener('ended', ended)
      el.removeEventListener('seeked', checkpointSeek)
      el.removeEventListener('error', fail)
      for (const eventName of LATENCY_EVENTS) el.removeEventListener(eventName, latencyHandlers[eventName])
    }
  }, [continueOrEnd, event, recordLatencyEvent, saveProgress])

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

  const updateVolume = (value: number) => {
    const safe = clampVolume(value)
    volumeRef.current = safe
    if (audioRef.current) audioRef.current.volume = safe
    setVolumeState(safe)
    window.localStorage.setItem('bm-radio-volume', String(safe))
  }

  const updatePlaybackRate = (value: number) => {
    const allowed = [0.75, 1, 1.25, 1.5, 1.75, 2]
    const rate = allowed.includes(value) ? value : 1
    audiobookRateRef.current = rate
    window.localStorage.setItem('bm-radio-audiobook-rate', String(rate))
    if (itemRef.current?.mode === 'audiobook' && audioRef.current) {
      audioRef.current.playbackRate = rate
      setPlaybackRateState(rate)
    }
  }

  const removeQueueItem = (index: number) => {
    if (index <= indexRef.current || index < 0 || index >= queueRef.current.length) return
    const updated = removeQueueEntry(queueRef.current, index)
    queueRef.current = updated
    setQueue(updated)
  }

  const clearQueue = () => {
    const current = itemRef.current
    const updated = current ? [current] : []
    queueRef.current = updated
    indexRef.current = current ? 0 : -1
    sourceRef.current = { kind: 'manual', canContinue: false }
    setQueue(updated)
    setQueueIndex(indexRef.current)
    setQueueSource(sourceRef.current)
  }

  const moveQueueItem = (from: number, to: number) => {
    if (from <= indexRef.current || to <= indexRef.current) return
    const updated = moveQueueEntry(queueRef.current, from, to)
    queueRef.current = updated
    setQueue(updated)
  }

  useEffect(() => {
    if (!latencyAcceptanceEnabled()) return
    const acceptanceWindow = window as LatencyAcceptanceWindow
    const control = {
      playQueue,
      next: () => { void continueOrEnd(1, true) },
      previous: () => { void continueOrEnd(-1, true) },
      seek: (seconds: number) => {
        if (audioRef.current) audioRef.current.currentTime = seconds
      },
      setPlaybackRate: updatePlaybackRate,
      togglePlayPause: () => {
        const el = audioRef.current
        if (!el || !itemRef.current) return
        if (el.paused) void el.play()
        else el.pause()
      },
      snapshot: () => ({ nowPlaying, queueIndex, isPlaying, currentTime, duration, playbackRate }),
    } satisfies NonNullable<LatencyAcceptanceWindow['__BM_RADIO_LATENCY_CONTROL__']>
    acceptanceWindow.__BM_RADIO_LATENCY_CONTROL__ = control
    return () => {
      if (acceptanceWindow.__BM_RADIO_LATENCY_CONTROL__ === control) delete acceptanceWindow.__BM_RADIO_LATENCY_CONTROL__
    }
  })

  return (
    <Context.Provider value={{
      nowPlaying,
      queue,
      queueIndex,
      isPlaying,
      currentTime,
      duration,
      volume,
      playbackRate,
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
      setVolume: updateVolume,
      setPlaybackRate: updatePlaybackRate,
      removeQueueItem,
      clearQueue,
      moveQueueItem,
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
