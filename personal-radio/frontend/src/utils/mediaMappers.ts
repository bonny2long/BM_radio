import { mediaUrl,type Track } from '../api'
import type { NowPlaying } from '../state/PlaybackContext'
import { cleanTrackTitle,cleanSubtitle,cleanChapterTitle as cleanChapterTitleDisplay } from './displayText'
export const trackToNowPlaying=(track:Track,context?:{stationName?:string}):NowPlaying=>({mode:'music',id:track.id,title:cleanTrackTitle(track.title),subtitle:cleanSubtitle([track.artist,track.album].filter(Boolean).join(' - ')),streamUrl:mediaUrl(track.stream_url)!,coverUrl:mediaUrl(track.cover_url),artist:track.artist,album:track.album,durationSeconds:track.duration_seconds,stationName:context?.stationName})
export const cleanChapterTitle=cleanChapterTitleDisplay
