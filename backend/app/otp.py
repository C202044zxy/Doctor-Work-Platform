"""T06 send reservation; authentication owns tickets, digests and consumption."""

from datetime import UTC, datetime

from fastapi import HTTPException
from redis.exceptions import WatchError


def reserve_send(cache, uid, daily_limit=20):
    cooldown = f"auth:send:cooldown:{uid}"
    daily = f"auth:send:daily:{uid}:{datetime.now(UTC).date()}"
    while True:
        try:
            with cache.pipeline() as pipe:
                pipe.watch(cooldown, daily)
                if pipe.exists(cooldown):
                    raise HTTPException(
                        429,
                        f"Please retry in {max(1, pipe.ttl(cooldown))} seconds",
                        headers={"Retry-After": str(max(1, pipe.ttl(cooldown)))},
                    )
                if int(pipe.get(daily) or 0) >= daily_limit:
                    raise HTTPException(
                        429, "Daily verification message limit reached; retry tomorrow"
                    )
                pipe.multi()
                pipe.set(cooldown, "1", ex=60)
                pipe.incr(daily)
                pipe.expire(daily, 86400)
                pipe.execute()
                return
        except WatchError:
            continue
