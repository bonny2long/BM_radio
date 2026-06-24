const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8094/api'
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  return response.json() as Promise<T>
}
export type LibrarySummary = { tracks: number; artists: number; albums: number }
export type AudiobookSummary = { available: number; not_started: number; in_progress: number; finished: number; favorites: number; total_listening_seconds: number }
export type Audiobook = { id: number; title: string; author: string; status: string; favorite: boolean }
export type Station = { name: string; type: string; track_count: number }
export type AlbumSummary = { title: string; artist: string; track_count: number }
export const getPathStatus = () => request('/library/paths')
export const getLibrarySummary = () => request<LibrarySummary>('/library/summary')
export const scanMusic = () => request('/library/scan/music', { method: 'POST' })
export const getAudiobookSummary = () => request<AudiobookSummary>('/audiobooks/summary')
export const scanAudiobooks = () => request('/audiobooks/scan', { method: 'POST' })
export const getAudiobooks = () => request<Audiobook[]>('/audiobooks/')
export const getAlbums = () => request<AlbumSummary[]>('/library/albums')
export const getStations = () => request<Station[]>('/stations/')
