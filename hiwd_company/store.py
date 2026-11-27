"""SQLite immutable snapshots and explicit version correction."""
import json
from pathlib import Path
import sqlite3
from .domain import EvidenceError, verify_fact


def validate_dataset(data):
    if data.get('dataset_kind') != 'real_official_reviewed_snapshot':
        raise EvidenceError('synthetic_or_unknown_dataset_not_allowed_in_reader')
    if data.get('acquisition_mode') not in ('manual_import', 'sec_official_single_run'):
        raise EvidenceError('unapproved_acquisition_mode')
    document, facts = data['document'], data['facts']
    if data['issuer']['cik'] != '0000320193' or len(facts) != 12 or len({f['id'] for f in facts}) != 12:
        raise EvidenceError('unsupported_issuer_or_incomplete_snapshot')
    for fact in facts:
        verify_fact(fact)
        if fact['version'] != document['accession'] or fact['source_url'] != document['original_url']:
            raise EvidenceError('document_fact_version_mismatch')
    return data


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS versions (
                    original_sha TEXT PRIMARY KEY, accession TEXT NOT NULL,
                    payload TEXT NOT NULL, supersedes TEXT REFERENCES versions(original_sha),
                    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
                CREATE TABLE IF NOT EXISTS active (slot INTEGER PRIMARY KEY CHECK(slot=1), original_sha TEXT REFERENCES versions(original_sha));
            ''')

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def put(self, data, supersedes=None):
        validate_dataset(data)
        sha, accession = data['document']['original_sha256'], data['document']['accession']
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            existing = db.execute('SELECT payload FROM versions WHERE original_sha=?', (sha,)).fetchone()
            if existing:
                if existing[0] != payload:
                    raise EvidenceError('immutable_version_conflict')
                return 'unchanged'
            previous = db.execute('SELECT original_sha FROM active WHERE slot=1').fetchone()
            if previous and supersedes != previous[0]:
                raise EvidenceError('explicit_correction_required')
            if not previous and supersedes:
                raise EvidenceError('correction_parent_missing')
            db.execute('INSERT INTO versions(original_sha,accession,payload,supersedes) VALUES(?,?,?,?)',
                       (sha, accession, payload, supersedes))
            db.execute('INSERT INTO active VALUES(1,?) ON CONFLICT(slot) DO UPDATE SET original_sha=excluded.original_sha', (sha,))
        return 'imported'

    def read(self):
        with self.connect() as db:
            result = db.execute('SELECT payload FROM versions JOIN active USING(original_sha) WHERE slot=1').fetchone()
        return validate_dataset(json.loads(result[0])) if result else None
