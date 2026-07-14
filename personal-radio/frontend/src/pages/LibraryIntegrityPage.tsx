import { useEffect, useMemo, useState } from 'react'
import { getLibraryIntegrity, getLibraryScanRuns, type LibraryIntegrityIssue, type LibraryIntegrityReport, type ScanRunRecord } from '../api'
import LoadingSkeleton from '../components/LoadingSkeleton'
import PageError from '../components/PageError'

type Filter = 'all' | 'error' | 'warning' | 'notice' | 'info'

const severityColor: Record<string, string> = { error: '#ff6b6b', warning: '#ffb84d', notice: 'var(--accent-primary)', info: 'var(--text-muted)' }
const filters: Filter[] = ['all', 'error', 'warning', 'notice', 'info']

function label(value: string) { return value.replace(/_/g, ' ').replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) }
function numberValue(value?: number | null) { return typeof value === 'number' ? value : 0 }
function timeLabel(value?: string | null) { return value ? new Date(value).toLocaleString() : 'Not recorded' }
function durationLabel(seconds?: number | null) { if (seconds === null || seconds === undefined) return 'Open'; if (seconds < 60) return `${Math.round(seconds)}s`; return `${Math.round(seconds / 60)}m` }
function statusLabel(run?: ScanRunRecord | null) { if (!run) return 'No scan'; return run.stale ? 'Stale' : label(run.status) }
function statusColor(run?: ScanRunRecord | null) { if (!run) return 'var(--text-muted)'; if (run.stale) return '#ffb84d'; if (run.status === 'succeeded') return '#4ade80'; if (run.status === 'failed') return '#ff6b6b'; return 'var(--accent-primary)' }
function shortenLibraryPath(path: string): string { const normalized = path.replace(/\\/g, '/'); const prefixes = ['Music/Library/FLAC/', 'Music/Library/', 'Audiobooks/Library/', 'Audiobooks/', 'Library/FLAC/', 'Library/']; for (const prefix of prefixes) { const idx = normalized.indexOf(prefix); if (idx !== -1) return normalized.slice(idx + prefix.length) } const parts = normalized.split('/'); return parts.slice(Math.max(0, parts.length - 3)).join('/') }

function SummaryCard({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return <div className="card-premium" style={{ padding: 14, minHeight: 62 }}><strong style={{ display: 'block', fontSize: 22, lineHeight: 1, color: tone ?? 'var(--text-primary)' }}>{value}</strong><span style={{ display: 'block', marginTop: 6, fontSize: 10, letterSpacing: 0, textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 800 }}>{label}</span></div>
}

function StatusPill({ run }: { run?: ScanRunRecord | null }) {
  return <span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, fontWeight: 800, color: statusColor(run), background: 'rgba(255,255,255,0.06)' }}>{statusLabel(run)}</span>
}

function ScanCard({ title, run }: { title: string; run?: ScanRunRecord | null }) {
  return <div className="card-premium" style={{ padding: 14 }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}><strong>{title}</strong><StatusPill run={run} /></div><p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>{run ? `${timeLabel(run.started_at)} · ${run.items_discovered} found · ${run.items_unavailable} unavailable · ${run.error_count} errors` : 'No scan history yet'}</p></div>
}

function itemText(item: Record<string, unknown>) {
  const title = String(item.title ?? item.album ?? item.name ?? item.chapter_title ?? 'Item')
  const subtitle = [item.artist, item.author, item.year, item.reason].filter(Boolean).join(' · ')
  const path = item.path ? `\n${shortenLibraryPath(String(item.path))}` : ''
  return `${title}${subtitle ? ` — ${subtitle}` : ''}${path}`
}

function IssueCard({ issue }: { issue: LibraryIntegrityIssue }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => { try { await navigator.clipboard.writeText([`${issue.title} (${issue.severity})`, issue.message, ...issue.items.map(itemText)].join('\n\n')); setCopied(true); window.setTimeout(() => setCopied(false), 1200) } catch { setCopied(false) } }
  return <article className="card-premium" style={{ padding: 14 }}>
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}><div style={{ flex: 1, minWidth: 0 }}><div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}><span style={{ width: 8, height: 8, borderRadius: '50%', background: severityColor[issue.severity] ?? 'var(--text-muted)' }} /><strong style={{ fontSize: 15 }}>{issue.title}</strong></div><p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.45 }}>{issue.message}</p></div><button onClick={copy} style={{ color: 'var(--accent-primary)', fontSize: 12, fontWeight: 800, flexShrink: 0 }}>{copied ? 'Copied' : 'Copy'}</button></div>
    <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}><span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, background: 'rgba(255,255,255,0.06)', color: severityColor[issue.severity] ?? 'var(--text-muted)', fontWeight: 800 }}>{label(issue.severity)}</span><span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>{issue.count} {issue.count === 1 ? 'item' : 'items'}</span><span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>{label(issue.category ?? issue.type)}</span>{issue.sample_truncated && <span style={{ borderRadius: 'var(--radius-pill)', padding: '4px 8px', fontSize: 11, background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>Sample</span>}</div>
    {!!issue.items.length && <div style={{ display: 'grid', gap: 7, marginTop: 12 }}>{issue.items.map((item, index) => <div key={index} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 9 }}><strong style={{ display: 'block', fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(item.title ?? item.album ?? item.chapter_title ?? item.name ?? 'Item')}</strong><span style={{ display: 'block', marginTop: 2, fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{[item.artist, item.author, item.year, item.reason, item.library_availability].filter(Boolean).join(' · ')}</span>{item.path !== undefined && <span style={{ display: 'block', marginTop: 2, fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{shortenLibraryPath(String(item.path))}</span>}</div>)}</div>}
  </article>
}

function ScanHistory({ runs }: { runs: ScanRunRecord[] }) {
  if (!runs.length) return <div className="card-premium" style={{ padding: 16, color: 'var(--text-muted)' }}>No scan history yet.</div>
  return <div className="card-premium" style={{ padding: 0, overflow: 'hidden' }}>{runs.map(run => <div key={run.id} style={{ display: 'grid', gridTemplateColumns: 'minmax(110px,1.3fr) minmax(72px,.8fr) minmax(76px,.8fr) minmax(150px,1.5fr)', gap: 10, alignItems: 'center', padding: '12px 14px', borderTop: '1px solid var(--border-subtle)' }}><span style={{ minWidth: 0, fontSize: 12, color: 'var(--text-secondary)' }}>{timeLabel(run.started_at)}</span><span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{label(run.media_kind)}</span><StatusPill run={run} /><span style={{ minWidth: 0, fontSize: 11, color: 'var(--text-muted)' }}>{run.items_discovered} found · {run.items_added} added · {run.items_updated} updated · {run.items_unavailable} unavailable · {run.error_count} errors · {durationLabel(run.duration_seconds)}{run.error_summary ? ` · ${run.error_summary}` : ''}</span></div>)}</div>
}

export default function LibraryIntegrityPage({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<LibraryIntegrityReport | null>(null)
  const [scanRuns, setScanRuns] = useState<ScanRunRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const load = () => { setLoading(true); setError(null); Promise.all([getLibraryIntegrity(), getLibraryScanRuns(25)]).then(([integrity, history]) => { setReport(integrity); setScanRuns(history.items) }).catch(() => setError('Could not load library integrity report.')).finally(() => setLoading(false)) }
  useEffect(load, [])
  const issues = useMemo(() => { if (!report) return []; if (filter === 'all') return report.issues; return report.issues.filter(issue => issue.severity === filter) }, [report, filter])
  if (loading) return <LoadingSkeleton rows={7} preserveSpace />
  if (error || !report) return <PageError message={error ?? 'Could not load library integrity report.'} onRetry={load} />
  const summary = report.summary
  const noIndexedMedia = numberValue(summary.total_tracks) === 0 && numberValue(summary.total_audiobooks) === 0
  return <div style={{ width: '100%', minWidth: 0 }}>
    <button onClick={onBack} style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 18 }}>Back to Library</button>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 18 }}><div><h1 style={{ fontSize: '1.6rem', fontWeight: 800, letterSpacing: 0, marginBottom: 4 }}>Library Integrity</h1><p style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.4 }}>Read-only diagnostics for active availability, retained history, scan runs, duplicate candidates, variants, and metadata quality. No repair, delete, rescan, or mark-available controls are exposed here.</p>{report.generated_at && <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>Generated {timeLabel(report.generated_at)} · Policy: {report.availability_policy ?? 'available'}</p>}</div><button onClick={load} style={{ padding: '9px 12px', borderRadius: 'var(--radius-pill)', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', color: 'var(--accent-primary)', fontWeight: 800, fontSize: 12 }}>Refresh</button></div>
    {noIndexedMedia && <div className="card-premium" style={{ padding: 16, marginBottom: 14, color: 'var(--text-muted)' }}>No indexed media yet.</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 9, marginBottom: 18 }}><SummaryCard label="Available Tracks" value={numberValue(summary.available_tracks)} /><SummaryCard label="Unavailable Tracks" value={numberValue(summary.unavailable_tracks)} tone={numberValue(summary.unavailable_tracks) ? '#ffb84d' : undefined} /><SummaryCard label="Available Audiobooks" value={numberValue(summary.available_audiobooks)} /><SummaryCard label="Unavailable Audiobooks" value={numberValue(summary.unavailable_audiobooks)} tone={numberValue(summary.unavailable_audiobooks) ? '#ffb84d' : undefined} /><SummaryCard label="Unavailable Chapters" value={numberValue(summary.unavailable_audiobook_chapters)} tone={numberValue(summary.unavailable_audiobook_chapters) ? '#ff6b6b' : undefined} /><SummaryCard label="Partial Audiobooks" value={numberValue(summary.partial_audiobooks)} tone={numberValue(summary.partial_audiobooks) ? '#ff6b6b' : undefined} /><SummaryCard label="Failed Scans" value={numberValue(summary.failed_scan_runs)} tone={numberValue(summary.failed_scan_runs) ? '#ffb84d' : undefined} /><SummaryCard label="Stale Running" value={numberValue(summary.stale_running_scan_runs)} tone={numberValue(summary.stale_running_scan_runs) ? '#ffb84d' : undefined} /></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 9, marginBottom: 18 }}><ScanCard title="Latest Music Scan" run={report.latest_scans?.music ?? null} /><ScanCard title="Latest Audiobook Scan" run={report.latest_scans?.audiobook ?? null} /></div>
    <h2 style={{ fontSize: 14, margin: '0 0 10px', letterSpacing: 0 }}>Scan History</h2><div style={{ marginBottom: 18 }}><ScanHistory runs={scanRuns} /></div>
    <div className="library-tabs" style={{ marginBottom: 14 }}>{filters.map(value => <button key={value} onClick={() => setFilter(value)} style={{ padding: '8px 11px', borderRadius: 'var(--radius-pill)', background: filter === value ? 'var(--accent-primary)' : 'var(--bg-surface)', color: filter === value ? '#fff' : 'var(--text-secondary)', border: '1px solid', borderColor: filter === value ? 'transparent' : 'var(--border-subtle)', whiteSpace: 'nowrap', fontSize: 13, fontWeight: filter === value ? 700 : 500 }}>{label(value)}</button>)}</div>
    <div style={{ display: 'grid', gap: 10 }}>{issues.map(issue => <IssueCard key={issue.id ?? `${issue.type}-${issue.severity}`} issue={issue} />)}{!issues.length && <div className="card-premium" style={{ padding: 22, textAlign: 'center', color: 'var(--text-muted)' }}>No issues match this filter.</div>}</div>
  </div>
}