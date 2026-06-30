import os
import sys

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db import SessionLocal
from app import models

MOJIBAKE_PATTERNS = [
    'â??',
    'â€™',
    'â€œ',
    'â€',
    'Ã—',
    'Â·',
]

def check_mojibake():
    db = SessionLocal()
    try:
        print("Scanning metadata for mojibake...")
        found_issues = False
        
        # Check Tracks
        tracks = db.query(models.Track).all()
        for track in tracks:
            title = track.title or ''
            album = track.album or ''
            artist = track.artist or ''
            
            for field, text in [('title', title), ('album', album), ('artist', artist)]:
                for pattern in MOJIBAKE_PATTERNS:
                    if pattern in text:
                        print(f"[WARNING] Mojibake found in Track {field}: '{text}' (Track ID: {track.id}, Path: {track.relative_path})")
                        found_issues = True
                        
        # Check Audiobooks (if model exists and has title/author)
        try:
            audiobooks = db.query(models.Audiobook).all()
            for book in audiobooks:
                title = book.title or ''
                author = book.author or ''
                
                for field, text in [('title', title), ('author', author)]:
                    for pattern in MOJIBAKE_PATTERNS:
                        if pattern in text:
                            print(f"[WARNING] Mojibake found in Audiobook {field}: '{text}' (Book ID: {book.id}, Path: {book.relative_path})")
                            found_issues = True
        except Exception:
            pass # Audiobook table might not be used or might be configured differently
            
        if found_issues:
            print("\nMojibake detection complete. Warnings found in database titles/metadata.")
            print("Note: This script acts as a detection warning layer and does not automatically edit production metadata.")
        else:
            print("Mojibake check passed. No bad characters detected in database titles/metadata.")
            
    finally:
        db.close()

if __name__ == '__main__':
    check_mojibake()
