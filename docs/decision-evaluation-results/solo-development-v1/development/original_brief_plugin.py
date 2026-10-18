from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def original_review_script(page):
    original=Path('/tmp/decision-solo-original-review.js').read_text()
    page.route('**/decision-review.js', lambda route: route.fulfill(body=original,content_type='application/javascript'))
