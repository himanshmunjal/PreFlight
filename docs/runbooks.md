# PreFlight runbooks

Each alert links to the section for its failure. Steps assume the docker-compose demo stack.

## container-down

A stack container is not running (or is unhealthy / just restarted).

1. `docker ps -a --filter name=pf-` to see state and exit code.
2. `docker logs --tail 100 pf-<service>` for the crash reason.
3. Restart: `docker compose up -d <service>`.
4. Re-run: `docker exec pf-preflight python -m preflight run --only <service>_container`.

## gateway-slow

The gateway answered PING slower than the threshold, or answered wrong.

1. `./chaos.sh status` to check whether the `gateway_slow` chaos flag is set.
2. Look at `runtime/logs/gateway.log` for Postgres persistence errors (they hold a lock).
3. Check host CPU (`host_cpu` on the board).

## feed-stale

The feed's last tick is older than the threshold. The process can be up with the port
open and still be stale. This check exists for that case.

1. `cat runtime/feed/heartbeat.json`: compare `ts` with `date +%s`.
2. `./chaos.sh status` to check whether `feed_paused` is set.
3. Restart the feed: `docker compose restart feed`. The strategy resubscribes on its own.
4. **Do not trade on stale prices.** Keep strategies flat until `feed_ticks` is OK.

## disk-full

1. `docker exec pf-strategy du -sh /scratch/*` to find the largest files.
2. Remove what's safe (`./chaos.sh clean-disk` for the demo fill file).

## log-errors

New ERROR / FATAL / Traceback lines appeared since the last run.

1. The alert quotes the first match; see `runtime/logs/<service>.log` for context.
2. Errors from a dependency outage (feed, gateway, Redis) clear once that recovers.

## config-changed

A config file's SHA-256 no longer matches `config/manifest.json`.

1. `git diff stack/config/` to see what changed and who changed it.
2. Unintended: `git checkout stack/config/` (demo: `./chaos.sh restore-config`).
3. Intended and reviewed: `python -m preflight manifest` to record the new known-good hashes.
