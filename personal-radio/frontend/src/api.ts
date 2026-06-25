const API_BASE_URL=import.meta.env.VITE_API_BASE_URL??'http://127.0.0.1:8094/api'
const API_ORIGIN=API_BASE_URL.replace(/\/api\/?$/,'')
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(`${API_BASE_URL}${path}`,init);if(!response.ok)throw new Error(`Request failed (${response.status})`);return response.json() as Promise<T>}
export type LibrarySummary={tracks:number;artists:number;albums:number}
export type AudiobookSummary={available:number;not_started:number;in_progress:number;finished:number;favorites:number;total_listening_seconds:number}
export type Track={id:number;title:string;artist:string;album:string;year?:number|null;genre?:string|null;duration_seconds?:number;stream_url:string;cover_url?:string|null}
export type Audiobook={id:number;title:string;author:string;narrator?:string|null;status:string;favorite:boolean;duration_seconds?:number;cover_url?:string|null}
export type ContainedBook={series_index?:string|number;title:string;display_title?:string;chapter_id?:number}
export type Chapter={id:number;title:string;sort_order:number;duration_seconds?:number;stream_url:string}
export type AudiobookDetail=Audiobook&{contained_books?:ContainedBook[];latest_progress?:{chapter_id?:number;position_seconds:number;progress_percent:number;chapter_progress_percent?:number;overall_progress_percent?:number;updated_at?:string}|null;chapters:Chapter[]}
export type Station={name:string;type:string;seed_value?:string|null;track_count:number}
export type AlbumSummary={title:string;artist:string;year?:number|null;track_count:number;cover_url?:string|null}
export type ArtistSummary={name:string;track_count:number;album_count?:number}
export type ArtistDetail={name:string;track_count:number;album_count:number;albums:AlbumSummary[];tracks:Track[]}
export type SearchResults={artists:ArtistSummary[];albums:AlbumSummary[];tracks:Track[];stations:Station[];audiobooks:Audiobook[]}
export type TrackPage={items:Track[];total:number;limit:number;offset:number;has_more:boolean}
export type RecentPlaybackItem={mode:'music'|'audiobook';track_id?:number;audiobook_id?:number;chapter_id?:number;position_seconds?:number;title:string;subtitle:string;cover_url?:string|null;stream_url?:string|null;last_event_at:string}
export const mediaUrl=(path?:string|null):string|null=>{if(!path)return null;if(/^https?:\/\//.test(path))return path;return path.startsWith('/')?`${API_ORIGIN}${path}`:`${API_ORIGIN}/${path}`}
export const getLibrarySummary=()=>request<LibrarySummary>('/library/summary')
export const scanMusic=()=>request('/library/scan/music',{method:'POST'})
export const getAudiobookSummary=()=>request<AudiobookSummary>('/audiobooks/summary')
export const scanAudiobooks=()=>request('/audiobooks/scan',{method:'POST'})
export const getAudiobooks=()=>request<Audiobook[]>('/audiobooks/')
export const getAudiobook=(id:number)=>request<AudiobookDetail>(`/audiobooks/${id}`)
export const getAlbums=()=>request<AlbumSummary[]>('/library/albums')
export const getAlbumTracks=(artist:string,album:string)=>request<Track[]>(`/library/album-tracks?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`)
export const getStations=()=>request<Station[]>('/stations/')
export const getStationQueue=(type:string,seedValue?:string|null)=>request<{queue:Track[]}>('/queue/station',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,seed_value:seedValue,limit:50,shuffle:true})})
export const updateAudiobookProgress=(id:number,p:{chapter_id:number;position_seconds:number;progress_percent:number})=>request(`/audiobooks/${id}/progress`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})
export const favoriteAudiobook=(id:number)=>request<{favorite:boolean}>(`/audiobooks/${id}/favorite`,{method:'POST'})
export const getArtists=()=>request<ArtistSummary[]>('/library/artists')
export const getArtistDetail=(artist:string)=>request<ArtistDetail>(`/library/artists/${encodeURIComponent(artist)}/detail`)
export const getTracks=(limit=100,offset=0)=>request<Track[]>(`/library/tracks?limit=${limit}&offset=${offset}`)
export const searchTracks=(q:string)=>request<Track[]>(`/library/search?q=${encodeURIComponent(q)}`)
export const searchAll=(q:string)=>request<SearchResults>(`/search?q=${encodeURIComponent(q)}`)
export const getArtistQueue=(artist:string,limit=50,shuffle=false)=>request<{queue:Track[]}>('/queue/artist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({artist,limit,shuffle})})
export const getAlbumQueue=(artist:string,album:string,limit=500,shuffle=false)=>request<{queue:Track[]}>('/queue/album',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({artist,album,limit,shuffle})})
export const finishAudiobook=(id:number)=>request<{book_status:string}>(`/audiobooks/${id}/finished`,{method:'POST'})
export const resetAudiobook=(id:number)=>request<{book_status:string}>(`/audiobooks/${id}/not-started`,{method:'POST'})
export const setTrackFeedback=(trackId:number,value:'thumbs_up'|'thumbs_down'|'neutral')=>request<{value:string}>(`/playback/tracks/${trackId}/feedback`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value})})
export const getTrackFeedback=(trackId:number)=>request<{value:string}>(`/playback/tracks/${trackId}/feedback`)
export const setTrackFavorite=(trackId:number,favorite?:boolean)=>request<{favorite:boolean}>(`/playback/tracks/${trackId}/favorite`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({favorite})})
export const getTrackFavorite=(trackId:number)=>request<{favorite:boolean}>(`/playback/tracks/${trackId}/favorite`)
export const getRecentPlayback=(limit=5)=>request<{items:RecentPlaybackItem[]}>(`/playback/recent?limit=${limit}`)
export const logPlaybackEvent=(event:{event_type:string;track_id?:number;audiobook_id?:number;audiobook_chapter_id?:number;position_seconds?:number;completed_percent?:number;mode?:string;station_name?:string})=>request('/playback/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event)})
export const getTracksPage=(limit=100,offset=0)=>request<TrackPage>(`/library/tracks-page?limit=${limit}&offset=${offset}`)
export const getArtistTracks=(artist:string,limit=50,offset=0)=>request<TrackPage>(`/library/artists/${encodeURIComponent(artist)}/tracks?limit=${limit}&offset=${offset}`)
