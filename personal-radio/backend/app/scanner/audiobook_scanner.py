from datetime import datetime, timezone
from pathlib import Path
import json,re
from sqlalchemy.orm import Session
from .. import models
from ..config import settings
from .music_scanner import read_metadata
from .path_safety import safe_media_files
AUDIOBOOK_EXTENSIONS={'.mp3','.m4b','.m4a','.flac','.aac','.ogg','.opus'}
def key(path):return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)',path.name)]
def _read_json(path:Path)->dict:
 try:
  if path.exists():return json.loads(path.read_text(encoding='utf-8'))
 except Exception:pass
 return {}
def _merge_meta(target:dict,source:dict):
 for k,v in source.items():
  if v not in (None,'',[],{}) and target.get(k) in (None,'',[],{}):target[k]=v
def load_audiobook_sidecar(book_path:Path)->dict:
 meta_dir=book_path/'metadata';raw={}
 for name in ('audiobook.json','metadata.json','move_manifest.json'):
  data=_read_json(meta_dir/name)
  if data:raw[name]=data
 out={'title':None,'author':None,'year':None,'narrator':None,'series':None,'series_index':None,'contained_books':[],'original_release_name':None}
 candidates=[]
 for data in raw.values():
  if isinstance(data.get('metadata_json'),dict):candidates.append(data['metadata_json'])
  if isinstance(data.get('suggested_metadata'),dict):candidates.append(data['suggested_metadata'])
  candidates.append(data)
 for source in candidates:_merge_meta(out,source)
 for data in raw.values():
  for key_name in ('contained_books','books'):
   value=data.get(key_name)
   if value and not out.get('contained_books'):out['contained_books']=value
  nested=data.get('metadata_json') if isinstance(data.get('metadata_json'),dict) else {}
  value=nested.get('contained_books')
  if value and not out.get('contained_books'):out['contained_books']=value
 if not out.get('title'):out['title']=re.sub(r'^\d{4}\s*-\s*','',book_path.name)
 if not out.get('author'):out['author']=book_path.parent.name
 out['contained_books']=out.get('contained_books') or []
 return out
def chapter_title(path,order,contained):
 for item in contained:
  number=str(item.get('series_index',''))
  if number and re.search(r'(book\s*'+re.escape(number)+r'|part\s*'+re.escape(number)+r'|vol(?:ume)?\.?\s*'+re.escape(number)+r'|#\s*'+re.escape(number)+r'|\('+re.escape(number)+r'\))',path.stem,re.I):return 'Book '+number+' - '+item.get('title','')
 title=re.sub(r'^\d+[-_.\s]+','',path.stem).strip()
 if re.fullmatch(r'(track\s*)?\d+',title,re.I):return f'Chapter {order}'
 return title or f'Chapter {order}'
def scan_audiobooks(db:Session):
 root=Path(settings.AUDIOBOOKS_ROOT);result={'status':'ok','audiobooks_scanned':0,'audiobooks_added':0,'audiobooks_updated':0,'chapters_scanned':0,'roots_scanned':[],'skipped_roots':[],'errors':[]}
 if not root.is_dir():result['skipped_roots'].append(str(root));return result
 groups={}
 for path in safe_media_files(root,AUDIOBOOK_EXTENSIONS,[root]):
  parts=path.relative_to(root).parts;book=root/parts[0]/parts[1] if len(parts)>1 else root/parts[0];groups.setdefault(book,[]).append(path)
 for book,chapters in groups.items():
  try:
   chapters.sort(key=key);meta=load_audiobook_sidecar(book);title=meta.get('title') or re.sub(r'^\d{4}\s*-\s*','',book.name);author=meta.get('author') or book.parent.name;contained=meta.get('contained_books',[]);data={'relative_path':str(book.relative_to(root)),'title':title,'author':author,'narrator':meta.get('narrator'),'series':meta.get('series'),'year':meta.get('year'),'duration_seconds':0.0,'last_indexed_at':datetime.now(timezone.utc)};rows=[]
   for order,path in enumerate(chapters,1):
    duration=read_metadata(path).get('duration_seconds') or 0;data['duration_seconds']+=duration;rows.append((path,duration,order))
   found=db.query(models.Audiobook).filter_by(path=str(book)).one_or_none()
   if found:
    for k,v in data.items():setattr(found,k,v)
    db.query(models.AudiobookChapter).filter_by(audiobook_id=found.id).delete();result['audiobooks_updated']+=1
   else:found=models.Audiobook(path=str(book),status='available',favorite=False,**data);db.add(found);db.flush();result['audiobooks_added']+=1
   for path,duration,order in rows:db.add(models.AudiobookChapter(audiobook_id=found.id,path=str(path),relative_path=str(path.relative_to(root)),title=chapter_title(path,order,contained),chapter_number=order,duration_seconds=duration,sort_order=order))
   result['audiobooks_scanned']+=1;result['chapters_scanned']+=len(rows)
  except Exception as exc:result['errors'].append(f'{book}: {exc}')
 db.commit();return result
