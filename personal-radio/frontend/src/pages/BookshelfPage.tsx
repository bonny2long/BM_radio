import { useEffect, useMemo, useState } from 'react'
import {
  favoriteAudiobook,
  getAudiobook,
  getAudiobookSummary,
  getAudiobooks,
  mediaUrl,
  resetAudiobookProgress,
  type Audiobook,
  type AudiobookDetail,
  type AudiobookSummary,
  type Chapter,
} from '../api'
import Artwork from '../components/Artwork'
import LoadingSkeleton from '../components/LoadingSkeleton'
import PageError from '../components/PageError'
import { usePlayback, type NowPlaying } from '../state/PlaybackContext'
import { cleanChapterTitle } from '../utils/mediaMappers'

const empty: AudiobookSummary = { available: 0, not_started: 0, in_progress: 0, finished: 0, favorites: 0, total_listening_seconds: 0 }
type CollectionPart = { index: number; title: string; displayTitle: string; chapter?: Chapter }

const numberFrom = (value?: string | number) => {
  if (typeof value === 'number') return value
  const match = String(value ?? '').match(/\d+/)
  return match ? Number(match[0]) : undefined
}

const titleTokens = (title: string) => title.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter(Boolean).filter(token => !['the', 'a', 'an', 'of', 'and', 'book', 'part', 'volume', 'vol'].includes(token))

function chapterNumber(chapter: Chapter) {
  const match = chapter.title.match(/(?:\(\s*book\s*(\d+)\s*\)|\bbook\s*(\d+)\b|\bpart\s*(\d+)\b|\bvol(?:ume)?\.?\s*(\d+)\b|#\s*(\d+)|(?:^|\D)(\d{1,2})(?:\D|$))/i)
  return match ? Number(match.slice(1).find(Boolean)) : undefined
}

function resolveAudiobookCollectionParts(detail: AudiobookDetail): CollectionPart[] {
  const books = (detail.contained_books ?? []).filter(book => book.title)
  if (!books.length) {
    return detail.chapters.map((chapter, index) => ({ index: index + 1, title: cleanChapterTitle(chapter.title, index), displayTitle: cleanChapterTitle(chapter.title, index), chapter }))
  }
  const used = new Set<number>()
  return books.map((book, itemIndex) => {
    const index = numberFrom(book.series_index) ?? itemIndex + 1
    const tokens = titleTokens(book.title)
    let chapter = detail.chapters.find(candidate => !used.has(candidate.id) && chapterNumber(candidate) === index)
    if (!chapter && tokens.length) chapter = detail.chapters.find(candidate => !used.has(candidate.id) && tokens.every(token => candidate.title.toLowerCase().includes(token)))
    if (!chapter) chapter = detail.chapters.find(candidate => !used.has(candidate.id)) ?? detail.chapters[itemIndex]
    if (chapter) used.add(chapter.id)
    const title = book.title.replace(/\s*\((?:book|part|vol(?:ume)?)?\s*\d+\)\s*$/i, '').trim()
    return { index, title, displayTitle: `Book ${index} - ${title}`, chapter }
  }).sort((left, right) => left.index - right.index)
}

function item(detail: AudiobookDetail, chapter: Chapter, startPositionSeconds?: number | null): NowPlaying {
  const part = resolveAudiobookCollectionParts(detail).find(candidate => candidate.chapter?.id === chapter.id)
  return {
    mode: 'audiobook',
    id: chapter.id,
    title: detail.title,
    subtitle: part?.displayTitle ?? cleanChapterTitle(chapter.title, Math.max(0, chapter.sort_order - 1)),
    tertiary: detail.author,
    streamUrl: mediaUrl(chapter.stream_url)!,
    durationSeconds: chapter.duration_seconds,
    audiobookId: detail.id,
    chapterId: chapter.id,
    startPositionSeconds,
    coverUrl: mediaUrl(detail.cover_url ?? `/api/media/audiobooks/${detail.id}/cover`) ?? undefined,
  }
}

const buttonStyle = { minHeight: 44, padding: '0 18px', borderRadius: 'var(--radius-pill)', fontWeight: 800, fontSize: 14 } as const

export default function BookshelfPage({ initialBookId }: { initialBookId?: number | null }) {
  const [, setSummary] = useState(empty)
  const [books, setBooks] = useState<Audiobook[]>([])
  const [detail, setDetail] = useState<AudiobookDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [pageError, setPageError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'in_progress' | 'finished' | 'saved'>('all')
  const { playQueue } = usePlayback()

  const refresh = () => {
    setLoading(true)
    setPageError(null)
    Promise.all([getAudiobookSummary(), getAudiobooks()])
      .then(([summary, items]) => { setSummary(summary); setBooks(items) })
      .catch(() => setPageError('Could not load your bookshelf. Check your NAS connection.'))
      .finally(() => setLoading(false))
  }

  useEffect(refresh, [])
  useEffect(() => { if (initialBookId) void getAudiobook(initialBookId).then(setDetail) }, [initialBookId])
  const collectionRows = useMemo(() => detail ? resolveAudiobookCollectionParts(detail) : [], [detail])

  if (loading && !detail) return <LoadingSkeleton rows={3} />
  if (pageError && !detail) return <PageError message={pageError} onRetry={refresh} />

  if (detail) {
    const latestChapterId = detail.latest_progress?.chapter_id
    const start = Math.max(0, detail.chapters.findIndex(chapter => chapter.id === latestChapterId))
    const percent = Math.round(detail.latest_progress?.overall_progress_percent ?? detail.latest_progress?.progress_percent ?? 0)
    const currentPart = collectionRows.find(part => part.chapter?.id === latestChapterId)
    const completed = detail.status === 'finished' || detail.latest_progress?.completion_state === 'finished'
    const play = (index = start, resume = true) => {
      const resumeChapterId = resume ? latestChapterId : undefined
      const startSeconds = resume ? detail.latest_progress?.position_seconds : undefined
      playQueue(detail.chapters.map(chapter => item(detail, chapter, chapter.id === resumeChapterId ? startSeconds : undefined)), index)
    }
    const playChapter = (chapter?: Chapter) => {
      if (!chapter) return
      const index = Math.max(0, detail.chapters.findIndex(candidate => candidate.id === chapter.id))
      playQueue(detail.chapters.map(candidate => item(detail, candidate)), index)
    }
    const toggle = async () => { await favoriteAudiobook(detail.id); setDetail(await getAudiobook(detail.id)); refresh() }
    const resetProgress = async () => { await resetAudiobookProgress(detail.id); setDetail(await getAudiobook(detail.id)); refresh() }
    const durationHours = detail.duration_seconds ? `${Math.round(detail.duration_seconds / 360) / 10} hours` : null

    return <div>
      <button onClick={() => setDetail(null)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 0', marginBottom: 16, minHeight: 44, color: 'var(--text-secondary)', fontSize: 14, fontWeight: 500 }}>&larr; Bookshelf</button>
      <h1 style={{ fontSize: '1.8rem', fontWeight: 800, marginBottom: 4 }}>{detail.title}</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: 4 }}>{detail.author}</p>
      {(detail.narrator || durationHours) && <p style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 12 }}>{[detail.narrator ? `Narrated by ${detail.narrator}` : null, durationHours].filter(Boolean).join(' · ')}</p>}
      <div style={{ padding: '20px 20px 18px', borderRadius: 18, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', boxShadow: 'var(--shadow-card)', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 4, borderRadius: 999, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}><div style={{ width: `${Math.min(100, Math.max(0, percent))}%`, height: '100%', borderRadius: 999, background: 'var(--gradient-radio)', transition: 'width 0.4s ease' }} /></div>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', flexShrink: 0, minWidth: 32, textAlign: 'right' }}>{percent}%</span>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{completed ? 'Finished — replay from the beginning' : percent > 0 ? currentPart?.title ?? (latestChapterId ? 'Current chapter' : 'Chapter 1') : 'Place saved automatically as you listen'}</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <button onClick={() => completed ? play(0, false) : play()} style={{ ...buttonStyle, background: 'var(--gradient-radio)', color: '#fff', boxShadow: '0 6px 20px rgba(139,92,246,0.25)' }}>{completed ? 'Replay' : percent > 0 ? 'Continue' : 'Start'}</button>
          <button onClick={() => void toggle()} style={{ ...buttonStyle, background: 'transparent', border: '1px solid', borderColor: detail.favorite ? 'var(--accent-primary)' : 'var(--border-subtle)', color: detail.favorite ? 'var(--accent-primary)' : 'var(--text-secondary)' }}>{detail.favorite ? 'Saved' : 'Save'}</button>
        </div>
        {percent > 0 && <button onClick={() => void resetProgress()} style={{ minHeight: 36, padding: '0 12px', marginTop: 10, borderRadius: 'var(--radius-pill)', background: 'transparent', border: '1px solid var(--border-subtle)', color: 'var(--text-muted)', fontWeight: 700, fontSize: 12, width: '100%' }}>Reset progress</button>}
      </div>
      <p className="section-label">{detail.contained_books?.length ? 'Books in this collection' : 'Chapters'}</p>
      {collectionRows.map(part => <button onClick={() => playChapter(part.chapter)} className="card-premium" style={{ padding: 14, textAlign: 'left', width: '100%', marginBottom: 8, color: 'var(--text-primary)' }} key={part.chapter?.id ?? `${part.index}-${part.title}`}><strong>{detail.contained_books?.length ? part.displayTitle : `${part.index}. ${part.title}`}</strong><div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>{detail.contained_books?.length ? 'Play book' : 'Play chapter'}</div></button>)}
    </div>
  }

  const filteredBooks = books.filter(book => filter === 'all' || (filter === 'saved' && book.favorite) || book.status === filter)
  const sectionLabel = filter === 'all' ? 'All Books' : filter === 'in_progress' ? 'Started Books' : filter === 'saved' ? 'Saved Books' : 'Finished Books'
  const counts = { all: books.length, in_progress: books.filter(book => book.status === 'in_progress').length, finished: books.filter(book => book.status === 'finished').length, saved: books.filter(book => book.favorite).length }

  return <div>
    <div style={{ marginBottom: 20 }}><h1 style={{ fontSize: '1.6rem', fontWeight: 800, letterSpacing: '-0.03em', color: 'var(--text-primary)' }}>Bookshelf</h1></div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
      {([['all', 'All', 'var(--text-primary)'], ['in_progress', 'Started', 'var(--accent-primary)'], ['finished', 'Finished', '#34d399'], ['saved', 'Saved', 'var(--accent-secondary)']] as const).map(([key, label, color]) => {
        const active = filter === key
        return <button key={label} onClick={() => setFilter(active ? 'all' : key)} style={{ background: 'var(--bg-card)', border: '1px solid', borderColor: active ? 'var(--accent-primary)' : 'var(--border-subtle)', borderRadius: 'var(--radius-m)', padding: '14px 16px', boxShadow: active ? '0 0 24px var(--accent-primary-glow)' : 'var(--shadow-card)', textAlign: 'left' }}><div style={{ fontSize: 28, fontWeight: 800, color, letterSpacing: '-0.04em', lineHeight: 1, marginBottom: 4 }}>{counts[key]}</div><div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>{label}</div></button>
      })}
    </div>
    {filter !== 'all' && <button onClick={() => setFilter('all')} style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>Show all books</button>}
    <p className="section-label">{sectionLabel}</p>
    <div style={{ position: 'relative' }}>
      {filteredBooks.map(book => <button onClick={() => void getAudiobook(book.id).then(setDetail)} className="card-premium" style={{ padding: '14px 16px', marginBottom: 10, width: '100%', textAlign: 'left', color: 'var(--text-primary)', display: 'flex', gap: 14, alignItems: 'center', borderColor: book.favorite ? 'var(--accent-primary)' : 'var(--border-subtle)' }} key={book.id}><Artwork src={mediaUrl(book.cover_url)} label={book.title} size={52} kind="book" /><div style={{ flex: 1, minWidth: 0 }}><div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}><div style={{ fontWeight: 600, fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{book.title}</div>{book.favorite && <span aria-label="Favorite" title="Favorite" style={{ color: 'var(--accent-primary)', fontSize: 13, flexShrink: 0 }}>Saved</span>}</div><div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{book.author}</div><div style={{ marginTop: 5 }}><span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', fontSize: 10, fontWeight: 600, color: book.status === 'finished' ? '#34d399' : book.status === 'in_progress' ? 'var(--accent-primary)' : 'var(--text-muted)' }}>{book.status.replace(/_/g, ' ')}</span></div></div></button>)}
      {!filteredBooks.length && <div className="card-premium" style={{ padding: 22, textAlign: 'center', color: 'var(--text-muted)', marginBottom: 10 }}>No books in this filter.</div>}
      {Array.from({ length: 6 }).map((_, index) => <div key={`shelf-${index}`} style={{ height: 56, marginBottom: 8, position: 'relative', pointerEvents: 'none' }}><div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, background: 'rgba(255,255,255,0.13)', borderRadius: 1 }} /><div style={{ position: 'absolute', bottom: 0, left: 0, width: 3, height: 10, background: 'rgba(255,255,255,0.10)', borderRadius: 2 }} /><div style={{ position: 'absolute', bottom: 0, right: 0, width: 3, height: 10, background: 'rgba(255,255,255,0.10)', borderRadius: 2 }} /><div style={{ position: 'absolute', bottom: -3, left: 0, right: 0, height: 6, background: 'linear-gradient(to bottom, rgba(0,0,0,0.28), transparent)' }} /></div>)}
    </div>
  </div>
}
