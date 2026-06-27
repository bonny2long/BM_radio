const API_BASE_URL=import.meta.env.VITE_API_BASE_URL??'http://127.0.0.1:8094/api'
const API_ORIGIN=API_BASE_URL.replace(/\/api\/?$/,'')
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(`${API_BASE_URL}${path}`,init);if(!response.ok)throw new Error(`Request failed (${response.status})`);return response.json() as Promise<T>}

type CacheEntry={expires:number;data?:unknown;promise?:Promise<unknown>}
const cache=new Map<string,CacheEntry>()
export function invalidateCache(prefix?:string){for(const key of [...cache.keys()]){if(!prefix||key===prefix||key.startsWith(`${prefix}:`))cache.delete(key)}}
function cachedRequest<T>(key:string,path:string,ttlMs=30000):Promise<T>{const now=Date.now();const hit=cache.get(key);if(hit?.data!==undefined&&hit.expires>now)return Promise.resolve(hit.data as T);if(hit?.promise)return hit.promise as Promise<T>;const promise=request<T>(path).then(data=>{cache.set(key,{data,expires:Date.now()+ttlMs});return data}).catch(error=>{cache.delete(key);throw error});cache.set(key,{promise,expires:now+ttlMs});return promise}
export function peekCache<T>(key:string):T|null{const hit=cache.get(key);if(hit?.data!==undefined&&hit.expires>Date.now())return hit.data as T;return null}
export function hasFreshCache(key:string):boolean{return peekCache(key)!==null}
function invalidateLibraryCaches(){invalidateCache('library-summary');invalidateCache('albums-page');invalidateCache('recent-albums');invalidateCache('artists-page')}
function invalidateStationCaches(){invalidateCache('stations')}
export type LibrarySummary={tracks:number;artists:number;albums:number}
export type AudiobookSummary={available:number;not_started:number;in_progress:number;finished:number;favorites:number;total_listening_seconds:number}
export type Track={id:number;title:string;artist:string;album:string;year?:number|null;genre?:string|null;duration_seconds?:number;stream_url:string;cover_url?:string|null}
export type Audiobook={id:number;title:string;author:string;narrator?:string|null;status:string;favorite:boolean;duration_seconds?:number;cover_url?:string|null}
export type ContainedBook={series_index?:string|number;title:string;display_title?:string;chapter_id?:number}
export type Chapter={id:number;title:string;sort_order:number;duration_seconds?:number;stream_url:string}
export type AudiobookDetail=Audiobook&{contained_books?:ContainedBook[];latest_progress?:{chapter_id?:number;position_seconds:number;progress_percent:number;chapter_progress_percent?:number;overall_progress_percent?:number;updated_at?:string}|null;chapters:Chapter[]}
export type Station={id?:number;name:string;type:string;seed_value?:string|null;track_count:number;source?:'system'|'user';favorite?:boolean}
export type AlbumSummary={title:string;artist:string;year?:number|null;track_count:number;cover_url?:string|null}
export type ArtistSummary={name:string;track_count:number;album_count?:number}
export type ArtistDetail={name:string;track_count:number;album_count:number;albums:AlbumSummary[];tracks:Track[]}
export type SearchResults={artists:ArtistSummary[];albums:AlbumSummary[];tracks:Track[];stations:Station[];audiobooks:Audiobook[]}
export type TrackPage={items:Track[];total:number;limit:number;offset:number;has_more:boolean}
export type AlbumPage={items:AlbumSummary[];limit:number;offset:number}
export type ArtistPage={items:ArtistSummary[];limit:number;offset:number}
export type RecentPlaybackItem={mode:'music'|'audiobook';track_id?:number;audiobook_id?:number;chapter_id?:number;position_seconds?:number;title:string;subtitle:string;cover_url?:string|null;stream_url?:string|null;last_event_at:string}
export type PlaylistSummary={id:number;name:string;description?:string|null;kind:string;track_count:number}
export type SmartPlaylistSummary={id:string;name:string;description?:string|null;kind:string;track_count:number}
export type PlaylistDetail=PlaylistSummary&{tracks:Track[]}
export const mediaUrl=(path?:string|null):string|null=>{if(!path)return null;if(/^https?:\/\//.test(path))return path;return path.startsWith('/')?`${API_ORIGIN}${path}`:`${API_ORIGIN}/${path}`}
export const getLibrarySummary=()=>cachedRequest<LibrarySummary>('library-summary','/library/summary',30000)
export const scanMusic=()=>request('/library/scan/music',{method:'POST'}).then(r=>{invalidateLibraryCaches();invalidateStationCaches();return r})
export const getAudiobookSummary=()=>cachedRequest<AudiobookSummary>('audiobooks-summary','/audiobooks/summary',30000)
export const scanAudiobooks=()=>request('/audiobooks/scan',{method:'POST'}).then(r=>{invalidateCache('audiobooks-summary');invalidateCache('recent-or-progress-audiobooks');return r})
export const getAudiobooks=()=>request<Audiobook[]>('/audiobooks/')
export const getRecentOrProgressAudiobooks=(limit=3)=>cachedRequest<Audiobook[]>(`recent-or-progress-audiobooks:${limit}`,`/audiobooks/recent-or-progress?limit=${limit}`,30000)
export const getAudiobook=(id:number)=>request<AudiobookDetail>(`/audiobooks/${id}`)
export const getAlbums=()=>request<AlbumSummary[]>('/library/albums')
export const getAlbumsPage=(limit=50,offset=0)=>cachedRequest<AlbumPage>(`albums-page:${limit}:${offset}`,`/library/albums-page?limit=${limit}&offset=${offset}`,30000)
export const getRecentAlbums=(limit=8)=>cachedRequest<AlbumSummary[]>(`recent-albums:${limit}`,`/library/recent-albums?limit=${limit}`,30000)
export const getAlbumTracks=(artist:string,album:string)=>request<Track[]>(`/library/album-tracks?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`)
export const getStations=()=>cachedRequest<Station[]>('stations','/stations/',30000)
export const createStation=(name:string,type:string,seedValue?:string|null,seedTrackId?:number|null)=>request<Station>('/stations/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,type,seed_value:seedValue??null,seed_track_id:seedTrackId??null})}).then(r=>{invalidateStationCaches();return r})
export const deleteStation=(id:number)=>request<{deleted:boolean}>('/stations/'+id,{method:'DELETE'}).then(r=>{invalidateStationCaches();return r})
export const favoriteStation=(id:number)=>request<{favorite:boolean}>(`/stations/${id}/favorite`,{method:'POST'}).then(r=>{invalidateStationCaches();return r})
const stationQueueRequests=new Map<string,Promise<{queue:Track[]}>>()
export const getStationQueue=(type:string,seedValue?:string|null,limit=50,excludeTrackIds:number[]=[])=>{const cappedExcludeIds=excludeTrackIds.slice(-100);const key=JSON.stringify({type,seedValue:seedValue??null,limit,excludeTrackIds:cappedExcludeIds});const existing=stationQueueRequests.get(key);if(existing)return existing;const promise=request<{queue:Track[]}>('/queue/station',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,seed_value:seedValue,limit,shuffle:true,exclude_track_ids:cappedExcludeIds})}).finally(()=>stationQueueRequests.delete(key));stationQueueRequests.set(key,promise);return promise}
export const updateAudiobookProgress=(id:number,p:{chapter_id:number;position_seconds:number;progress_percent:number})=>request(`/audiobooks/${id}/progress`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})
export const favoriteAudiobook=(id:number)=>request<{favorite:boolean}>(`/audiobooks/${id}/favorite`,{method:'POST'})
export const getArtists=()=>request<ArtistSummary[]>('/library/artists')
export const getArtistsPage=(limit=50,offset=0)=>cachedRequest<ArtistPage>(`artists-page:${limit}:${offset}`,`/library/artists-page?limit=${limit}&offset=${offset}`,30000)
export const getArtistDetail=(artist:string)=>request<ArtistDetail>(`/library/artists/${encodeURIComponent(artist)}/detail`)
export const getTracks=(limit=100,offset=0)=>request<Track[]>(`/library/tracks?limit=${limit}&offset=${offset}`)
export const searchTracks=(q:string)=>request<Track[]>(`/library/search?q=${encodeURIComponent(q)}`)
export const searchAll=(q:string)=>request<SearchResults>(`/search?q=${encodeURIComponent(q)}`)
export const getArtistQueue=(artist:string,limit=50,shuffle=false)=>request<{queue:Track[]}>('/queue/artist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({artist,limit,shuffle})})
export const getAlbumQueue=(artist:string,album:string,limit=500,shuffle=false)=>request<{queue:Track[]}>('/queue/album',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({artist,album,limit,shuffle})})
export const finishAudiobook=(id:number)=>request<{book_status:string}>(`/audiobooks/${id}/finished`,{method:'POST'})
export const resetAudiobook=(id:number)=>request<{book_status:string}>(`/audiobooks/${id}/not-started`,{method:'POST'})
export const setTrackFeedback=(trackId:number,value:'thumbs_up'|'thumbs_down'|'neutral')=>request<{value:string}>(`/playback/tracks/${trackId}/feedback`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value})}).then(r=>{invalidateStationCaches();return r})
export const getTrackFeedback=(trackId:number)=>request<{value:string}>(`/playback/tracks/${trackId}/feedback`)
export const setTrackFavorite=(trackId:number,favorite?:boolean)=>request<{favorite:boolean}>(`/playback/tracks/${trackId}/favorite`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({favorite})}).then(r=>{invalidateStationCaches();return r})
export const getTrackFavorite=(trackId:number)=>request<{favorite:boolean}>(`/playback/tracks/${trackId}/favorite`)
export const getRecentPlayback=(limit=5)=>request<{items:RecentPlaybackItem[]}>(`/playback/recent?limit=${limit}`)
export const logPlaybackEvent=(event:{event_type:string;track_id?:number;audiobook_id?:number;audiobook_chapter_id?:number;position_seconds?:number;completed_percent?:number;mode?:string;station_name?:string})=>request('/playback/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event)})
export const getTracksPage=(limit=100,offset=0)=>request<TrackPage>(`/library/tracks-page?limit=${limit}&offset=${offset}`)
export const getArtistTracks=(artist:string,limit=50,offset=0)=>request<TrackPage>(`/library/artists/${encodeURIComponent(artist)}/tracks?limit=${limit}&offset=${offset}`)

export const getPlaylists=()=>request<PlaylistSummary[]>('/playlists')
export const createPlaylist=(name:string,description?:string)=>request<PlaylistSummary>('/playlists',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description})})
export const deletePlaylist=(id:number)=>request<{deleted:boolean}>('/playlists/'+id,{method:'DELETE'})
export const renamePlaylist=(id:number,name:string)=>request<PlaylistSummary>('/playlists/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})})
export const getPlaylist=(id:number)=>request<PlaylistDetail>(`/playlists/${id}`)
export const addTrackToPlaylist=(playlistId:number,trackId:number)=>request<PlaylistDetail>(`/playlists/${playlistId}/tracks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({track_id:trackId})})
export const removeTrackFromPlaylist=(playlistId:number,trackId:number)=>request<PlaylistDetail>(`/playlists/${playlistId}/tracks/${trackId}`,{method:'DELETE'})
export const getPlaylistQueue=(playlistId:number,shuffle=false)=>request<{queue:Track[]}>('/queue/playlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({playlist_id:playlistId,shuffle})})
export const getSmartPlaylists=()=>request<SmartPlaylistSummary[]>('/playlists/smart')
export const getSmartPlaylistQueue=(key:string,shuffle=false,limit=100)=>request<{queue:Track[]}>('/queue/smart-playlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,shuffle,limit})})
export const createPlaylistFromTrackList=(name:string,trackIds:number[],description?:string)=>request<PlaylistDetail>('/playlists/from-track-list',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description,track_ids:trackIds})})
