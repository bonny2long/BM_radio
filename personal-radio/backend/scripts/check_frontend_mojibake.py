from __future__ import annotations

from pathlib import Path
import sys

TOKENS = ["Ã", "Â", "â", "�", "ð"]
TEXT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".json", ".md", ".svg"}


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    src = repo / "frontend" / "src"
    failures: list[str] = []
    for path in src.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in TOKENS:
            if token in text:
                failures.append(f"{path.relative_to(repo)}: {ascii(token)}")
    if failures:
        print("Frontend mojibake found:")
        print("\n".join(failures))
        sys.exit(1)
    print("ok: no frontend mojibake tokens")


if __name__ == "__main__":
    main()