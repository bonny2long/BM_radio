from .. import models
def track_item(track:models.Track)->dict:
 return {'id':track.id,'title':track.title,'artist':track.artist,'album':track.album,'genre':track.genre,'year':track.year,'duration_seconds':track.duration_seconds,'file_ext':track.file_ext,'library_area':track.library_area,'stream_url':f'/api/media/tracks/{track.id}/stream','cover_url':f'/api/media/tracks/{track.id}/cover'}
def chapter_item(chapter:models.AudiobookChapter)->dict:
 return {'id':chapter.id,'title':chapter.title,'sort_order':chapter.sort_order,'duration_seconds':chapter.duration_seconds,'stream_url':f'/api/media/audiobooks/{chapter.audiobook_id}/chapters/{chapter.id}/stream'}
def audiobook_item(book:models.Audiobook)->dict:
 return {'id':book.id,'title':book.title,'author':book.author,'narrator':book.narrator,'status':book.status,'favorite':book.favorite,'duration_seconds':book.duration_seconds,'cover_url':f'/api/media/audiobooks/{book.id}/cover'}
