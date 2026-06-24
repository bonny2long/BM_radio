import { mediaUrl,type Track } from '../api'
import type { NowPlaying } from '../state/PlaybackContext'
export const trackToNowPlaying=(track:Track,context?:{stationName?:string}):NowPlaying=>({mode:'music',id:track.id,title:track.title,subtitle:[track.artist,track.album].filter(Boolean).join(' - '),streamUrl:mediaUrl(track.stream_url)!,coverUrl:mediaUrl(track.cover_url),artist:track.artist,album:track.album,durationSeconds:track.duration_seconds,stationName:context?.stationName})
export const cleanChapterTitle=(title:string,index:number)=>{const clean=title.replace(/^\d+[-_.\s]+/,'').replace(/track\s*\d+$/i,'').trim();return clean||`Chapter ${index+1}`}

