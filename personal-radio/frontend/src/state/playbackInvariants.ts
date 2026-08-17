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
