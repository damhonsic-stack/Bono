#!/usr/bin/env python3
"""Aktualizace Bona z GitHubu – jedním příkazem i v a-Shell na iPadu:

    python3 update.py

Stáhne nejnovější verzi a přepíše jen kód. Tvoje data (složka data/: Gemini klíč,
rekordy, kalibrace, debriefy) zůstanou beze změny.
"""
import io
import os
import sys
import urllib.request
import zipfile

REPO = 'damhonsic-stack/Bono'
BRANCH = sys.argv[1] if len(sys.argv) > 1 else 'f1-ai-engineer'
HERE = os.path.dirname(os.path.abspath(__file__))
URL = 'https://codeload.github.com/%s/zip/refs/heads/%s' % (REPO, BRANCH)


def main():
    print('Stahuji %s …' % URL)
    with urllib.request.urlopen(URL, timeout=60) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    n = 0
    for info in z.infolist():
        parts = info.filename.split('/', 1)
        if len(parts) < 2 or not parts[1]:
            continue
        rel = parts[1]
        if rel.startswith('data/') or info.is_dir():
            continue                      # data nikdy nepřepisuj
        dest = os.path.join(HERE, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(z.read(info))
        n += 1
    print('Hotovo, aktualizováno %d souborů. Spusť znovu: python3 server.py' % n)


if __name__ == '__main__':
    main()
