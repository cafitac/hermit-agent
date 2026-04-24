from __future__ import annotations


class HTML2Text:
    ignore_links: bool
    ignore_images: bool
    body_width: int

    def handle(self, html: str) -> str: ...
