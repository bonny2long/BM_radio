from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scanner.audiobook_scanner import audiobook_chapter_sort_key, explicit_book_index


def test_explicit_book_index() -> None:
    assert explicit_book_index(Path("Example (Book 1).mp3")) == 1
    assert explicit_book_index(Path("Example Book 02.mp3")) == 2
    assert explicit_book_index(Path("Example Part 3.mp3")) == 3
    assert explicit_book_index(Path("Example Vol. 4.mp3")) == 4
    assert explicit_book_index(Path("Example Volume 5.mp3")) == 5
    assert explicit_book_index(Path("Example #6.mp3")) == 6
    assert explicit_book_index(Path("01 Track 1.mp3")) is None


def test_darth_bane_order() -> None:
    files = [
        Path("Star Wars Darth Bane Dynasty Of Evil (Book 3) [Unabridged].mp3"),
        Path("Star Wars Darth Bane Path Of Destruction (Book 1) [Unabridged].mp3"),
        Path("Star Wars Darth Bane Rule Of Two (Book 2) [Unabridged].mp3"),
    ]
    ordered = sorted(files, key=audiobook_chapter_sort_key)
    assert "Book 1" in ordered[0].name, ordered
    assert "Book 2" in ordered[1].name, ordered
    assert "Book 3" in ordered[2].name, ordered


def test_revan_numeric_order() -> None:
    files = [
        Path("Disc 1/10 Track 10.mp3"),
        Path("Disc 1/02 Track 2.mp3"),
        Path("Disc 1/01 Track 1.mp3"),
    ]
    ordered = sorted(files, key=audiobook_chapter_sort_key)
    assert ordered[0].name == "01 Track 1.mp3", ordered
    assert ordered[1].name == "02 Track 2.mp3", ordered
    assert ordered[2].name == "10 Track 10.mp3", ordered


def main() -> None:
    test_explicit_book_index()
    test_darth_bane_order()
    test_revan_numeric_order()
    print("Audiobook multi-book ordering checks passed.")


if __name__ == "__main__":
    main()