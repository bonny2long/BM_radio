import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/pages/LibraryIntegrityPage.tsx'), 'utf8')
const api = readFileSync(resolve(root, 'src/api.ts'), 'utf8')

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

assert(api.includes('export type ScanRunRecord='), 'ScanRunRecord type missing')
assert(api.includes('latest_scans?:Record<string,ScanRunRecord|null>'), 'latest_scans type missing')
assert(api.includes('getLibraryScanRuns'), 'scan-run history API client missing')
assert(page.includes('Available Tracks'), 'availability summary card missing')
assert(page.includes('Unavailable Tracks'), 'unavailable tracks summary missing')
assert(page.includes('Partial Audiobooks'), 'partial audiobook summary missing')
assert(page.includes('Latest Music Scan'), 'latest music scan card missing')
assert(page.includes('Latest Audiobook Scan'), 'latest audiobook scan card missing')
assert(page.includes('Scan History'), 'scan history section missing')
assert(page.includes('Read-only diagnostics'), 'read-only notice missing')
assert(page.includes('No indexed media yet'), 'empty state copy missing')
assert(page.includes('StatusPill'), 'scan status pill rendering missing')
assert(!page.includes('Rescan now'), 'mutation rescan control must not exist')
assert(!page.includes('Mark available'), 'mutation mark-available control must not exist')
assert(!page.includes('Delete row'), 'mutation delete-row control must not exist')
assert(!page.includes('Clear failed scan'), 'mutation clear-failed-scan control must not exist')

console.log('PASS: BM-PROD1.3D3 integrity UI contract')