import json
import re
import time
from datetime import datetime, date
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from .store import now

TSA_URL = 'https://www.tsa.gov/travel/passenger-volumes'
GAMMA = 'https://gamma-api.polymarket.com'
CLOB = 'https://clob.polymarket.com'


class PublicHTTP:
    def __init__(self, store, retries=3, interval=1.0):
        self.store, self.retries, self.interval = store, retries, interval
        self.last = 0.0

    def get(self, url, is_json=True):
        for attempt in range(self.retries):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                req = Request(url, headers={'User-Agent': 'TSA-Research/0.1 (public research)'})
                with urlopen(req, timeout=20) as response:
                    text = response.read().decode('utf8')
                    self.store.append('raw', dict(url=url, status=response.status,
                        headers=dict(response.headers), body=text))
                return json.loads(text) if is_json else text
            except Exception as exc:
                self.store.append('request_error', dict(url=url, attempt=attempt + 1,
                                                      error=type(exc).__name__ + ': ' + str(exc)))
                if isinstance(exc, HTTPError) and exc.code in (401, 403, 404):
                    break
                retry = exc.headers.get('Retry-After') if isinstance(exc, HTTPError) else None
                delay = min(60, float(retry)) if retry and retry.isdigit() else 2 ** attempt
                if attempt + 1 < self.retries:
                    time.sleep(delay)
        raise RuntimeError('Source unavailable: ' + url)


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.inside = [], [], '', False
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('td', 'th'): self.inside, self.cell = True, ''
    def handle_data(self, text):
        if self.inside: self.cell += text
    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.row.append(self.cell.strip()); self.inside = False
        if tag == 'tr' and self.row: self.rows.append(self.row)


def parse_tsa(html):
    parser = Tables(); parser.feed(html)
    observations = {}
    for row in parser.rows:
        if len(row) < 2: continue
        try:
            d = datetime.strptime(row[0], '%m/%d/%Y').date()
        except ValueError:
            continue
        # Only column adjacent to the explicit date, never align past-year
        # columns by row position (TSA historical columns may be weekday aligned).
        if not re.fullmatch(r'[\d,]+', row[1]):
            raise ValueError('Changed TSA numeric structure')
        value = int(row[1].replace(',', ''))
        if not 10000 <= value <= 6000000 or d > date.today():
            raise ValueError('Implausible TSA row')
        if d.isoformat() in observations and observations[d.isoformat()]['value'] != value:
            raise ValueError('Conflicting duplicate TSA date')
        observations[d.isoformat()] = dict(date=d.isoformat(), value=value)
    if not observations: raise ValueError('No TSA rows; page structure changed or blocked')
    return list(observations.values())


def fetch_tsa(store, urls=None):
    http = PublicHTTP(store)
    count, errors = 0, []
    for url in urls or [TSA_URL]:
        try:
            count += store.ingest(parse_tsa(http.get(url, False)))
        except (RuntimeError, ValueError) as exc:
            errors.append(str(exc))
    return store.append('data_status', dict(ok=not errors, new_versions=count, errors=errors))['payload']
