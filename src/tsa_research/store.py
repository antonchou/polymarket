"""Append-only JSON journal is the recovery source; DuckDB/Parquet are projections.
Never silently substitute another database for DuckDB. Offline journal mode is
explicit and useful when dependencies cannot be downloaded.
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Journal files are immutable; cache only their kind, never raw response bodies.
_KINDS = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    return d.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('TSA_DATA_DIR', 'data'))
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = self.root / 'journal'
        self.journal.mkdir(exist_ok=True)

    def append(self, kind, payload, at=None):
        row = dict(id=uuid4().hex, kind=kind, fetched_at=at or now(), recorded_at_ns=time.time_ns(), payload=payload)
        target = self.journal / (row['id'] + '.json')
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(row, ensure_ascii=False, allow_nan=False), encoding='utf8')
        temp.replace(target)
        _KINDS[str(target.resolve())] = kind
        return row

    def rows(self, kind=None):
        rows = []
        for path in self.journal.glob('*.json'):
            key = str(path.resolve())
            if kind is not None and key in _KINDS and _KINDS[key] != kind:
                continue
            row = json.loads(path.read_text())
            _KINDS[key] = row['kind']
            if kind is None or row['kind'] == kind:
                rows.append(row)
        return sorted(rows, key=lambda r: (stamp(r['fetched_at']), r.get('recorded_at_ns',0), r['id']))

    def latest(self, kind):
        rows = self.rows(kind)
        return rows[-1] if rows else None

    def ingest(self, observations, at=None, source='TSA'):
        at = at or now()
        stamp(at)
        previous = {}
        for r in self.rows('throughput'):
            previous[r['payload']['date']] = r['payload']
        count = 0
        for obs in observations:
            old = previous.get(obs['date'])
            if old and old['value'] == obs['value']:
                continue
            version = digest({'date': obs['date'], 'value': obs['value']})
            p = dict(obs, source=source, first_seen_at=at, version=version,
                     source_published_at=obs.get('source_published_at'),
                     previous_version=old['version'] if old else None)
            self.append('throughput', p, at)
            previous[obs['date']] = p
            count += 1
        return count

    def asof(self, at):
        cutoff = stamp(at)
        result = {}
        for row in self.rows('throughput'):
            p = row['payload']
            if stamp(p['first_seen_at']) <= cutoff and (
                not p['source_published_at'] or stamp(p['source_published_at']) <= cutoff
            ):
                result[p['date']] = p['value']
        return result

    def export(self):
        import duckdb
        import tempfile
        files = list(self.journal.glob('*.json'))
        if not files:
            return 0
        # Build projections separately. Raw responses can be megabytes each;
        # never materialize the whole journal or serialize it twice in memory.
        with tempfile.TemporaryDirectory(prefix='export-', dir=self.root) as tmp:
            stage = Path(tmp)
            db = stage / 'research.duckdb'
            settings = {'memory_limit':'512MB', 'threads':2, 'preserve_insertion_order':False}
            con = duckdb.connect(str(db), config=settings)
            try:
                con.execute('CREATE TABLE snapshots(id VARCHAR, kind VARCHAR, fetched_at TIMESTAMPTZ, payload JSON)')
                con.execute('CREATE TABLE throughput(id VARCHAR, statistical_date DATE, value BIGINT, source_published_at TIMESTAMPTZ, first_seen_at TIMESTAMPTZ, fetched_at TIMESTAMPTZ, version VARCHAR, previous_version VARCHAR)')
                batch, facts = [], []
                def flush():
                    if batch:
                        con.execute('BEGIN')
                        con.executemany('INSERT INTO snapshots VALUES (?,?,?,?)', batch)
                        con.execute('COMMIT')
                        batch.clear()
                for path in files:
                    r = json.loads(path.read_text())
                    payload = r['payload']
                    if r['kind']=='raw' and 'body' in payload:
                        # Original response stays in its immutable journal file.
                        # Index its location/hash rather than duplicating GBs of
                        # irrelevant market JSON into a single database column.
                        payload = dict(payload)
                        body = payload.pop('body')
                        payload['body_ref'] = str(Path('journal')/path.name)
                        payload['body_sha256'] = hashlib.sha256(body.encode('utf8')).hexdigest()
                        payload['body_bytes'] = len(body.encode('utf8'))
                    batch.append((r['id'],r['kind'],r['fetched_at'],json.dumps(payload)))
                    if r['kind']=='throughput':
                        p=r['payload']
                        facts.append((r['id'],p['date'],p['value'],p.get('source_published_at'),p['first_seen_at'],r['fetched_at'],p['version'],p.get('previous_version')))
                    if len(batch)>=8: flush()
                flush()
                if facts:
                    con.execute('BEGIN')
                    con.executemany('INSERT INTO throughput VALUES (?,?,?,?,?,?,?,?)',facts)
                    con.execute('COMMIT')
                for table in ('snapshots','throughput'):
                    con.execute(f"COPY {table} TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE_BYTES '16MB')",[str(stage/(table+'.parquet'))])
            finally:
                con.close()
            # The old database/WAL are derived projections. Do not replay a
            # potentially huge obsolete WAL when a complete replacement exists.
            # Keep the WAL aside until the replacement succeeds.
            wal = self.root/'research.duckdb.wal'
            backup_wal = stage/'previous.wal'
            if wal.exists(): wal.replace(backup_wal)
            try:
                for name in ('snapshots.parquet','throughput.parquet','research.duckdb'):
                    (stage/name).replace(self.root/name)
            except BaseException:
                if backup_wal.exists(): backup_wal.replace(wal)
                raise
        return len(files)
