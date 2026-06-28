import { createStation, getStationQueue, type Track } from '../api'
import { usePlayback, type QueueSource } from '../state/PlaybackContext'
import { trackToNowPlaying } from '../utils/mediaMappers'

export function useRadioActions() {
  const { playQueue } = usePlayback()

  const startSongRadio = (track: Track) => {
    const stationName = `${track.title} Radio`
    void getStationQueue('song', String(track.id)).then(result => {
      playQueue(
        result.queue.map(item => trackToNowPlaying(item, { stationName })),
        0,
        {
          kind: 'station',
          stationType: 'song',
          seedValue: String(track.id),
          stationName,
          canContinue: true,
        } satisfies QueueSource,
      )
    })
  }

  const saveSongStation = (track: Track) => {
    void createStation(`${track.title} Radio`, 'song', String(track.id), track.id).catch(() => {})
  }

  const startArtistRadio = (artist: string) => {
    const stationName = `${artist} Radio`
    void getStationQueue('artist', artist).then(result => {
      playQueue(
        result.queue.map(item => trackToNowPlaying(item, { stationName })),
        0,
        {
          kind: 'station',
          stationType: 'artist',
          seedValue: artist,
          stationName,
          canContinue: true,
        } satisfies QueueSource,
      )
    })
  }

  const saveArtistStation = (artist: string) => {
    void createStation(`${artist} Radio`, 'artist', artist).catch(() => {})
  }

  return {
    startSongRadio,
    saveSongStation,
    startArtistRadio,
    saveArtistStation,
  }
}
