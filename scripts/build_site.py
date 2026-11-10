#!/usr/bin/env python3
"""Copy an explicit public-site allowlist; never publish repository internals."""
from pathlib import Path
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
FILES = ['.nojekyll', 'CNAME', '404.html', 'index.html', 'robots.txt', 'sitemap.xml', 'style.css', 'tweet-metrics.js', 'social.js']
DIRECTORIES = ['about', 'artstudiovr-comingsoon', 'artstudiovrprivacypolicy', 'assets', 'games', 'games-1', 'portfolio', 'privacy', 'say-hi', 'tools-projects', 'tutorials', 'work']
EXTENSIONS = {'.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.mp4', '.webm', '.woff', '.woff2', '.ttf', '.pdf', '.txt', '.json'}


def build(output):
    output = output.resolve()
    if output == ROOT or ROOT.is_relative_to(output):
        raise ValueError('Unsafe output directory')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output directory must be empty')
    output.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = ROOT / name
        if path.is_file() and not path.is_symlink():
            shutil.copy2(path, output / name)
    for name in DIRECTORIES:
        for path in (ROOT / name).rglob('*'):
            relative = path.relative_to(ROOT)
            if path.is_file() and not any(p.startswith('.') for p in relative.parts) and not any(p.is_symlink() for p in [path, *path.parents]) and path.suffix.lower() in EXTENSIONS:
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    (output / 'data').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'data/social-sources.json', output / 'data/social-sources.json')


if __name__ == '__main__':
    build(Path(sys.argv[1]))
