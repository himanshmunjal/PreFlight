"""Fake market-data feed.

Publishes one JSON tick per second to every TCP subscriber and writes a heartbeat file
after each tick. When /runtime/control/feed_paused exists it stalls *silently*: the
process stays up and the port stays open, but no ticks flow. That is the failure only
a freshness check catches.
"""
from __future__ import annotations

import json
import os
import random
import socket
import threading
import time

from common import RUNTIME, flag, setup_logging

log = setup_logging("feed")
PORT = int(os.environ.get("FEED_PORT", "9000"))
HEARTBEAT = RUNTIME / "feed" / "heartbeat.json"
PRICES = {"RELIANCE": 2950.0, "TCS": 4120.0, "INFY": 1860.0, "HDFCBANK": 1655.0, "NIFTY": 24850.0}

clients: set[socket.socket] = set()
clients_lock = threading.Lock()


def accept_loop(server: socket.socket) -> None:
    while True:
        conn, addr = server.accept()
        conn.settimeout(0.5)  # a slow subscriber must not stall the publisher
        with clients_lock:
            clients.add(conn)
        log.info("subscriber connected from %s:%s (%d total)", addr[0], addr[1], len(clients))


def broadcast(line: bytes) -> None:
    with clients_lock:
        for conn in list(clients):
            try:
                conn.sendall(line)
            except OSError:
                clients.discard(conn)
                conn.close()


def write_heartbeat(seq: int, ts: float) -> None:
    tmp = HEARTBEAT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ts": ts, "seq": seq, "subscribers": len(clients)}))
    tmp.replace(HEARTBEAT)  # atomic: readers never see a half-written file


def main() -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PORT))
    server.listen(64)
    threading.Thread(target=accept_loop, args=(server,), daemon=True).start()
    log.info("feed publishing on tcp/%d", PORT)

    seq = 0
    next_tick = time.monotonic()
    while True:
        next_tick += 1.0
        if not flag("feed_paused"):
            seq += 1
            for sym in PRICES:
                PRICES[sym] = round(PRICES[sym] * (1 + random.gauss(0, 0.0005)), 2)
            ts = time.time()
            tick = {"seq": seq, "ts": ts, "quotes": PRICES}
            broadcast((json.dumps(tick) + "\n").encode())
            write_heartbeat(seq, ts)
            if seq % 60 == 0:
                log.info("published %d ticks, %d subscriber(s)", seq, len(clients))
        time.sleep(max(0.0, next_tick - time.monotonic()))


if __name__ == "__main__":
    main()
