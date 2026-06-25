export function cleanTrackTitle(raw:string){
  if(!raw)return'Untitled Track'
  let title=raw.trim()
  title=title
    .replace(/^\d+\s*[-_.]\s*\d+\s*[-_.]?\s*/i,'')
    .replace(/^\d+\s*[-_.]\s*/i,'')
    .replace(/^\d+\s*\.\s*[-–—]?\s*/i,'')
    .replace(/^[-–—]\s*/i,'')
    .replace(/^\d+\s*\.\s*/i,'')
    .replace(/\s+/g,' ')
    .trim()
  return title||raw.trim()||'Untitled Track'
}
export function cleanChapterTitle(raw:string,index:number){if(!raw)return`Chapter ${index+1}`;const title=raw.trim();const match=title.match(/^(?:\d+\s*)?track\s*(\d+)$/i);if(match)return`Chapter ${Number(match[1])||index+1}`;return title.replace(/^\d+[-_.\s]+/i,'').replace(/^track\s*\d+[-_.\s]*/i,'').trim()||`Chapter ${index+1}`}
export function cleanSubtitle(raw:string){
  if(!raw)return''
  const parts=raw
    .replace(/\s+[·•]\s+/g,' · ')
    .split(/\s+(?:-|–|—|·|•)\s+/)
    .map(p=>p.trim())
    .filter(Boolean)
  const dedup=[...new Map(parts.map(p=>[p.toLowerCase(),p])).values()]
  return dedup.join(' · ')
}
export function cleanFallbackLabel(raw:string){return cleanTrackTitle(raw)||'BM'}
