export interface Track {
  id: number;
  path: string;
  relative_path: string;
  title: string;
  artist: string;
  album: string;
  album_artist?: string;
  genre?: string;
  year?: number;
  duration_seconds: number;
  file_ext: string;
  library_area: string;
  cover_path?: string;
}

export interface Album {
  title: string;
  artist: string;
  tracks: Track[];
  cover_path?: string;
}

export interface Artist {
  name: string;
  albums: Album[];
}
