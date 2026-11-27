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
                      and data.get('schema_version') in (3, 4) and data.get('acquisition_mode') == 'sec_on_demand'))
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
    automatic = data.get('schema_version') in (3, 4)
    if data.get('schema_version') == 4 and any(not fact.get('semantic') or not fact.get('source_row')
                                              for fact in facts):
        raise EvidenceError('missing_primary_statement_semantics')
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
        if data.get('schema_version') in (2, 3, 4) and (not fact.get('cik') or not fact.get('original_sha256')):
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
                CREATE TABLE IF NOT EXISTS report_attestations (
                    cik TEXT NOT NULL, accession TEXT NOT NULL, sha TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (cik, accession, sha),
                    FOREIGN KEY (cik, accession, sha) REFERENCES report_versions(cik, accession, sha));
                CREATE TABLE IF NOT EXISTS revision_candidates (
                    cik TEXT NOT NULL, accession TEXT NOT NULL, sha TEXT NOT NULL,
                    payload TEXT NOT NULL, approved_review TEXT,
                    PRIMARY KEY (cik, accession, sha));
                CREATE TABLE IF NOT EXISTS report_heads (
                    cik TEXT NOT NULL, report_key TEXT NOT NULL, accession TEXT NOT NULL, sha TEXT NOT NULL,
                    PRIMARY KEY (cik, report_key),
                    FOREIGN KEY (cik, accession, sha) REFERENCES report_versions(cik, accession, sha));
            """)
            self.quarantine_legacy_amendments(db)
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
        if data['document']['form'].endswith('/A'):
            raise EvidenceError('amendment_requires_review')
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
        existing = db.execute('''SELECT COALESCE(a.payload,v.payload) FROM report_versions v
                                LEFT JOIN report_attestations a USING(cik,accession,sha)
                                WHERE v.cik=? AND v.accession=? AND v.sha=?''',
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
            rows = db.execute("""SELECT COALESCE(a.payload,v.payload) FROM report_heads h
                                 JOIN report_versions v USING(cik,accession,sha)
                                 LEFT JOIN report_attestations a USING(cik,accession,sha)
                                 WHERE h.cik=? ORDER BY v.report_end DESC, v.published_on DESC""", (cik,))
            return [self.report_record(json.loads(row[0])) for row in rows]

    @staticmethod
    def report_record(data):
        doc = data['document']
        status = ('needs_semantic_review' if data.get('schema_version') == 3
                  else doc.get('verification_status', 'financials_verified'))
        return {'accession': doc['accession'], 'report_end': doc['report_end'], 'form': doc['form'],
                'published_on': doc['published_on'], 'label': doc.get('label', doc['report_end']),
                'status': status, 'sha256': doc['original_sha256'], 'verified_at': doc.get('observed_at')}

    def read(self, cik=None, accession=None, sha=None):
        with self.connect() as db:
            if accession and sha:
                row = db.execute('''SELECT COALESCE(a.payload,v.payload) FROM report_versions v
                                    LEFT JOIN report_attestations a USING(cik,accession,sha)
                                    WHERE v.cik=? AND v.accession=? AND v.sha=?''', (cik, accession, sha)).fetchone()
            else:
                row = db.execute("""SELECT COALESCE(a.payload,v.payload) FROM report_heads h
                                    JOIN report_versions v USING(cik,accession,sha)
                                    LEFT JOIN report_attestations a USING(cik,accession,sha)
                                    WHERE (? IS NULL OR h.cik=?) AND (? IS NULL OR h.accession=?)
                                    ORDER BY CASE WHEN v.report_key LIKE 'foreign_report:%' THEN 1 ELSE 0 END,
                                      v.report_end DESC, v.published_on DESC LIMIT 1""",
                                 (cik, cik, accession, accession)).fetchone()
        return validate_dataset(json.loads(row[0])) if row else None

    def attest(self, data):
        """Attach new semantic verification to a known immutable original body."""
        validate_dataset(data)
        if data.get('schema_version') != 4 or not data['facts']:
            raise EvidenceError('full_semantic_attestation_required')
        doc, cik = data['document'], data['issuer']['cik']
        key = (cik, doc['accession'], doc['original_sha256'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            saved = db.execute('SELECT payload FROM report_versions WHERE cik=? AND accession=? AND sha=?', key).fetchone()
            if not saved:
                raise EvidenceError('attestation_original_missing')
            old = json.loads(saved[0])
            if old.get('schema_version') != 3 or old['document']['form'].endswith('/A'):
                raise EvidenceError('attestation_original_not_eligible')
            stable = ('accession', 'original_sha256', 'form', 'published_on', 'report_end',
                      'accounting_standard', 'scope', 'currency', 'original_url')
            if any(doc[k] != old['document'][k] for k in stable):
                raise EvidenceError('attestation_identity_changed')
            # Retain the old payload verbatim. The new attestation can narrow
            # coverage after re-checking the original, never mutate its bytes.
            content = json.dumps(data, ensure_ascii=False, sort_keys=True)
            existing = db.execute('SELECT payload FROM report_attestations WHERE cik=? AND accession=? AND sha=?', key).fetchone()
            if existing:
                if json.loads(existing[0])['facts'] != data['facts']:
                    raise EvidenceError('immutable_attestation_conflict')
                return 'unchanged'
            db.execute('INSERT INTO report_attestations VALUES(?,?,?,?)', (*key, content))
        return 'attested'

    def quarantine_legacy_amendments(self, db):
        rows = db.execute('''SELECT h.cik,h.report_key,h.accession,h.sha,v.payload,v.previous_accession,v.previous_sha
                             FROM report_heads h JOIN report_versions v USING(cik,accession,sha)''').fetchall()
        for cik, key, accession, sha, payload, previous, previous_sha in rows:
            data = json.loads(payload)
            if data.get('acquisition_mode') != 'sec_on_demand' or not data['document']['form'].endswith('/A'):
                continue
            approved = db.execute('''SELECT approved_review FROM revision_candidates
                                     WHERE cik=? AND accession=? AND sha=?''', (cik, accession, sha)).fetchone()
            if approved and approved[0]:
                continue
            db.execute('INSERT OR IGNORE INTO revision_candidates VALUES(?,?,?,?,NULL)', (cik, accession, sha, payload))
            while previous:
                row = db.execute('''SELECT payload,previous_accession,previous_sha FROM report_versions
                                    WHERE cik=? AND accession=? AND sha=?''', (cik, previous, previous_sha)).fetchone()
                if not row:
                    previous = None
                    break
                candidate = json.loads(row[0])
                if not candidate['document']['form'].endswith('/A'):
                    break
                db.execute('INSERT OR IGNORE INTO revision_candidates VALUES(?,?,?,?,NULL)', (cik, previous, previous_sha, row[0]))
                previous, previous_sha = row[1:]
            if previous:
                db.execute('UPDATE report_heads SET accession=?,sha=? WHERE cik=? AND report_key=?',
                           (previous, previous_sha, cik, key))
            else:
                db.execute('DELETE FROM report_heads WHERE cik=? AND report_key=?', (cik, key))

    @staticmethod
    def impact(before, after):
        def keyed(data):
            return {(f.get('segment', f['metric']) + ':' + f.get('slot', 'current' if f['period_end'] == data['document']['report_end'] else 'prior')): f
                    for f in data['facts']}
        old, new = keyed(before) if before else {}, keyed(after)
        fields = ('value', 'concept', 'period_start', 'period_end', 'unit', 'scale', 'currency', 'scope', 'semantic')
        missing = sorted(old.keys() - new.keys())
        added = sorted(new.keys() - old.keys())
        changed = sorted(key for key in old.keys() & new.keys()
                         if any(old[key].get(f) != new[key].get(f) for f in fields))
        proof = (*fields, 'source_url', 'anchor')
        def describe(fact):
            return {field: fact.get(field) for field in proof} if fact else None
        return {'missing': missing, 'added': added, 'changed': changed,
                'details': [{'slot': key, 'before': describe(old.get(key)), 'after': describe(new.get(key))}
                            for key in sorted(set(missing + added + changed))]}

    def stage_revision(self, data):
        validate_dataset(data)
        doc, cik = data['document'], data['issuer']['cik']
        if not doc['form'].endswith('/A'):
            raise EvidenceError('not_an_amendment')
        key = (cik, doc['accession'], doc['original_sha256'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = self.revision_baseline(db, cik, doc)
            new = json.dumps(data, ensure_ascii=False, sort_keys=True)
            existing = db.execute('SELECT payload,approved_review FROM revision_candidates WHERE cik=? AND accession=? AND sha=?', key).fetchone()
            if existing:
                candidate = json.loads(existing[0])
                if candidate.get('schema_version') == 3 and data.get('schema_version') == 4 and not existing[1]:
                    db.execute('UPDATE revision_candidates SET payload=? WHERE cik=? AND accession=? AND sha=?', (new, *key))
                elif candidate['facts'] != data['facts']:
                    raise EvidenceError('revision_candidate_conflict')
            else:
                db.execute('INSERT INTO revision_candidates VALUES(?,?,?,?,NULL)', (*key, new))
        return {'accession': doc['accession'], 'sha256': doc['original_sha256'],
                'baseline': None if not prior else self.report_record(prior), 'impact': self.impact(prior, data)}

    @staticmethod
    def revision_baseline(db, cik, doc):
        group = report_group(doc['form'])
        row = db.execute('''SELECT COALESCE(a.payload,v.payload) FROM report_heads h
                            JOIN report_versions v USING(cik,accession,sha)
                            LEFT JOIN report_attestations a USING(cik,accession,sha)
                            WHERE h.cik=? AND h.report_key=? AND h.accession<>?''',
                         (cik, f"{group}:{doc['report_end']}", doc['accession'])).fetchone()
        return json.loads(row[0]) if row else None

    def revision_review(self, cik, accession, sha):
        with self.connect() as db:
            row = db.execute('''SELECT payload,approved_review FROM revision_candidates
                                WHERE cik=? AND accession=? AND sha=?''', (cik, accession, sha)).fetchone()
            if not row:
                raise EvidenceError('pending_revision_not_found')
            data = json.loads(row[0])
            previous = self.revision_baseline(db, cik, data['document'])
            key = [previous['document']['accession'], previous['document']['original_sha256']] if previous else None
            return {'baseline': key, 'amendment_sha256': sha, 'impact': self.impact(previous, data),
                    'note': '', 'approval_recorded': bool(row[1])}

    def publish_revision(self, cik, accession, sha, review):
        """Promote only a reviewed, complete restatement of the active evidence."""
        if not isinstance(review.get('note'), str) or not review['note'].strip():
            raise EvidenceError('revision_review_note_required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT payload,approved_review FROM revision_candidates
                                WHERE cik=? AND accession=? AND sha=?''', (cik, accession, sha)).fetchone()
            if not row or row[1]:
                raise EvidenceError('pending_revision_not_found')
            data = validate_dataset(json.loads(row[0]))
            doc = data['document']
            old = self.revision_baseline(db, cik, doc)
            if not old or old.get('schema_version') == 3 or data.get('schema_version') != 4:
                raise EvidenceError('reviewed_baseline_and_amendment_required')
            parent = (old['document']['accession'], old['document']['original_sha256'])
            impact = self.impact(old, data)
            if impact['missing'] or not data['facts']:
                raise EvidenceError('partial_amendment_cannot_replace_baseline')
            if ([*parent] != review.get('baseline') or sha != review.get('amendment_sha256')
                    or impact != review.get('impact')):
                raise EvidenceError('amendment_review_outdated_or_incomplete')
            old_amendment = db.execute('SELECT payload FROM report_versions WHERE cik=? AND accession=? AND sha=?',
                                       (cik, accession, sha)).fetchone()
            if old_amendment:
                if json.loads(old_amendment[0]).get('schema_version') != 3:
                    raise EvidenceError('conflicting_amendment_archive')
                key = (cik, accession, sha)
                db.execute('INSERT INTO report_attestations VALUES(?,?,?,?)',
                           (*key, json.dumps(data, ensure_ascii=False, sort_keys=True)))
                db.execute('UPDATE report_heads SET accession=?,sha=? WHERE cik=? AND report_key=?',
                           (accession, sha, cik, f"{report_group(doc['form'])}:{doc['report_end']}"))
            else:
                self._put(db, data, parent)
            db.execute('UPDATE revision_candidates SET approved_review=? WHERE cik=? AND accession=? AND sha=?',
                       (json.dumps(review, ensure_ascii=False), cik, accession, sha))
        return 'published'
