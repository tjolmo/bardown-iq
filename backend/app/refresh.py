import asyncio
import datetime

# One pipeline at a time: startup, nightly and manual refreshes all write the same tables
_lock = asyncio.Lock()
_status: dict = {"running": None, "last_run": None}
_task: asyncio.Task | None = None

def is_running() -> bool:
    return _lock.locked()

def get_status() -> dict:
    return {**_status, "is_running": is_running()}

async def run_exclusive(name: str, pipeline) -> bool:
    """Runs `pipeline` unless another pipeline is already running. Returns False if it was skipped."""
    if _lock.locked():
        print(f"Skipping '{name}': '{_status['running']['name']}' is still running")
        return False
    async with _lock:
        started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _status["running"] = {"name": name, "started_at": started}
        error = None
        try:
            await pipeline()
        except Exception as e:
            error = repr(e)
            print(f"Pipeline '{name}' failed: {error}")
        finally:
            _status["running"] = None
            _status["last_run"] = {
                "name": name,
                "started_at": started,
                "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "error": error,
            }
    return True

async def run_when_free(name: str, pipeline, max_wait: datetime.timedelta = datetime.timedelta(hours=2),
                        poll_seconds: float = 60) -> bool:
    """Runs `pipeline` once no other pipeline holds the lock, waiting up to `max_wait`: a scheduled daily run that
    lands on a startup refresh, a long training run or a manual refresh is delayed instead of lost. Returns False if
    it never got the lock."""
    deadline = asyncio.get_running_loop().time() + max_wait.total_seconds()
    if _lock.locked():
        print(f"'{name}' waiting for '{(_status['running'] or {}).get('name')}' to finish")
    while _lock.locked():
        if asyncio.get_running_loop().time() >= deadline:
            print(f"Skipping '{name}': the pipeline lock was busy for {max_wait}")
            return False
        await asyncio.sleep(poll_seconds)
    # no await between the check above and run_exclusive taking the lock, so nothing can slip in between
    return await run_exclusive(name, pipeline)

def start_in_background(name: str, pipeline) -> bool:
    """Starts `pipeline` as a background task. Returns False if a pipeline is already running."""
    global _task
    if _lock.locked() or (_task is not None and not _task.done()):
        return False
    # keep a reference so the task isn't garbage collected, and so it can be cancelled on shutdown
    _task = asyncio.create_task(run_exclusive(name, pipeline))
    return True

def cancel_background():
    if _task is not None:
        _task.cancel()
