import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TutorialLayoutTests(unittest.TestCase):
    def test_detail_pages_have_one_title_and_preserve_notes(self):
        paths = list((ROOT / 'tutorials').glob('*/index.html'))
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(page=path.parent.name):
                html = path.read_text()
                notes = re.search(r'<div class="tutorial-notes">(.*?)</div>', html).group(1)
                self.assertNotRegex(notes, r'<h[1-6]\b')
                self.assertTrue(notes.startswith('<p>'))
                self.assertIn('class="tutorial-date"', notes)
                self.assertEqual(len(re.findall(r'<h1\b', html)), 1)
                self.assertIn('class="one-line"', html)
                self.assertIn('class="post-video"', html)
                self.assertIn('<a href="/privacy/">Privacy</a>', html)
                self.assertNotIn('class="social-legal"', html)
                self.assertNotIn('class="metrics-legend"', html)

    def test_tutorials_load_current_layout_version(self):
        version = hashlib.sha256((ROOT / 'style.css').read_bytes()).hexdigest()[:12]
        for path in (ROOT / 'tutorials').rglob('index.html'):
            with self.subTest(page=str(path.relative_to(ROOT))):
                self.assertIn(f'href="/style.css?v={version}"', path.read_text())


if __name__ == '__main__':
    unittest.main()
