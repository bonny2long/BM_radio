import { useEffect, useMemo, useState } from 'react'
import { getLibraryIntegrity, type LibraryIntegrityIssue, type LibraryIntegrityReport } from '../api'
import LoadingSkeleton from '../components/LoadingSkeleton'
import PageError from '../components/PageError'

type Filter = 'all' | 'warning' | 'notice' | 'info' | 'error'

const severityColor: Record<string, string> = {
  error: '#ff6b6b',
  warning: '#ffb84d',
  notice: 'var(--accent-primary)',
  info: 'var(--text-muted)',
}

function label(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function itemText(item: Record<string, unknown>) {
  const title = String(item.title ?? item.album ?? item.name ?? 'Item')
  const subtitle = [item.artist, item.author, item.year].filter(Boolean).join(' · ')
  const path = item.path ? `\n${String(item.path)}` : ''
  const reason = item.reason ? `\nReason: ${String(item.reason)}` : ''
  return `${title}${subtitle ? ` — ${subtitle}` : ''}${reason}${path}`
}

function SummaryCard({ label, value }: { label: string; value: number | string }) {
  return <div className="card-premium" style={{ padding: 14, minHeight: 58 }}><strong style={{ display: 'block', fontSize: 22, lineHeight: 1, color: 'var(--text-primary)' }}>{value}</strong><span style={{ display: 'block', marginTop: 6, fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 800 }}>{label}</span></div>
}

function IssueCard({ issue }: { issue: LibraryIntegrityIssue }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    const text = [`${issue.title} (${issue.severity})`, issue.message, ...issue.items.map(itemText)].join('\n\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }
  return <article className="card-premium" style={{ padding: 14 }}>
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: severityColor[issue.severity] ?? 'var(--text-muted)', boxShadow: `0 0 14px ${severityColor[issue.severity] ?? 'transparent'}` }} />
          <strong style={{ fontSize: 15 }}>{issue.title}</strong>
        </div>
        <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.45 }}>{issue.message}</p>
      </div>
      <button onClick={copy} style={{ color: 'var(--accent-primary)', fontSize: 12, fontWeight: 800, flexShrink: 0 }}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
    <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
      <span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, background: 'rgba(255,255,255,0.06)', color: severityColor[issue.severity] ?? 'var(--text-muted)', fontWeight: 800 }}>{issue.severity}</span>
      <span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>{issue.count} {issue.count === 1 ? 'item' : 'items'}</span>
      <span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>{label(issue.type)}</span>
    </div>
    {!!issue.items.length && <div style={{ display: 'grid', gap: 7, marginTop: 12 }}>
      {issue.items.map((item, index) => <div key={index} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 9 }}>
        <strong style={{ display: 'block', fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(item.title ?? item.album ?? item.name ?? 'Item')}</strong>
        <span style={{ display: 'block', marginTop: 2, fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{[item.artist, item.author, item.year, item.reason].filter(Boolean).join(' · ')}</span>
        {item.path !== undefined && <span style={{ display: 'block', marginTop: 2, fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(item.path)}</span>}
      </div>)}
    </div>}
  </article>
}

export default function LibraryIntegrityPage({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<LibraryIntegrityReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const load = () => {
    setLoading(true)
    setError(null)
    getLibraryIntegrity()
      .then(setReport)
      .catch(() => setError('Could not load library integrity report.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const issues = useMemo(() => {
    if (!report) return []
    if (filter === 'all') return report.issues
    return report.issues.filter(issue => issue.severity === filter)
  }, [report, filter])

  if (loading) return <LoadingSkeleton rows={7} preserveSpace />
  if (error || !report) return <PageError message={error ?? 'Could not load library integrity report.'} onRetry={load} />

  const summary = report.summary
  const filters: Filter[] = ['all', 'warning', 'notice', 'info', 'error']

  return <div style={{ width: '100%', minWidth: 0 }}>
    <button onClick={onBack} style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 18 }}>? Back to Library</button>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 18 }}>
      <div>
        <h1 style={{ fontSize: '1.6rem', fontWeight: 800, letterSpacing: '-0.03em', marginBottom: 4 }}>Library Integrity</h1>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.4 }}>Read-only BM Radio app-index diagnostics. No files are changed.</p>
      </div>
      <button onClick={load} style={{ padding: '9px 12px', borderRadius: 'var(--radius-pill)', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', color: 'var(--accent-primary)', fontWeight: 800, fontSize: 12 }}>Refresh</button>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 9, marginBottom: 18 }}>
      <SummaryCard label="Tracks" value={summary.total_tracks} />
      <SummaryCard label="Albums" value={summary.total_albums} />
      <SummaryCard label="Books" value={summary.total_audiobooks} />
      <SummaryCard label="Dupes" value={summary.duplicate_music_track_release_rows + summary.duplicate_audiobook_editions} />
      <SummaryCard label="Variants" value={(summary.suspected_duplicate_recordings ?? 0) + (summary.audiobook_variants ?? 0)} />
      <SummaryCard label="Covers" value={summary.missing_covers} />
    </div>

    <div className="library-tabs" style={{ marginBottom: 14 }}>
      {filters.map(value => <button key={value} onClick={() => setFilter(value)} style={{ padding: '8px 11px', borderRadius: 'var(--radius-pill)', background: filter === value ? 'var(--accent-primary)' : 'var(--bg-surface)', color: filter === value ? '#fff' : 'var(--text-secondary)', border: '1px solid', borderColor: filter === value ? 'transparent' : 'var(--border-subtle)', whiteSpace: 'nowrap', fontSize: 13, fontWeight: filter === value ? 700 : 500 }}>{label(value)}</button>)}
    </div>

    <div style={{ display: 'grid', gap: 10 }}>
      {issues.map(issue => <IssueCard key={`${issue.type}-${issue.severity}`} issue={issue} />)}
      {!issues.length && <div className="card-premium" style={{ padding: 22, textAlign: 'center', color: 'var(--text-muted)' }}>No issues match this filter.</div>}
    </div>
  </div>
}

