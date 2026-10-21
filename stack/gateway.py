"""Fake order gateway.

Line protocol over TCP:
    PING                          -> PONG
    ORDER <BUY|SELL> <SYM> <QTY> <PX> -> ACK <id> | REJ <reason>
Orders are checked against risk_limits.yaml and persisted to Postgres (best effort).
/runtime/control/gateway_slow adds latency so the port check's response time trips.
"""
from __future__ import annotations

import itertools
import os
import socketserver
import threading
import time

import psycopg

from common import flag, load_config, setup_logging

log = setup_logging("gateway")
PORT = int(os.environ.get("GATEWAY_PORT", "9001"))
PG_DSN = os.environ.get("PG_DSN", "postgresql://preflight:preflight@postgres:5432/trading")
SLOW_MS = int(os.environ.get("GATEWAY_SLOW_MS", "400"))

LIMITS = load_config("risk_limits.yaml")
order_ids = itertools.count(1)


class OrderStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn = None
        self.lock = threading.Lock()

    def _connect(self):
        self.conn = psycopg.connect(self.dsn, connect_timeout=2, autocommit=True)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                   id BIGINT PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(),
                   side TEXT, symbol TEXT, qty INT, price NUMERIC)""")

    def save(self, oid, side, sym, qty, px) -> None:
        with self.lock:
            try:
                if self.conn is None or self.conn.closed:
                    self._connect()
                self.conn.execute("INSERT INTO orders (id, side, symbol, qty, price) VALUES (%s,%s,%s,%s,%s)"
                                  " ON CONFLICT (id) DO NOTHING", (oid, side, sym, qty, px))
            except psycopg.Error as e:
                self.conn = None
                log.error("failed to persist order %s: %s", oid, str(e).strip().splitlines()[0])


store = OrderStore(PG_DSN)


def handle_order(parts: list[str]) -> str:
    if len(parts) != 5:
        return "REJ usage: ORDER <BUY|SELL> <SYM> <QTY> <PX>"
    _, side, sym, qty_s, px_s = parts
    try:
        qty, px = int(qty_s), float(px_s)
    except ValueError:
        return "REJ bad qty/price"
    if side not in ("BUY", "SELL"):
        return "REJ side must be BUY or SELL"
    if qty > LIMITS.get("max_order_qty", 1000):
        log.warning("rejected %s %s x%d: above max_order_qty", side, sym, qty)
        return "REJ qty above limit"
    if qty * px > LIMITS.get("max_order_notional", 5_000_000):
        log.warning("rejected %s %s x%d: above max_order_notional", side, sym, qty)
        return "REJ notional above limit"
    oid = next(order_ids)
    store.save(oid, side, sym, qty, px)
    log.info("order %d %s %s x%d @ %.2f accepted", oid, side, sym, qty, px)
    return f"ACK {oid}"


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            parts = raw.decode(errors="replace").strip().split()
            if not parts:
                continue
            if flag("gateway_slow"):
                time.sleep(SLOW_MS / 1000)
            cmd = parts[0].upper()
            if cmd == "PING":
                reply = "PONG"
            elif cmd == "ORDER":
                reply = handle_order([p.upper() for p in parts])
            else:
                reply = f"ERR unknown command {cmd}"
            self.wfile.write((reply + "\n").encode())


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    log.info("gateway listening on tcp/%d, limits %s", PORT, LIMITS)
    with Server(("0.0.0.0", PORT), Handler) as srv:
        srv.serve_forever()
