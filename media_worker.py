"""Isolated YouTube job. The parent owns the temporary directory and timeout."""
import json
import sys

from media import MediaError, YouTube


def report_stage(stage):
    if stage in ('searching', 'extracting', 'downloading', 'preparing', 'challenge_failed', 'verification_required', 'access_denied', 'rate_limited'):
        print(json.dumps({'stage': stage}), flush=True)


def main():
    try:
        request = json.load(sys.stdin)
        source = YouTube(stage=report_stage)
        if request['operation'] == 'search':
            result = source.search(request['query'], request.get('limit', 5))
        elif request['operation'] == 'download':
            result = source.download(request['query'], direct=request.get('direct', False),
                                     video=request.get('video', False))
        else:
            raise MediaError('Unsupported media request.')
        response = {'ok': True, 'result': result}
    except MediaError as exc:
        response = {'ok': False, 'error': str(exc)}
    except Exception:
        # Do not print provider output, cookie paths or environment variables.
        response = {'ok': False, 'error': 'Media processing failed. Check the host runtime and try again.'}
    print(json.dumps(response, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
