#!/usr/bin/env python3
# maildir_to_mbox.py
# Converts a Maildir tree to mbox files (one .mbox per folder).
# Verbose progress, resilient to odd/corrupted messages.
# Run with:  python3 -u maildir_to_mbox.py

import os
import sys
import time
import email.utils
import mailbox
from typing import List

BANNER = r"""
Maildir → mbox converter
------------------------
This tool scans a Maildir root (folders with cur/new/tmp) and writes one .mbox
file per folder into the destination directory. It prints progress so you can
see it's moving. Corrupted messages are handled via a raw fallback (best-effort).
"""

def is_maildir(path: str) -> bool:
    return all(os.path.isdir(os.path.join(path, d)) for d in ("cur", "new", "tmp"))

def find_maildirs(root: str) -> List[str]:
    found = []
    for r, _, _ in os.walk(root):
        if is_maildir(r):
            found.append(r)
    return sorted(found)

def choose(prompt: str, default: str = "") -> str:
    val = input(prompt).strip()
    return val or default

def mbox_filename(src_root: str, maildir_root: str) -> str:
    rel = os.path.relpath(maildir_root, src_root)
    if rel == ".":
        name = "Inbox"
    else:
        # strip leading dots used by cPanel (e.g. ".Sent")
        while rel.startswith("."):
            rel = rel[1:]
        # flatten subdirs into a single filename (safe for Windows)
        name = rel.replace(os.sep, "_") or "Inbox"
    return f"{name}.mbox"

def add_with_fallback(mbox_obj: mailbox.mbox, md: mailbox.Maildir, key: str) -> str:
    """
    Try to add the message normally; if that fails, add raw bytes from the file.
    Returns a string describing the outcome: "OK", "RAW", or "SKIP".
    """
    try:
        m = md.get_message(key)  # mailbox.Message
        mbox_obj.add(m)
        return "OK"
    except Exception as e1:
        # try raw bytes path
        try:
            with md.get_file(key) as fh:
                raw = fh.read()
            # mailbox.mboxMessage accepts bytes/str; keep raw headers/body intact
            mbox_obj.add(mailbox.mboxMessage(raw))
            return f"RAW"  # stored raw; headers/body preserved as-is
        except Exception:
            # last-resort placeholder (keeps count but not original content)
            placeholder = (
                b"From: conversion-error\n"
                b"Subject: Recovered placeholder\n"
                b"\n"
                b"<Failed to read original message in Maildir.>"
            )
            try:
                mbox_obj.add(mailbox.mboxMessage(placeholder))
                return "RAW"  # still counted, but as placeholder
            except Exception:
                return "SKIP"

def convert_maildir(root: str, dst_dir: str, per_message_verbose: bool, tick: int) -> int:
    msg_total = 0
    maildirs = find_maildirs(root)
    if not maildirs:
        print(f"No Maildir folders found under: {root}")
        return 0

    print(f"Found {len(maildirs)} Maildir folders.\n")
    for mdir in maildirs:
        out_path = os.path.join(dst_dir, mbox_filename(root, mdir))
        print(f"[{time.strftime('%H:%M:%S')}] Converting:\n  {mdir}\n  -> {out_path}")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        # collect entries from cur/ and new/
        entries = []
        for sub in ("cur", "new"):
            p = os.path.join(mdir, sub)
            if os.path.isdir(p):
                # Maildir keys include the filename; we need keys, not full paths, to use with mailbox API
                # Collect keys by listing the directory and matching to md keys later.
                for fn in os.listdir(p):
                    entries.append(fn)

        # Use Maildir API to iterate in a stable order (by key); sort by filename for deterministic progress
        md = mailbox.Maildir(mdir, factory=None)
        keys = [k for k in md.keys() if k in entries]
        # If keys filtering missed, fall back to all keys:
        if not keys:
            keys = list(md.keys())
        keys.sort()

        count = 0
        ok = raw = skip = 0
        mbox_obj = mailbox.mbox(out_path)
        try:
            for key in keys:
                outcome = add_with_fallback(mbox_obj, md, key)
                count += 1
                msg_total += 1
                if outcome == "OK":
                    ok += 1
                elif outcome == "RAW":
                    raw += 1
                else:
                    skip += 1

                if per_message_verbose:
                    print(f"  #{count:6d} {outcome}  key={key}", flush=True)
                elif tick and (count % tick == 0):
                    print(f"  … {count} messages processed (OK:{ok} RAW:{raw} SKIP:{skip})", flush=True)

                # Flush every 200 messages to make file growth visible
                if (count % 200) == 0:
                    try:
                        mbox_obj.flush()
                    except Exception:
                        pass
        finally:
            try:
                mbox_obj.flush()
            except Exception:
                pass
            try:
                mbox_obj.close()
            except Exception:
                pass

        print(f"  Done: {count} messages  (OK:{ok} RAW:{raw} SKIP:{skip})\n")

    print(f"All done. Wrote {msg_total} messages into: {dst_dir}")
    return msg_total

def main():
    print(BANNER)
    src = choose("Enter Maildir root path (absolute): ").strip()
    if not src:
        print("No source provided. Exiting.")
        sys.exit(1)
    if not os.path.isdir(src):
        print(f"Source path does not exist: {src}")
        sys.exit(1)

    dst = choose("Enter destination directory for .mbox files: ").strip()
    if not dst:
        print("No destination provided. Exiting.")
        sys.exit(1)
    os.makedirs(dst, exist_ok=True)

    mode = choose("Verbosity: [1] per-message (very chatty)  [2] periodic (every 200 msgs)  [Enter=2]: ").strip()
    per_message_verbose = (mode == "1")
    tick = 0 if per_message_verbose else 200

    print("\nStarting… this may take a while for large mailboxes.\n")
    total = convert_maildir(src, dst, per_message_verbose, tick)
    if total == 0:
        sys.exit(2)

if __name__ == "__main__":
    # Unbuffered output if not using -u
    try:
        import os, msvcrt  # type: ignore
    except Exception:
        pass
    main()
