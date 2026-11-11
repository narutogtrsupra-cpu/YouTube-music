"""Bounded YouTube workers with process-tree and temporary-file cleanup."""
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile

from media import MediaError

log = logging.getLogger(__name__)


class MediaJobs:
    def __init__(self, worker=None, timeout=120):
        self.worker = str(worker or Path(__file__).with_name('media_worker.py'))
        self.timeout = timeout
        # Limit resource use on small hosting plans.
        self.slot = asyncio.Semaphore(1)

    async def run(self, operation, query, *, direct=False, video=False, limit=5):
        try:
            return await asyncio.wait_for(
                self._run(operation, query, direct=direct, video=video, limit=limit),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            log.warning('YouTube %s timed out', operation)
            raise MediaError('YouTube took too long to respond. The request was stopped; try again or check the host console.') from None

    async def _run(self, operation, query, *, direct, video, limit):
        async with self.slot:
            directory = tempfile.mkdtemp(prefix='music-job-')
            proc = None
            keep = False
            try:
                env = os.environ.copy()
                env['TMPDIR'] = directory
                payload = json.dumps(dict(operation=operation, query=query, direct=direct,
                                          video=video, limit=limit)).encode()
                # The worker, Deno and FFmpeg share a process group; cancellation
                # must stop the whole tree before removing cookies and downloads.
                spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                    sys.executable, self.worker, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    env=env, start_new_session=True,
                ))
                try:
                    proc = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    proc = await spawn
                    raise
                log.info('YouTube %s started', operation)
                proc.stdin.write(payload)
                await proc.stdin.drain()
                proc.stdin.close()
                response = None
                while line := await proc.stdout.readline():
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError('invalid event')
                        stage = event.get('stage')
                        if stage in ('searching', 'extracting', 'downloading', 'preparing', 'challenge_failed', 'verification_required', 'access_denied', 'rate_limited'):
                            # Whitelisted labels only: never log URLs, cookies or provider messages.
                            log.info('YouTube stage: %s', stage)
                        elif isinstance(event.get('ok'), bool) and response is None:
                            response = event
                        else:
                            raise ValueError('invalid event')
                    except (ValueError, UnicodeError):
                        raise MediaError('Media worker returned an invalid response. Check the host console.') from None
                await proc.wait()
                if proc.returncode != 0:
                    log.warning('Media worker exited with status %s', proc.returncode)
                    raise MediaError('Media worker stopped unexpectedly. Check FadeHost console and memory usage.')
                if response is None:
                    raise MediaError('Media worker returned no result. Check the host console.')
                if not response['ok']:
                    raise MediaError(response.get('error') or 'YouTube request failed.')
                result = response.get('result')
                if operation == 'download':
                    if not isinstance(result, dict) or not isinstance(result.get('file_path'), str):
                        raise MediaError('Media worker did not return a downloaded file.')
                    path = Path(result['file_path']).resolve()
                    root = Path(directory).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        raise MediaError('Media worker returned an invalid file.')
                    result['directory'] = directory
                    keep = True
                elif not isinstance(result, list):
                    raise MediaError('Media worker returned invalid search results.')
                log.info('YouTube %s finished', operation)
                return result
            finally:
                if proc is not None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await proc.wait()
                if not keep:
                    shutil.rmtree(directory, ignore_errors=True)
