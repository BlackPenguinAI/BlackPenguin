"""First-party public rendering of approved gallery snapshots, including old snapshots.

Only embedded raster images and escaped text survive rendering. Uploaded HTML,
remote URLs, attributes and scripts are never executed.
"""
from __future__ import annotations

import base64
import hashlib
import re
from html import escape
from html.parser import HTMLParser

from fastapi.responses import HTMLResponse

GALLERY_SCRIPT = """(() => {
const buttons = [...document.querySelectorAll('.thumbnail')];
const dialog = document.querySelector('dialog');
const image = document.createElement('img');
const caption = dialog.querySelector('.caption');
const counter = dialog.querySelector('.counter');
dialog.querySelector('.image').append(image);
let index = 0;
function show(next) {
  index = (next + buttons.length) % buttons.length;
  const original = buttons[index].querySelector('img');
  image.src = original.src; image.alt = original.alt;
  caption.textContent = original.alt;
  counter.textContent = `${index + 1} / ${buttons.length}`;
}
buttons.forEach((button, i) => button.addEventListener('click', () => {
  show(i); dialog.showModal();
}));
dialog.querySelector('.close').addEventListener('click', () => dialog.close());
dialog.querySelector('.previous').addEventListener('click', () => show(index - 1));
dialog.querySelector('.next').addEventListener('click', () => show(index + 1));
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
dialog.addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft') { event.preventDefault(); show(index - 1); }
  if (event.key === 'ArrowRight') { event.preventDefault(); show(index + 1); }
});
})();"""
SCRIPT_HASH = base64.b64encode(hashlib.sha256(GALLERY_SCRIPT.encode()).digest()).decode()
PUBLIC_HEADERS = {
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow',
    'Content-Security-Policy': "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        f"script-src 'sha256-{SCRIPT_HASH}'; base-uri 'none'; form-action 'none'; sandbox allow-scripts",
}
STYLE = """*{box-sizing:border-box}body{margin:0;background:#0b0b0b;color:#f5f5f5;font:16px/1.5 system-ui,sans-serif}
main{max-width:1120px;margin:auto;padding:32px 20px}header{border-bottom:1px solid #333;padding-bottom:20px;margin-bottom:24px}
h1{font-size:clamp(24px,5vw,36px);margin:0 0 8px}h2{font-size:22px;margin:0 0 6px}p{color:#bbb;margin:8px 0}
.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:16px}
figure{margin:0;min-width:0}button{font:inherit;color:inherit;background:#181818;border:1px solid #555;border-radius:10px;cursor:pointer;padding:10px 16px}
button:focus-visible{outline:3px solid #ffc400;outline-offset:3px}.thumbnail{padding:0;width:100%;overflow:hidden;display:block}
.thumbnail img{display:block;width:100%;height:220px;object-fit:cover}figcaption{padding:8px 2px;color:#bbb;overflow-wrap:anywhere}
dialog{color:#fff;background:#111;border:1px solid #555;border-radius:14px;width:min(100% - 24px,1100px);max-height:95dvh;padding:16px}
dialog::backdrop{background:#000d}.toolbar,.navigation{display:flex;align-items:center;justify-content:space-between;gap:12px}.image{text-align:center;margin:12px 0}
.image img{max-width:100%;max-height:65dvh;object-fit:contain}.caption{overflow-wrap:anywhere}.counter{color:#bbb}
@media(max-width:480px){main{padding:24px 16px}.thumbnail img{height:200px}.image img{max-height:55dvh}}
"""


class SnapshotImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: list[tuple[str, str]] = []
        self.heading = ''
        self.in_heading = False

    def handle_starttag(self, tag, attrs):
        if tag == 'h1':
            self.in_heading = True
        if tag != 'img':
            return
        attrs = dict(attrs)
        src = attrs.get('src') or ''
        if re.fullmatch(r'data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}', src):
            self.images.append((src, attrs.get('alt') or 'Property image'))


    def handle_endtag(self, tag):
        if tag == 'h1':
            self.in_heading = False

    def handle_data(self, data):
        if self.in_heading:
            self.heading += data


def render_gallery(content: bytes, *, project_name: str, property_name: str) -> bytes:
    parser = SnapshotImages()
    parser.feed(content.decode('utf-8'))
    property_name = parser.heading or property_name
    if not parser.images:
        raise ValueError('Gallery has no approved embedded images')
    figures = ''.join(
        f'<figure><button type="button" class="thumbnail" aria-label="Open image {i}">'
        f'<img src="{escape(src, quote=True)}" alt="{escape(label, quote=True)}" loading="lazy">'
        f'</button><figcaption>{escape(label)}</figcaption></figure>'
        for i, (src, label) in enumerate(parser.images, 1)
    )
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(project_name)} · {escape(property_name)} · Available images</title>'
        f'<style>{STYLE}</style></head><body><main><header><h1>{escape(project_name)}</h1>'
        f'<h2>{escape(property_name)}</h2><p>Available images · {len(parser.images)}</p></header>'
        f'<div class="gallery">{figures}</div><noscript><p>Enable JavaScript to open the image viewer.</p></noscript>'
        '</main><dialog aria-label="Property image viewer"><div class="toolbar">'
        '<span class="counter" aria-live="polite"></span><button type="button" class="close" autofocus>Close</button></div>'
        '<div class="image"></div><p class="caption"></p><div class="navigation">'
        '<button type="button" class="previous" aria-label="Previous image">Previous</button>'
        '<button type="button" class="next" aria-label="Next image">Next</button></div></dialog>'
        f'<script>{GALLERY_SCRIPT}</script></body></html>').encode()


def unavailable_response() -> HTMLResponse:
    return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Resource unavailable</title><style>{STYLE}</style></head><body><main>'
        '<h1>This resource is no longer available.</h1>'
        '<p>Please contact the project team for updated information.</p></main></body></html>',
        status_code=404, headers=PUBLIC_HEADERS)
