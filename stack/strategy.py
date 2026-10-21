"""Fake strategy process.

Subscribes to the feed, runs a moving-average crossover, caches state in Redis and sends
orders to the gateway. It logs ERROR when its dependencies fail (feed silent, gateway
down, Redis down) and occasionally emits random WARN/ERROR lines, like real systems do.
/runtime/control/leak_fds makes it leak file descriptors until the flag is removed.
"""
from __future__ import annotations

import json
import os
import random
import socket
import time
from collections import deque

import redis

from common import flag, load_config, setup_logging

log = setup_logging("strategy")
FEED = (os.environ.get("FEED_HOST", "feed"), int(os.environ.get("FEED_PORT", "9000")))
GATEWAY = (os.environ.get("GATEWAY_HOST", "gateway"), int(os.environ.get("GATEWAY_PORT", "9001")))
RANDOM_WARN_RATE = float(os.environ.get("STRATEGY_RANDOM_WARN_RATE", "0.01"))
RANDOM_ERROR_RATE = float(os.environ.get("STRATEGY_RANDOM_ERROR_RATE", "0.001"))

CFG = load_config("strategy.yaml")
SYMBOL = CFG.get("symbol", "RELIANCE")
FAST, SLOW = int(CFG.get("fast_window", 5)), int(CFG.get("slow_window", 20))
QTY = int(CFG.get("order_qty", 10))
STALE_AFTER = float(CFG.get("stale_after_seconds", 5))

cache = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379,
                    socket_timeout=1, socket_connect_timeout=1)
leaked: list = []


def send_order(side: str, px: float) -> None:
    try:
        with socket.create_connection(GATEWAY, timeout=2) as s:
            s.sendall(f"ORDER {side} {SYMBOL} {QTY} {px:.2f}\n".encode())
            reply = s.makefile().readline().strip()
    except OSError as e:
        log.error("order send failed, gateway %s:%d unreachable: %s", *GATEWAY, e)
        return
    if reply.startswith("ACK"):
        log.info("order %s %s x%d @ %.2f -> %s", side, SYMBOL, QTY, px, reply)
    else:
        log.warning("order %s %s rejected: %s", side, SYMBOL, reply)


def on_tick(tick: dict, prices: deque, position: list) -> None:
    px = tick["quotes"][SYMBOL]
    prices.append(px)
    try:
        cache.hset("strategy:state", mapping={"last_px": px, "seq": tick["seq"], "position": position[0]})
    except redis.RedisError as e:
        log.error("redis unavailable, state not cached: %s", e)

    if len(prices) >= SLOW:
        fast = sum(list(prices)[-FAST:]) / FAST
        slow = sum(prices) / len(prices)
        want = 1 if fast > slow else -1
        if want != position[0]:
            position[0] = want
            send_order("BUY" if want > 0 else "SELL", px)

    if tick["seq"] % 10 == 0:
        log.info("seq=%d %s=%.2f position=%+d", tick["seq"], SYMBOL, px, position[0])
    if random.random() < RANDOM_WARN_RATE:
        log.warning("slippage above threshold on %s: %.1f bps", SYMBOL, random.uniform(3, 9))
    if random.random() < RANDOM_ERROR_RATE:
        log.error("risk check timed out for %s, order skipped", SYMBOL)

    if flag("leak_fds"):
        leaked.extend(open(os.devnull) for _ in range(25))
    elif leaked:
        log.info("closing %d leaked file handles", len(leaked))
        while leaked:
            leaked.pop().close()


def run_session() -> None:
    prices: deque = deque(maxlen=SLOW)
    position = [0]
    with socket.create_connection(FEED, timeout=STALE_AFTER) as s:
        log.info("subscribed to feed %s:%d", *FEED)
        reader = s.makefile("r")
        while True:
            try:
                line = reader.readline()
            except socket.timeout:
                # A socket file can't be read again after a timeout; resubscribe instead.
                log.error("no market data for %.0fs, feed may be stale; resubscribing", STALE_AFTER)
                return
            if not line:
                raise ConnectionError("feed closed the connection")
            on_tick(json.loads(line), prices, position)


def main() -> None:
    log.info("strategy starting: %s MA(%d/%d), qty %d", SYMBOL, FAST, SLOW, QTY)
    failures = 0
    while True:
        started = time.monotonic()
        try:
            run_session()
        except (OSError, ValueError, KeyError) as e:
            if time.monotonic() - started > 30:
                failures = 0  # the session had been healthy; this is a fresh outage
            failures += 1
            level = log.error if failures >= 3 else log.warning
            level("feed connection lost (%s), retry #%d", e, failures)
            time.sleep(min(10, 2 ** min(failures, 3)))


if __name__ == "__main__":
    main()
