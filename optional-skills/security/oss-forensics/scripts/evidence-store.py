#!/usr/bin/env python3
"""
OSS Forensics Evidence Store Manager
Manages a JSON-based evidence store for forensic investigations.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

EVIDENCE_TYPES = [
    "git",
    "gh_api",
    "gh_archive",
    "web_archive",
    "ioc",
    "analysis",
    "manual",
    "vendor_report",
]

VERIFICATION_STATES = ["unverified", "single_source", "multi_source_verified"]

IOC_TYPES = [
    "COMMIT_SHA", "FILE_PATH", "API_KEY", "SECRET", "IP_ADDRESS",
    "DOMAIN", "PACKAGE_NAME", "ACTOR_USERNAME", "MALICIOUS_URL",
    "WORKFLOW_FILE", "BRANCH_NAME", "TAG_NAME", "RELEASE_NAME", "OTHER",
]


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds") + "Z"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class EvidenceStore:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data = {
            "metadata": {
                "version": "2.0",
                "created_at": _now_iso(),
                "last_updated": _now_iso(),
                "investigation": "",
                "target_repo": "",
            },
            "evidence": [],
            "chain_of_custody": [],
        }
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as handle:
                    self.data = json.load(handle)
            except (json.JSONDecodeError, IOError) as exc:
                print(f"Error loading evidence store '{filepath}': {exc}", file=sys.stderr)
                print("Hint: The file might be corrupted. Check for manual edits or syntax errors.", file=sys.stderr)
                sys.exit(1)

    def _save(self):
        self.data["metadata"]["last_updated"] = _now_iso()
        with open(self.filepath, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, ensure_ascii=False)

    def _next_id(self) -> str:
        return f"EV-{len(self.data['evidence']) + 1:04d}"

    def add(
        self,
        source: str,
        content: str,
        evidence_type: str,
        actor: str = None,
        url: str = None,
        timestamp: str = None,
        ioc_type: str = None,
        verification: str = "unverified",
        notes: str = None,
    ) -> str:
        evidence_id = self._next_id()
        entry = {
            "id": evidence_id,
            "type": evidence_type,
            "source": source,
            "content": content,
            "content_sha256": _sha256(content),
            "actor": actor,
            "url": url,
            "event_timestamp": timestamp,
            "collected_at": _now_iso(),
            "ioc_type": ioc_type,
            "verification": verification,
            "notes": notes,
        }
        self.data["evidence"].append(entry)
        self.data["chain_of_custody"].append({
            "action": "add",
            "evidence_id": evidence_id,
            "timestamp": _now_iso(),
            "source": source,
        })
        self._save()
        return evidence_id

    def list_evidence(self, filter_type: str = None, filter_actor: str = None):
        results = self.data["evidence"]
        if filter_type:
            results = [e for e in results if e.get("type") == filter_type]
        if filter_actor:
            results = [e for e in results if e.get("actor") == filter_actor]
        return results

    def verify_integrity(self):
        issues = []
        for entry in self.data["evidence"]:
            expected = _sha256(entry["content"])
            stored = entry.get("content_sha256", "")
            if expected != stored:
                issues.append({
                    "id": entry["id"],
                    "stored_sha256": stored,
                    "computed_sha256": expected,
                })
        return issues

    def query(self, keyword: str):
        keyword_lower = keyword.lower()
        return [
            e for e in self.data["evidence"]
            if keyword_lower in (e.get("content", "") or "").lower()
            or keyword_lower in (e.get("source", "") or "").lower()
            or keyword_lower in (e.get("actor", "") or "").lower()
            or keyword_lower in (e.get("url", "") or "").lower()
        ]

    def export_markdown(self) -> str:
        lines = [
            "# Evidence Registry",
            "",
            f"**Store**: `{self.filepath}`",
            f"**Last Updated**: {self.data['metadata'].get('last_updated', 'N/A')}",
            f"**Total Evidence Items**: {len(self.data['evidence'])}",
            "",
            "| ID | Type | Source | Actor | Verification | Event Timestamp | URL |",
            "|----|------|--------|-------|--------------|-----------------|-----|",
        ]
        for item in self.data["evidence"]:
            url = item.get("url") or ""
            url_display = f"[link]({url})" if url else ""
            lines.append(
                f"| {item['id']} | {item.get('type', '')} | {item.get('source', '')} "
                f"| {item.get('actor') or ''} | {item.get('verification', '')} "
                f"| {item.get('event_timestamp') or ''} | {url_display} |"
            )
        lines.extend([
            "",
            "## Chain of Custody",
            "",
            "| Evidence ID | Action | Timestamp | Source |",
            "|-------------|--------|-----------|--------|",
        ])
        for item in self.data["chain_of_custody"]:
            lines.append(
                f"| {item.get('evidence_id', '')} | {item.get('action', '')} "
                f"| {item.get('timestamp', '')} | {item.get('source', '')} |"
            )
        return "\n".join(lines)

    def summary(self) -> dict:
        by_type = {}
        by_verification = {}
        actors = set()
        for item in self.data["evidence"]:
            evidence_type = item.get("type", "unknown")
            by_type[evidence_type] = by_type.get(evidence_type, 0) + 1
            verification = item.get("verification", "unverified")
            by_verification[verification] = by_verification.get(verification, 0) + 1
            if item.get("actor"):
                actors.add(item["actor"])
        return {
            "total": len(self.data["evidence"]),
            "by_type": by_type,
            "by_verification": by_verification,
            "unique_actors": sorted(actors),
        }


def main():
    parser = argparse.ArgumentParser(
        description="OSS Forensics Evidence Store Manager v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--store", default="evidence.json", help="Path to evidence JSON file (default: evidence.json)")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    add_p = subparsers.add_parser("add", help="Add a new evidence entry")
    add_p.add_argument("--source", required=True)
    add_p.add_argument("--content", required=True)
    add_p.add_argument("--type", required=True, choices=EVIDENCE_TYPES, dest="evidence_type")
    add_p.add_argument("--actor")
    add_p.add_argument("--url")
    add_p.add_argument("--timestamp")
    add_p.add_argument("--ioc-type", choices=IOC_TYPES)
    add_p.add_argument("--verification", choices=VERIFICATION_STATES, default="unverified")
    add_p.add_argument("--notes")
    add_p.add_argument("--quiet", action="store_true")

    list_p = subparsers.add_parser("list", help="List all evidence entries")
    list_p.add_argument("--type", dest="filter_type", choices=EVIDENCE_TYPES)
    list_p.add_argument("--actor", dest="filter_actor")

    subparsers.add_parser("verify", help="Verify SHA-256 integrity of all evidence content")

    query_p = subparsers.add_parser("query", help="Search evidence by keyword")
    query_p.add_argument("keyword")

    subparsers.add_parser("export", help="Export evidence as a Markdown table (stdout)")
    subparsers.add_parser("summary", help="Print investigation statistics")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    store = EvidenceStore(args.store)
    if args.command == "add":
        evidence_id = store.add(
            source=args.source,
            content=args.content,
            evidence_type=args.evidence_type,
            actor=args.actor,
            url=args.url,
            timestamp=args.timestamp,
            ioc_type=args.ioc_type,
            verification=args.verification,
            notes=args.notes,
        )
        if not getattr(args, "quiet", False):
            print(f"✓ Added evidence: {evidence_id}")
    elif args.command == "list":
        items = store.list_evidence(filter_type=getattr(args, "filter_type", None), filter_actor=getattr(args, "filter_actor", None))
        if not items:
            print("No evidence found.")
        for item in items:
            actor_str = f" | actor: {item['actor']}" if item.get("actor") else ""
            url_str = f" | {item['url']}" if item.get("url") else ""
            print(f"[{item['id']}] {item['type']:12s} | {item['verification']:20s} | {item['source']}{actor_str}{url_str}")
    elif args.command == "verify":
        issues = store.verify_integrity()
        if not issues:
            print(f"✓ All {len(store.data['evidence'])} evidence entries passed SHA-256 integrity check.")
        else:
            print(f"✗ {len(issues)} integrity issue(s) detected:")
            for issue in issues:
                print(f"  [{issue['id']}] stored={issue['stored_sha256'][:16]}... computed={issue['computed_sha256'][:16]}...")
            sys.exit(1)
    elif args.command == "query":
        results = store.query(args.keyword)
        print(f"Found {len(results)} result(s) for '{args.keyword}':")
        for item in results:
            print(f"  [{item['id']}] {item['type']} | {item['source']} | {item['content'][:80]}")
    elif args.command == "export":
        print(store.export_markdown())
    elif args.command == "summary":
        summary = store.summary()
        print(f"Total evidence items : {summary['total']}")
        print(f"By type              : {json.dumps(summary['by_type'], indent=2)}")
        print(f"By verification      : {json.dumps(summary['by_verification'], indent=2)}")
        print(f"Unique actors        : {summary['unique_actors']}")


if __name__ == "__main__":
    main()
