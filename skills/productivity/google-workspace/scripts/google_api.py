#!/usr/bin/env python3
"""Google Workspace API CLI for Henio Agent.

Thin wrapper that delegates to gws via gws_bridge.py.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BRIDGE = Path(__file__).parent / "gws_bridge.py"
PYTHON = sys.executable


def gws(*args: str) -> None:
    result = subprocess.run(
        [PYTHON, str(BRIDGE), *list(args)],
        env={**os.environ, "HENIO_HOME": os.environ.get("HENIO_HOME", str(Path.home() / ".henio"))},
    )
    sys.exit(result.returncode)


# -- Gmail --
def gmail_search(args):
    gws("gmail", "+triage", "--query", args.query, "--max", str(args.max), "--format", "json")


def gmail_get(args):
    gws("gmail", "+read", "--id", args.message_id, "--headers", "--format", "json")


def gmail_send(args):
    cmd = ["gmail", "+send", "--to", args.to, "--subject", args.subject, "--body", args.body, "--format", "json"]
    if args.cc:
        cmd += ["--cc", args.cc]
    if args.html:
        cmd.append("--html")
    gws(*cmd)


def gmail_reply(args):
    gws("gmail", "+reply", "--message-id", args.message_id, "--body", args.body, "--format", "json")


def gmail_labels(args):
    gws("gmail", "users", "labels", "list", "--params", json.dumps({"userId": "me"}), "--format", "json")


def gmail_modify(args):
    body = {}
    if args.add_labels:
        body["addLabelIds"] = args.add_labels.split(",")
    if args.remove_labels:
        body["removeLabelIds"] = args.remove_labels.split(",")
    gws("gmail", "users", "messages", "modify", "--params", json.dumps({"userId": "me", "id": args.message_id}), "--json", json.dumps(body), "--format", "json")


# -- Calendar --
def calendar_list(args):
    if args.start or args.end:
        from datetime import datetime, timedelta, timezone as tz
        now = datetime.now(tz.utc)
        time_min = args.start or now.isoformat()
        time_max = args.end or (now + timedelta(days=7)).isoformat()
        gws(
            "calendar", "events", "list",
            "--params", json.dumps({
                "calendarId": args.calendar,
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": args.max,
                "singleEvents": True,
                "orderBy": "startTime",
            }),
            "--format", "json",
        )
    else:
        cmd = ["calendar", "+agenda", "--days", "7", "--format", "json"]
        if args.calendar != "primary":
            cmd += ["--calendar", args.calendar]
        gws(*cmd)


def calendar_create(args):
    cmd = ["calendar", "+insert", "--summary", args.summary, "--start", args.start, "--end", args.end, "--format", "json"]
    if args.location:
        cmd += ["--location", args.location]
    if args.description:
        cmd += ["--description", args.description]
    if args.attendees:
        for email in args.attendees.split(","):
            cmd += ["--attendee", email.strip()]
    if args.calendar != "primary":
        cmd += ["--calendar", args.calendar]
    gws(*cmd)


def calendar_delete(args):
    gws("calendar", "events", "delete", "--params", json.dumps({"calendarId": args.calendar, "eventId": args.event_id}), "--format", "json")


# -- Drive --
def drive_search(args):
    query = args.query if args.raw_query else f"fullText contains '{args.query}'"
    gws("drive", "files", "list", "--params", json.dumps({"q": query, "pageSize": args.max, "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}), "--format", "json")


# -- Contacts --
def contacts_list(args):
    gws("people", "people", "connections", "list", "--params", json.dumps({"resourceName": "people/me", "pageSize": args.max, "personFields": "names,emailAddresses,phoneNumbers"}), "--format", "json")


# -- Sheets --
def sheets_get(args):
    gws("sheets", "+read", "--spreadsheet", args.sheet_id, "--range", args.range, "--format", "json")


def sheets_update(args):
    values = json.loads(args.values)
    gws("sheets", "spreadsheets", "values", "update", "--params", json.dumps({"spreadsheetId": args.sheet_id, "range": args.range, "valueInputOption": "USER_ENTERED"}), "--json", json.dumps({"values": values}), "--format", "json")


def sheets_append(args):
    values = json.loads(args.values)
    gws("sheets", "+append", "--spreadsheet", args.sheet_id, "--json-values", json.dumps(values), "--format", "json")


# -- Docs --
def docs_get(args):
    gws("docs", "documents", "get", "--params", json.dumps({"documentId": args.doc_id}), "--format", "json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Workspace API for Henio Agent (gws backend)")
    sub = parser.add_subparsers(dest="service", required=True)

    gmail = sub.add_parser("gmail")
    gmail_sub = gmail.add_subparsers(dest="action", required=True)
    p = gmail_sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=10)
    p.set_defaults(func=gmail_search)
    p = gmail_sub.add_parser("get")
    p.add_argument("message_id")
    p.set_defaults(func=gmail_get)
    p = gmail_sub.add_parser("send")
    p.add_argument("--to", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--cc", default="")
    p.add_argument("--html", action="store_true")
    p.add_argument("--thread-id", default="")
    p.set_defaults(func=gmail_send)
    p = gmail_sub.add_parser("reply")
    p.add_argument("message_id")
    p.add_argument("--body", required=True)
    p.set_defaults(func=gmail_reply)
    p = gmail_sub.add_parser("labels")
    p.set_defaults(func=gmail_labels)
    p = gmail_sub.add_parser("modify")
    p.add_argument("message_id")
    p.add_argument("--add-labels", default="")
    p.add_argument("--remove-labels", default="")
    p.set_defaults(func=gmail_modify)

    cal = sub.add_parser("calendar")
    cal_sub = cal.add_subparsers(dest="action", required=True)
    p = cal_sub.add_parser("list")
    p.add_argument("--start", default="")
    p.add_argument("--end", default="")
    p.add_argument("--max", type=int, default=25)
    p.add_argument("--calendar", default="primary")
    p.set_defaults(func=calendar_list)
    p = cal_sub.add_parser("create")
    p.add_argument("--summary", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--location", default="")
    p.add_argument("--description", default="")
    p.add_argument("--attendees", default="")
    p.add_argument("--calendar", default="primary")
    p.set_defaults(func=calendar_create)
    p = cal_sub.add_parser("delete")
    p.add_argument("event_id")
    p.add_argument("--calendar", default="primary")
    p.set_defaults(func=calendar_delete)

    drv = sub.add_parser("drive")
    drv_sub = drv.add_subparsers(dest="action", required=True)
    p = drv_sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--raw-query", action="store_true")
    p.set_defaults(func=drive_search)

    con = sub.add_parser("contacts")
    con_sub = con.add_subparsers(dest="action", required=True)
    p = con_sub.add_parser("list")
    p.add_argument("--max", type=int, default=50)
    p.set_defaults(func=contacts_list)

    sh = sub.add_parser("sheets")
    sh_sub = sh.add_subparsers(dest="action", required=True)
    p = sh_sub.add_parser("get")
    p.add_argument("sheet_id")
    p.add_argument("range")
    p.set_defaults(func=sheets_get)
    p = sh_sub.add_parser("update")
    p.add_argument("sheet_id")
    p.add_argument("range")
    p.add_argument("--values", required=True)
    p.set_defaults(func=sheets_update)
    p = sh_sub.add_parser("append")
    p.add_argument("sheet_id")
    p.add_argument("range")
    p.add_argument("--values", required=True)
    p.set_defaults(func=sheets_append)

    docs = sub.add_parser("docs")
    docs_sub = docs.add_subparsers(dest="action", required=True)
    p = docs_sub.add_parser("get")
    p.add_argument("doc_id")
    p.set_defaults(func=docs_get)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
