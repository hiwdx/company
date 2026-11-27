"""Bounded, no-network worker for the automatic iXBRL extractor."""
import codecs
import hashlib
import json
from pathlib import Path
import resource
import struct
import subprocess
import sys

# An isolated interpreter starts with no working-directory import path.
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiwd_company.auto_facts import extract
from hiwd_company.domain import EvidenceError
from hiwd_company.sec import MAX_BODY


HEADER = struct.Struct('!III')
MAX_META = 65536
MAX_RESULT = 262144


def parse_in_worker(issuer, filing, html, facts, *, observed_at, companyfacts_sha256):
    metadata = json.dumps({'issuer': issuer, 'filing': filing, 'observed_at': observed_at,
                           'companyfacts_sha256': companyfacts_sha256}, ensure_ascii=False).encode()
    if len(metadata) > MAX_META or max(len(html), len(facts)) > MAX_BODY:
        raise EvidenceError('document_worker_input_limit')
    try:
        child = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve())],
                               input=HEADER.pack(len(metadata), len(html), len(facts)) + metadata + html + facts,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25,
                               env={'LANG': 'C.UTF-8'}, check=False)
    except subprocess.TimeoutExpired as exc:
        raise EvidenceError('document_worker_timeout') from exc
    if child.returncode or len(child.stdout) > MAX_RESULT:
        raise EvidenceError('document_worker_failed')
    data = json.loads(child.stdout)
    if not data.get('ok'):
        raise EvidenceError(data.get('reason', 'document_parse_rejected'))
    return data['payload']


def deny_io(event, _args):
    if event == 'open' or event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.system', 'ctypes.')):
        raise PermissionError('iXBRL worker filesystem and network access denied')


def worker():
    resource.setrlimit(resource.RLIMIT_CPU, (14, 14))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (640 * 1024 * 1024, 640 * 1024 * 1024))
    codecs.lookup('utf-8-sig')
    sys.addaudithook(deny_io)
    try:
        reader = sys.stdin.buffer
        metadata_size, html_size, facts_size = HEADER.unpack(reader.read(HEADER.size))
        if metadata_size > MAX_META or max(html_size, facts_size) > MAX_BODY:
            raise EvidenceError('document_worker_input_limit')
        metadata = json.loads(reader.read(metadata_size))
        html, facts = reader.read(html_size), reader.read(facts_size)
        if len(html) != html_size or len(facts) != facts_size:
            raise EvidenceError('document_worker_truncated_input')
        if hashlib.sha256(facts).hexdigest() != metadata['companyfacts_sha256']:
            raise EvidenceError('companyfacts_receipt_mismatch')
        payload = extract(metadata['issuer'], metadata['filing'], html, json.loads(facts),
                          observed_at=metadata['observed_at'], companyfacts_sha256=metadata['companyfacts_sha256'])
        print(json.dumps({'ok': True, 'payload': payload}, ensure_ascii=False))
    except EvidenceError as exc:
        print(json.dumps({'ok': False, 'reason': str(exc)}))
    except (ValueError, KeyError, TypeError, AttributeError, PermissionError, struct.error):
        print(json.dumps({'ok': False, 'reason': 'document_parse_rejected'}))


if __name__ == '__main__':
    worker()
