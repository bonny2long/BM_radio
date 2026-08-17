export const clampVolume = (value: number) => Math.max(0, Math.min(1, value))

export const playbackIdentity = (mode: 'music' | 'audiobook', id: number, chapterId?: number) =>
  `${mode}:${id}:${chapterId ?? ''}`

export const playEventForIdentity = (identity: string, startedIdentity: string | null) =>
  identity === startedIdentity ? 'resume' : 'start'

export const shouldAdvanceForEnded = (identity: string, endedIdentity: string | null) =>
  identity !== endedIdentity

export const nextQueueIndex = (current: number, length: number) => {
  const candidate = current + 1
  return candidate >= 0 && candidate < length ? candidate : -1
}

export const previousQueueIndex = (current: number, length: number) => {
  const candidate = current - 1
  return candidate >= 0 && candidate < length ? candidate : -1
}

export const moveQueueEntry = <T,>(items: T[], from: number, to: number) => {
  if (from < 0 || from >= items.length || to < 0 || to >= items.length || from === to) return [...items]
  const updated = [...items]
  const [entry] = updated.splice(from, 1)
  updated.splice(to, 0, entry)
  return updated
}

export const removeQueueEntry = <T,>(items: T[], index: number) =>
  index < 0 || index >= items.length ? [...items] : items.filter((_, itemIndex) => itemIndex !== index)

export const STATION_REFILL_THRESHOLD = 5
export const STATION_REFILL_LIMIT = 50
export const STATION_EXCLUDE_LIMIT = 200

export const shouldPrefetchStation = (queueLength: number, queueIndex: number, exhausted = false) =>
  !exhausted && queueLength - queueIndex - 1 <= STATION_REFILL_THRESHOLD

export const stationExcludeIds = <T extends { mode: 'music' | 'audiobook'; id: number }>(items: T[]) =>
  items.filter(item => item.mode === 'music').map(item => item.id).slice(-STATION_EXCLUDE_LIMIT)

export const appendUniqueQueueItems = <T extends { id: number }>(current: T[], incoming: T[]) => {
  const seen = new Set(current.map(item => item.id))
  const appended: T[] = []
  for (const item of incoming) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    appended.push(item)
  }
  return { queue: [...current, ...appended], appended }
}
