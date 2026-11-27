"""Immutable reviewed filings with transactional logical report heads."""
from datetime import date
import json
from pathlib import Path
import sqlite3
from .domain import ACCESSION, ANCHOR, CURRENCIES, SHA, STANDARDS, EvidenceError, evidence_url, report_group, verify_fact


ACQUISITION = {'manual_import', 'sec_official_single_run', 'sec_adapter_snapshot', 'legacy_reviewed_snapshot', 'sec_on_demand'}


def validate_dataset(data):
    recognized = (data.get('dataset_kind') == 'real_official_reviewed_snapshot'
                  or (data.get('dataset_kind') == 'real_official_auto_verified'
                      and data.get('schema_version') == 3 and data.get('acquisition_mode') == 'sec_on_demand'))
    if not recognized or data.get('acquisition_mode') not in ACQUISITION:
        raise EvidenceError('unapproved_snapshot')
    issuer, doc, facts = data['issuer'], data['document'], data['facts']
    cik = issuer['cik']
    accession, sha = doc['accession'], doc['original_sha256']
    if (not isinstance(cik, str) or len(cik) != 10 or not cik.isascii() or not cik.isdecimal()
            or not ACCESSION.fullmatch(accession) or not SHA.fullmatch(sha) or not report_group(doc['form'])):
        raise EvidenceError('invalid_document_identity')
    period, filed = date.fromisoformat(doc['report_end']), date.fromisoformat(doc['published_on'])
    if period > filed:
        raise EvidenceError('invalid_report_date')
    evidence_url(doc['original_url'], cik, accession)
    currency = doc.get('currency', facts[0]['currency'] if facts else None)
    if currency not in CURRENCIES or doc['accounting_standard'] not in STANDARDS or doc['scope'] != 'consolidated':
        raise EvidenceError('invalid_report_currency_or_scope')
    verification = doc.get('verification_status', 'financials_verified')
    if verification not in ('financials_verified', 'document_verified') or bool(facts) != (verification == 'financials_verified'):
        raise EvidenceError('invalid_verification_state')
    for attachment in doc.get('attachments', []):
        evidence_url(attachment['url'], cik, accession)
        if not SHA.fullmatch(attachment['sha256']):
            raise EvidenceError('invalid_attachment_hash')
    automatic = data.get('schema_version') == 3
    if automatic and (not SHA.fullmatch(doc.get('companyfacts_sha256', '')) or data.get('narrative')):
        raise EvidenceError('missing_automatic_evidence_receipt')
    ids, slots = set(), set()
    for fact in facts:
        verify_fact(fact)
        if automatic and fact.get('verification') != 'automatic_ixbrl_companyfacts_match':
            raise EvidenceError('unverified_automatic_fact')
        slot = fact.get('slot', 'current' if fact['period_end'] == doc['report_end'] else 'prior')
        key = (fact.get('segment', fact['metric']), slot)
        if (fact['id'] in ids or key in slots or slot not in ('current', 'prior')
                or (slot == 'current') != (fact['period_end'] == doc['report_end'])):
            raise EvidenceError('duplicate_or_mislabeled_fact')
        ids.add(fact['id'])
        slots.add(key)
        if (fact['version'] != accession or fact['source_url'] != doc['original_url']
                or fact.get('original_sha256', sha) != sha or fact.get('cik', cik) != cik
                or fact['currency'] != currency
                or fact['scope'] != ('segment' if fact['metric'] == 'segment_revenue' else doc['scope'])
                or fact['accounting_standard'] != doc['accounting_standard']):
            raise EvidenceError('document_fact_version_mismatch')
        if data.get('schema_version') in (2, 3) and (not fact.get('cik') or not fact.get('original_sha256')):
            raise EvidenceError('missing_fact_version_identity')
    for narrative in data.get('narrative', []):
        if (narrative['kind'] not in ('business', 'management_statement') or not narrative['text']
                or not ANCHOR.fullmatch(narrative['anchor'])):
            raise EvidenceError('unverified_narrative')
    return data


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS report_versions (
                    cik TEXT NOT NULL, accession TEXT NOT NULL, sha TEXT NOT NULL,
                    report_key TEXT NOT NULL, report_end TEXT NOT NULL, published_on TEXT NOT NULL,
                    payload TEXT NOT NULL, previous_accession TEXT, previous_sha TEXT,
                    PRIMARY KEY (cik, accession, sha),
                    FOREIGN KEY (cik, previous_accession, previous_sha)
                        REFERENCES report_versions(cik, accession, sha));
                CREATE TABLE IF NOT EXISTS report_heads (
                    cik TEXT NOT NULL, report_key TEXT NOT NULL, accession TEXT NOT NULL, sha TEXT NOT NULL,
                    PRIMARY KEY (cik, report_key),
                    FOREIGN KEY (cik, accession, sha) REFERENCES report_versions(cik, accession, sha));
            """)
            old_tables = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('versions','active')").fetchone()[0]
            if old_tables == 2:
                # Preserve the Phase 1 active snapshot on upgrade. Its legacy revisions
                # stay in the old tables for offline inspection.
                previous = db.execute('SELECT payload FROM versions JOIN active USING(original_sha)').fetchone()
                if previous:
                    old = json.loads(previous[0])
                    db.execute('BEGIN IMMEDIATE')
                    if not db.execute('SELECT 1 FROM report_heads WHERE cik=?', (old['issuer']['cik'],)).fetchone():
                        self._put(db, old)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def put(self, data, supersedes=None, *, seed=False):
        validate_dataset(data)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._put(db, data, supersedes, seed)

    def _put(self, db, data, supersedes=None, seed=False):
        validate_dataset(data)
        doc, cik = data['document'], data['issuer']['cik']
        sha, accession = doc['original_sha256'], doc['accession']
        end, filed = doc['report_end'], doc['published_on']
        group = report_group(doc['form'])
        key = f'{group}:{end}' if group != 'foreign_report' else f'{group}:{accession}'
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        existing = db.execute('SELECT payload FROM report_versions WHERE cik=? AND accession=? AND sha=?',
                              (cik, accession, sha)).fetchone()
        if existing:
            if existing[0] != payload:
                previous = json.loads(existing[0])
                # Acquisition provenance describes how this SQLite copy was populated.
                previous['acquisition_mode'] = data['acquisition_mode']
                if previous != data:
                    raise EvidenceError('immutable_version_conflict')
            return 'unchanged'
        if supersedes and group == 'foreign_report':
            parent = db.execute(
                'SELECT report_key FROM report_versions WHERE cik=? AND accession=? AND sha=? AND report_end=?',
                (cik, supersedes[0], supersedes[1], end)).fetchone()
            if parent:
                key = parent[0]
        prev = db.execute("""SELECT h.accession,h.sha,v.published_on FROM report_heads h
                             JOIN report_versions v USING(cik,accession,sha)
                             WHERE h.cik=? AND h.report_key=?""", (cik, key)).fetchone()
        if seed and prev:
            return 'existing_report'
        if prev and (supersedes != (prev[0], prev[1]) or filed < prev[2]):
            raise EvidenceError('explicit_correction_required')
        if not prev and supersedes:
            raise EvidenceError('correction_parent_missing')
        db.execute('INSERT INTO report_versions VALUES (?,?,?,?,?,?,?,?,?)',
                   (cik, accession, sha, key, end, filed, payload, *(supersedes or (None, None))))
        db.execute("""INSERT INTO report_heads VALUES(?,?,?,?) ON CONFLICT(cik,report_key)
                      DO UPDATE SET accession=excluded.accession, sha=excluded.sha""", (cik, key, accession, sha))
        return 'imported'

    def reports(self, cik):
        with self.connect() as db:
            rows = db.execute("""SELECT v.payload FROM report_heads h
                                 JOIN report_versions v USING(cik,accession,sha)
                                 WHERE h.cik=? ORDER BY v.report_end DESC, v.published_on DESC""", (cik,))
            return [{'accession': doc['accession'], 'report_end': doc['report_end'],
                     'form': doc['form'], 'published_on': doc['published_on'], 'label': doc.get('label', doc['report_end']),
                     'status': doc.get('verification_status', 'financials_verified'), 'sha256': doc['original_sha256']}
                    for doc in (json.loads(row[0])['document'] for row in rows)]

    def read(self, cik=None, accession=None, sha=None):
        with self.connect() as db:
            if accession and sha:
                row = db.execute('SELECT payload FROM report_versions WHERE cik=? AND accession=? AND sha=?',
                                 (cik, accession, sha)).fetchone()
            else:
                row = db.execute("""SELECT v.payload FROM report_heads h
                                    JOIN report_versions v USING(cik,accession,sha)
                                    WHERE (? IS NULL OR h.cik=?) AND (? IS NULL OR h.accession=?)
                                    ORDER BY CASE WHEN v.report_key LIKE 'foreign_report:%' THEN 1 ELSE 0 END,
                                      v.report_end DESC, v.published_on DESC LIMIT 1""",
                                 (cik, cik, accession, accession)).fetchone()
        return validate_dataset(json.loads(row[0])) if row else None
