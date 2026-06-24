import { useEffect, useState } from 'react'
import Artwork from '../components/Artwork'
import { getAlbumTracks,getAlbums,getLibrarySummary,mediaUrl,type AlbumSummary,type LibrarySummary } from '../api'
import { usePlayback } from '../state/PlaybackContext'
import { trackToNowPlaying } from '../utils/mediaMappers'
const empty:LibrarySummary={tracks:0,artists:0,albums:0};
export default function LibraryPage(){const [summary,setSummary]=useState(empty),[albums,setAlbums]=useState<AlbumSummary[]>([]),[busy,setBusy]=useState<string|null>(null);const {playQueue}=usePlayback();useEffect(()=>{void Promise.all([getLibrarySummary(),getAlbums()]).then(([s,a])=>{setSummary(s);setAlbums(a)})},[]);const play=async(a:AlbumSummary)=>{setBusy(a.title);try{playQueue((await getAlbumTracks(a.artist,a.title)).map(t=>trackToNowPlaying(t)))}finally{setBusy(null)}};return <div><div style={{marginBottom:28}}><h1>Library</h1><p style={{fontSize:13,color:'var(--text-muted)'}}>{summary.tracks} tracks - {summary.artists} artists - {summary.albums} albums</p></div><p className="section-label">Albums</p><div style={{display:'grid',gap:10}}>{albums.map(a=>{const cover=mediaUrl('/api/media/albums/cover?artist='+encodeURIComponent(a.artist)+'&album='+encodeURIComponent(a.title));return <div className="card-premium" style={{padding:14,display:'flex',alignItems:'center',gap:12}} key={a.artist+a.title}><Artwork src={cover} label={a.title} size={52}/><div style={{flex:1,minWidth:0}}><strong style={{display:'block',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{a.title}</strong><span style={{color:'var(--text-muted)',fontSize:12}}>{a.artist} - {a.track_count} tracks</span></div><button onClick={()=>void play(a)} disabled={!!busy} style={{padding:'9px 13px',borderRadius:18,background:'var(--accent-primary)',color:'#fff'}}>{busy===a.title?'Loading':'Play'}</button></div>})}</div></div>}



