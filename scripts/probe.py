#!/usr/bin/env python3
"""Bounded, read-only Phase 0 probes. No raw upstream payloads are persisted.

WeStock Markdown parsing here inspects transport/schema only; it is NOT a
production financial adapter. Never use its numeric output as verified facts.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit

SAMPLES = [
    ("US", "usAAPL", ["AAPL", "Apple", "苹果"]),
    ("US", "usTSM", ["TSM", "Taiwan Semiconductor", "台积电"]),
    ("HK", "hk00700", ["00700", "Tencent", "腾讯控股"]),
    ("HK", "hk09988", ["09988", "Alibaba", "阿里巴巴"]),
    ("CN", "sh600519", ["600519", "Kweichow Moutai", "贵州茅台"]),
    ("CN", "sh601398", ["601398", "ICBC", "工商银行"]),
]
SEC = {"AAPL": "0000320193", "TSM": "0001046179"}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tables(text):
    """Diagnostic inspection only; retains headers/identity, never amounts."""
    result, current = [], None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            current = None
            continue
        cells = [s.strip() for s in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r"[:\- ]+", s) for s in cells):
            continue
        if current is None:
            # A data row after an embedded newline is not a new header.
            if index + 1 >= len(lines) or not re.fullmatch(r'[|:\-\s]+', lines[index + 1]):
                continue
            current = {"columns": cells, "rows": []}
            result.append(current)
        elif len(cells) == len(current["columns"]):
            current["rows"].append(dict(zip(current["columns"], cells)))
    return result


def public_url(value):
    p = urlsplit(value)
    # Do not publish signed URLs, embedded credentials or private endpoints.
    allowed = {"file.finance.qq.com", "www.sec.gov", "data.sec.gov", "www.hkexnews.hk",
        "www1.hkexnews.hk", "www2.hkexnews.hk", "static.cninfo.com.cn"}
    if p.scheme in ("http", "https") and p.hostname in allowed and not p.username and not p.query and not p.fragment:
        return value
    return None


def inspect_cli(output, operation):
    parsed = tables(output)
    summary = {"tables": [{"columns": t["columns"], "row_count": len(t["rows"])} for t in parsed]}
    if operation == "search":
        summary["matches"] = [{k: r[k] for k in ("code", "name", "type") if k in r}
                              for t in parsed for r in t["rows"]][:30]
    elif operation == "finance":
        allowed = ("code", "EndDate", "ReportDate", "InfoPublDate", "CurrencyType", "DisclosureCurrency", "ReportType")
        summary["period_metadata"] = [dict((k, r[k]) for k in allowed if k in r)
                                      for t in parsed for r in t["rows"]][:24]
        summary["numeric_values_saved"] = False
    elif operation == "notice":
        summary["records"] = [{k: r[k] for k in ("id", "symbol", "time", "update_time") if k in r}
                              for t in parsed for r in t["rows"]][:12]
        summary["url_nonempty_count"] = sum(bool(r.get("url")) for t in parsed for r in t["rows"])
    elif operation == "detail":
        summary["public_urls"] = sorted(set(filter(None, (public_url(u.rstrip(').|'))
            for u in re.findall(r'https?://[^\s<>"\]]+', output)))))
        summary["text_returned"] = bool(output.strip())
    elif operation == "profile":
        summary["identities"] = [{"code": m.group(1), "name": m.group(2).strip()}
            for m in re.finditer(r'^\| ((?:us|hk|sh|sz|bj)[A-Za-z0-9.]+) \| ([^|\n]+) \|', output, re.M)]
        summary["multiline_rows_may_be_unparsed"] = True
    # Status must not confuse a successful process with successful data.
    summary["has_rows"] = any(t["rows"] for t in parsed)
    summary["has_error_marker"] = bool(re.search(r'(?i)\b(?:unauthorized|forbidden|timeout|error|NOT_DISCLOSED)\b|未授权|失败[:：]\s*[1-9]|错误[:：]|无数据|暂无', output))
    return summary


def westock(binary, stage="all"):
    if not Path(binary).is_file():
        raise ValueError("CLI must be a previously reviewed local binary")
    results, halted = [], False
    def run(args, operation):
        nonlocal halted
        if halted:
            item = {"at": now(), "command": ["westock"] + args, "status": "skipped_after_auth_or_rate_limit"}
            results.append(item)
            return item
        stamp, start = now(), time.monotonic()
        try:
            proc = subprocess.run([binary] + args, capture_output=True, timeout=45)
            out = proc.stdout.decode("utf-8", "replace")
            transport_text = out + "\n" + proc.stderr.decode("utf-8", "replace")
            halted = bool(re.search(r'(?i)\b(?:unauthorized|forbidden|AUTH_REQUIRED|RATE_LIMITED)\b|'
                r'HTTP\s*(?:401|403|429)\b|too many requests|未授权|需要登录|请先登录|频率限制|超过.*额度|限流', transport_text))
            item = {"at": stamp, "command": ["westock"] + args,
                    "exit_code": proc.returncode, "stdout_sha256": digest(proc.stdout),
                    "stderr_sha256": digest(proc.stderr), "stdout_bytes": len(proc.stdout),
                    "summary": inspect_cli(out, operation), "stop_after_denial": halted}
            if operation == "version":
                item["version"] = out.strip()
            # Do not print/store login URLs, tokens or unreviewed stderr bodies.
        except subprocess.TimeoutExpired:
            item = {"at": stamp, "command": ["westock"] + args, "status": "timeout"}
        item["elapsed_ms"] = round((time.monotonic() - start) * 1000)
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
        time.sleep(1.1)  # research throttle, NOT a claimed vendor quota
        return item
    run(["--version"], "version")
    for _, _, queries in SAMPLES if stage == "all" else []:
        for query in queries:
            run(["search", query], "search")
    for market in ("US", "HK", "CN"):
        codes = ",".join(s[1] for s in SAMPLES if s[0] == market)
        run(["profile", codes], "profile")
        run(["finance", codes, "--limit", "4"], "finance")
        listing = run(["notice", "list", codes, "--type", "1", "--limit", "2"], "notice")
        # One financial document per issuer is enough for a bounded link probe.
        records = listing.get("summary", {}).get("records", [])
        seen = set()
        for row in records:
            notice_id = row.get("id")
            if row.get("symbol") in seen:
                continue
            seen.add(row.get("symbol"))
            if notice_id and re.fullmatch(r'no[uskt][A-Za-z0-9_-]+', notice_id):
                run(["notice", "detail", notice_id], "detail")
        if stage == "followup":
            run(["notice", "list", codes, "--limit", "2"], "notice")
    return {"provider": "WeStock", "binary_sha256": digest(Path(binary).read_bytes()), "results": results}


def fetch(url, ua):
    allowed = {"data.sec.gov", "www.sec.gov"}
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in allowed or p.username or p.query:
        raise ValueError("SEC exact-host HTTPS URLs only")
    # No redirects, cookies, proxies supplied by callers, retries or UA rotation.
    start = time.monotonic()
    proc = subprocess.run(["curl", "--silent", "--show-error", "--max-time", "40",
        "--max-filesize", "16777216", "--proto", "=https", "--user-agent", ua,
        "--write-out", "\n__PROBE__%{http_code}|%{content_type}", url], capture_output=True, timeout=45)
    body, sep, meta = proc.stdout.rpartition(b"\n__PROBE__")
    status, _, content_type = meta.decode("utf-8", "replace").partition("|")
    result = {"at": now(), "url": url, "curl_exit": proc.returncode,
        "http_status": int(status) if status.isdigit() else None,
        "content_type": content_type, "bytes": len(body), "sha256": digest(body),
        "elapsed_ms": round((time.monotonic() - start) * 1000)}
    time.sleep(1.1)
    return result, body


def sec(ua):
    if not ua or "\n" in ua or "\r" in ua or len(ua) > 300:
        raise ValueError("Provide SEC_USER_AGENT with truthful project and contact")
    results, archive_blocked = [], False
    result, body = fetch("https://www.sec.gov/files/company_tickers.json", ua)
    if result["http_status"] == 200:
        try:
            data = json.loads(body)
            result["identity_matches"] = [r for r in data.values() if r.get("ticker") in SEC]
        except (ValueError, AttributeError):
            result["parse_status"] = "invalid_json_or_schema"
    elif result["http_status"] in (401, 403, 429):
        archive_blocked = True
    results.append(result)
    data_blocked = False
    for ticker, cik in SEC.items():
        if data_blocked:
            results.append({"ticker": ticker, "status": "skipped_after_host_denial"})
            continue
        result, body = fetch("https://data.sec.gov/submissions/CIK" + cik + ".json", ua)
        result["ticker"] = ticker
        if result["http_status"] != 200:
            data_blocked = result["http_status"] in (401, 403, 429)
            results.append(result)
            continue
        try:
            data = json.loads(body)
            result["identity"] = {k: data.get(k) for k in ("cik", "name", "tickers", "exchanges", "fiscalYearEnd")}
            recent = data["filings"]["recent"]
            filings = []
            for i, form in enumerate(recent["form"]):
                if form not in ("10-K", "10-Q", "8-K", "20-F", "6-K", "10-K/A", "20-F/A"):
                    continue
                row = {k: recent[k][i] for k in ("accessionNumber", "form", "filingDate", "reportDate", "acceptanceDateTime", "primaryDocument") if k in recent}
                row["url"] = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}".format(int(cik), row["accessionNumber"].replace("-", ""), row["primaryDocument"])
                filings.append(row)
                if len(filings) == 12:
                    break
            result["filings"] = filings
            result["history_files"] = data["filings"].get("files", [])
        except (ValueError, KeyError, TypeError):
            result["parse_status"] = "invalid_json_or_schema"
            filings = []
        results.append(result)
        if filings and not archive_blocked:
            annual = next((f for f in filings if f["form"] in ("10-K", "20-F")), filings[0])
            original, _ = fetch(annual["url"], ua)
            original["check"] = "original_document"
            results.append(original)
            archive_blocked = original["http_status"] in (401, 403, 429)
        fact, raw = fetch("https://data.sec.gov/api/xbrl/companyfacts/CIK" + cik + ".json", ua)
        fact["ticker"] = ticker
        if fact["http_status"] == 200:
            try:
                data = json.loads(raw)
                fact["taxonomies"] = list(data["facts"])
                fact["concept_samples"] = []
                for taxonomy, concepts in data["facts"].items():
                    for name in ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "Revenue", "NetIncomeLoss", "ProfitLoss"):
                        if name not in concepts:
                            continue
                        units = concepts[name]["units"]
                        fact["concept_samples"].append({"taxonomy": taxonomy, "concept": name,
                            "units": list(units), "contexts": [{k: r[k] for k in ("start", "end", "val", "accn", "form", "filed", "fy", "fp", "frame") if k in r}
                            for values in units.values() for r in values[-2:]]})
            except (ValueError, KeyError, TypeError):
                fact["parse_status"] = "invalid_json_or_schema"
        data_blocked = fact["http_status"] in (401, 403, 429)
        results.append(fact)
    for r in results:
        print(json.dumps(r, ensure_ascii=False), flush=True)
    return {"provider": "SEC", "user_agent": ua, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=["sec", "westock"])
    parser.add_argument("--binary")
    parser.add_argument("--stage", choices=["all", "followup"], default="all")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    dest = Path(args.output)
    if dest.exists():
        raise ValueError("Do not overwrite an evidence run; use a new filename")
    if args.provider == "westock" and not args.binary:
        parser.error("--binary is required for westock")
    started = now()
    data = sec(os.environ.get("SEC_USER_AGENT")) if args.provider == "sec" else westock(str(Path(args.binary).resolve()), args.stage)
    data.update({"started_at": started, "finished_at": now(), "probe_revision": 2, "stage": args.stage,
        "scope": "single execution environment; no regional SLA claim"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
