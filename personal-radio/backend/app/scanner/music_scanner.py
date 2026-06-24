from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json,re
from sqlalchemy.orm import Session
from .. import models
from ..config import settings
from .path_safety import safe_media_files
MUSIC_EXTENSIONS={'.mp3','.flac','.m4a','.aac','.ogg','.opus','.wav'}
def _tag_value(tags:Any,*keys:str):
 for key in keys:
  value=tags.get(key) if tags and hasattr(tags,'get') else None
  if value:return str(value[0] if isinstance(value,(list,tuple)) else value).strip()
 return None
def read_metadata(path:Path)->dict[str,Any]:
 result={'duration_seconds':None}
 try:
  from mutagen import File
  media=File(path,easy=True);tags=media.tags if media else None;result.update({'duration_seconds':getattr(getattr(media,'info',None),'length',None),'title':_tag_value(tags,'title'),'artist':_tag_value(tags,'artist'),'album':_tag_value(tags,'album'),'album_artist':_tag_value(tags,'albumartist'),'genre':_tag_value(tags,'genre'),'year':_tag_value(tags,'date','year')})
 except Exception:pass
 try:result['year']=int(str(result.get('year'))[:4])
 except Exception:result['year']=None
 return result
def generic(v):return not v or str(v).strip().lower() in {'unknown artist','unknown album','unknown year','cd1','cd2','track 01','various artists'}
def year_title(name):
 m=re.match(r'^(\d{4})\s*-\s*(.+)$',name);return (int(m.group(1)),m.group(2)) if m else (None,name)
def clean_title(name):return re.sub(r'^\d+(?:[-_.\s]+\d+)?\s*[-_.]*\s*','',name).strip() or name
def sidecar(path,root):
 for folder in [path.parent,*path.parents]:
  if folder==root.parent:break
  for name in ('music-album.json','discography.json'):
   file=folder/'metadata'/name
   if file.is_file():
    try:return json.loads(file.read_text(encoding='utf-8'))
    except Exception:return {}
 return {}
def infer(path,root):
 parts=path.relative_to(root).parts
 if parts and parts[0]=='Discographies' and len(parts)>=4:
  artist,release=parts[1],parts[2];folder=next((p for p in parts[3:-1] if re.match(r'^\d{4}\s*-',p)),parts[-2]);year,album=year_title(folder);return {'artist':artist,'album':album,'album_artist':artist,'year':year,'library_area':'Discographies','release_type':release}
 for marker in ('MP3','FLAC'):
  if marker in parts:
   i=parts.index(marker);artist=parts[i+1] if len(parts)>i+1 else None;folder=next((p for p in parts[i+2:-1] if re.match(r'^\d{4}\s*-',p)),path.parent.name);year,album=year_title(folder);return {'artist':artist,'album':album,'album_artist':artist,'year':year,'library_area':'Library'}
 return {'library_area':'Library'}
def pick(side,path,tags,key):
 s=side.get(key) or side.get('suggested_metadata',{}).get(key)
 return s or path.get(key) or (None if generic(tags.get(key)) else tags.get(key))
def scan_music(db:Session):
 roots=[Path(settings.MUSIC_MP3_ROOT),Path(settings.MUSIC_FLAC_ROOT),Path(settings.MUSIC_DISCOGRAPHIES_ROOT)];existing=[r for r in roots if r.is_dir()];root=Path(settings.MUSIC_ROOT);result={'status':'ok','tracks_scanned':0,'tracks_added':0,'tracks_updated':0,'roots_scanned':[str(r) for r in existing],'skipped_roots':[str(r) for r in roots if not r.is_dir()],'errors':[]}
 for scan_root in existing:
  for path in safe_media_files(scan_root,MUSIC_EXTENSIONS,existing):
   try:
    tags=read_metadata(path);p=infer(path,root);s=sidecar(path,root);artist=pick(s,p,tags,'artist') or path.parent.name;album=pick(s,p,tags,'album') or p.get('album') or path.parent.name;data={'relative_path':str(path.relative_to(root)),'title':clean_title(tags.get('title') or path.stem),'artist':artist,'album':album,'album_artist':pick(s,p,tags,'album_artist') or artist,'genre':pick(s,p,tags,'genre'),'year':pick(s,p,tags,'year'),'duration_seconds':tags.get('duration_seconds'),'file_ext':path.suffix.lower(),'library_area':p.get('library_area','Library'),'last_indexed_at':datetime.now(timezone.utc)};track=db.query(models.Track).filter_by(path=str(path)).one_or_none()
    if track:
     for k,v in data.items():setattr(track,k,v)
     result['tracks_updated']+=1
    else:db.add(models.Track(path=str(path),**data));result['tracks_added']+=1
    result['tracks_scanned']+=1
   except Exception as exc:result['errors'].append(f'{path}: {exc}')
 db.commit();return result
