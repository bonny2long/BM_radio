import { useEffect,useState } from 'react'
import Artwork from '../components/Artwork'
import { getStationQueue,getStations,type Station } from '../api'
import { usePlayback } from '../state/PlaybackContext'
import { trackToNowPlaying } from '../utils/mediaMappers'
export default function RadioPage(){const [stations,setStations]=useState<Station[]>([]),[busy,setBusy]=useState<string|null>(null);const {playQueue}=usePlayback();useEffect(()=>{void getStations().then(setStations)},[]);const play=async(s:Station)=>{setBusy(s.name);try{const seed=s.seed_value??((s.type==='genre'||s.type==='artist')?s.name.replace(/ Radio$/,''):null);playQueue((await getStationQueue(s.type,seed)).queue.map(t=>trackToNowPlaying(t,{stationName:s.name})))}finally{setBusy(null)}};return <div><div style={{marginBottom:28}}><h1>Stations</h1><p style={{color:'var(--text-muted)',fontSize:13}}>Auto-generated from your library</p></div><div style={{display:'grid',gap:10}}>{stations.map(s=><button className="card-premium" onClick={()=>void play(s)} disabled={!!busy} style={{padding:14,textAlign:'left',color:'var(--text-primary)'}} key={s.name}><div style={{display:'flex',gap:12,alignItems:'center'}}><Artwork label={s.name} size={46}/><div><strong>{s.name}</strong><div style={{color:'var(--text-muted)',fontSize:12,marginTop:3}}>{busy===s.name?'Loading queue...':s.track_count+' tracks - tap to play'}</div></div></div></button>)}</div></div>}



