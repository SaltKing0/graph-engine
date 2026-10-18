from pathlib import Path
import re,urllib.parse
ROOT=Path(__file__).resolve().parents[4]
files=['CONTRIBUTING.md','docs/decision-source-observations.md','docs/decision-release-readiness.md','docs/decision-evaluation-results/false-alert-development-v1/reviewed-v1/README.md']
count=0
for name in files:
 path=ROOT/name
 for raw in re.findall(r'\[[^\]]*\]\(([^)]+)\)',path.read_text()):
  if re.match(r'\w+://',raw):continue
  url=urllib.parse.urlsplit(raw)
  target=path.parent/urllib.parse.unquote(url.path) if url.path else path
  assert target.is_file(),(name,raw)
  if url.fragment and target.suffix=='.md':
   headings=re.findall(r'^#+\s+(.+)$',target.read_text(),re.M)
   slugs=[re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in headings]
   assert urllib.parse.unquote(url.fragment) in slugs,(name,raw)
  count+=1
print(f'{count} local Markdown file/anchor references verified across {len(files)} documents.')
