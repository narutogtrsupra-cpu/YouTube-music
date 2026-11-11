"""YouTube extraction with private cookie copies and shared JS runtime settings."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
import threading
from urllib.parse import urlparse, parse_qs


class MediaError(ValueError):
    pass


def youtube_url(query):
    parsed = urlparse(query)
    if parsed.scheme not in ('http', 'https'):
        return None
    host = (parsed.hostname or '').lower()
    if host == 'youtu.be':
        video_id = parsed.path.strip('/').split('/')[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        video_id = parse_qs(parsed.query).get('v', [''])[0]
        if not video_id and parsed.path.startswith(('/shorts/', '/embed/')):
            video_id = parsed.path.split('/')[2]
    else:
        raise MediaError('Please use a YouTube video link or a song name.')
    if len(video_id) != 11 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in video_id):
        raise MediaError('Please use a single YouTube video link.')
    return f'https://www.youtube.com/watch?v={video_id}'


class QuietLogger:
    # Never forward provider text: it can contain account and URL information.
    def __init__(self, stage=None):
        self.stage = stage or (lambda _: None)
        self.reported = set()

    def debug(self, message):
        pass

    def warning(self, message):
        text = str(message).lower()
        if 'challenge solving failed' in text or 'error solving' in text:
            category = 'challenge_failed'
        elif 'sign in to confirm' in text or 'confirm you’re not a bot' in text or 'confirm you are not a bot' in text:
            category = 'verification_required'
        elif 'http error 403' in text:
            category = 'access_denied'
        elif 'http error 429' in text:
            category = 'rate_limited'
        else:
            return
        if category not in self.reported:
            self.reported.add(category)
            self.stage(category)

    error = warning


class YouTube:
    def __init__(self, factory=None, stage=None):
        self.factory = factory
        self.stage = stage or (lambda _: None)
        self.lock = threading.RLock()
        self.cache = Path(tempfile.gettempdir()) / 'akhil-music-youtube-cache'

    @contextmanager
    def options(self):
        # yt-dlp can update a cookie jar. Use an isolated copy so concurrent
        # extraction cannot overwrite the host's secret or another request's jar.
        with self.lock, tempfile.TemporaryDirectory(prefix='music-auth-') as auth:
            opts = dict(quiet=True, no_warnings=True, noplaylist=True,
                        cachedir=str(self.cache), logger=QuietLogger(self.stage),
                        socket_timeout=25, retries=2, extractor_retries=2)
            runtime = os.getenv('YOUTUBE_JS_RUNTIME')
            if runtime:
                name, _, path = runtime.partition(':')
                if name not in ('node', 'deno', 'quickjs', 'bun'):
                    raise MediaError('YOUTUBE_JS_RUNTIME must name node, deno or quickjs.')
                opts['js_runtimes'] = {name: {'path': path} if path else {}}
            elif shutil.which('deno'):
                opts['js_runtimes'] = {'deno': {}}
            else:
                # FadeHost runs Python in a virtual environment. The pip-installed
                # Deno binary can be outside PATH when Python is started directly.
                try:
                    import deno
                    deno_path = deno.find_deno_bin()
                except (ImportError, FileNotFoundError, OSError):
                    deno_path = None
                if deno_path:
                    opts['js_runtimes'] = {'deno': {'path': deno_path}}
                elif shutil.which('node'):
                    opts['js_runtimes'] = {'node': {}}
            cookiefile = os.getenv('YOUTUBE_COOKIES_FILE')
            if cookiefile:
                try:
                    source = Path(cookiefile)
                    with source.open(encoding='utf-8') as stream:
                        header = stream.readline()
                    if not header.startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
                        raise MediaError('YouTube cookie file is not in Netscape format. Export it again; do not send the file in chat.')
                    private = Path(auth) / 'cookies.txt'
                    shutil.copyfile(source, private)
                    private.chmod(0o600)
                    opts['cookiefile'] = str(private)
                except FileNotFoundError:
                    raise MediaError('YouTube cookie file is missing. Check YOUTUBE_COOKIES_FILE matches the full path and filename in your host.') from None
                except PermissionError:
                    raise MediaError('YouTube cookie file is not readable by the bot. Check its file permissions on the host.') from None
                except UnicodeError:
                    raise MediaError('YouTube cookie file is not valid UTF-8 text. Export a Netscape cookie file again.') from None
                except OSError:
                    raise MediaError('Could not access the YouTube cookie file. Check the host file and permissions.') from None
            yield opts

    def ydl(self, options):
        if self.factory is not None:
            return self.factory(options)
        import yt_dlp
        return yt_dlp.YoutubeDL(options)

    @staticmethod
    def error(exc):
        reason = str(exc).lower()
        if 'sign in' in reason or 'not a bot' in reason or 'cookies' in reason:
            return MediaError('YouTube requires verification on this host. The bot owner must set YOUTUBE_COOKIES_FILE to a private Netscape cookie file and install the YouTube JS runtime. Do not send cookies in Telegram.')
        return MediaError('YouTube could not provide this track. Check the host JS runtime and current yt-dlp version, or try a different video.')

    def search(self, query, limit=5):
        try:
            self.stage('searching')
            with self.options() as opts:
                opts['extract_flat'] = True
                with self.ydl(opts) as ydl:
                    info = ydl.extract_info(f'ytsearch{limit}:{query}', download=False)
            results = []
            for entry in (info or {}).get('entries', []):
                if not entry:
                    continue
                try:
                    url = youtube_url('https://www.youtube.com/watch?v=' + entry.get('id', ''))
                except MediaError:
                    continue
                results.append(dict(title=entry.get('title') or 'Untitled', url=url,
                                    duration=int(entry.get('duration') or 0)))
            return results
        except MediaError:
            raise
        except Exception as exc:
            raise self.error(exc) from None

    @staticmethod
    def reject_live(info, *, incomplete=False):
        if info.get('is_live'):
            return 'Live streams are not supported. Select a recorded song or video.'
        return None

    def download(self, query, direct=False, video=False):
        directory = Path(tempfile.mkdtemp(prefix='music-'))
        try:
            link = youtube_url(query)
            if direct and not link:
                raise MediaError('Saved track needs a valid YouTube video link.')
            self.stage('extracting')
            seen_download = False
            def progress_hook(info):
                nonlocal seen_download
                if info.get('status') == 'downloading' and not seen_download:
                    seen_download = True
                    self.stage('downloading')
            with self.options() as opts:
                opts.update(outtmpl=str(directory / 'audio.%(ext)s'), writethumbnail=True,
                            match_filter=self.reject_live, progress_hooks=[progress_hook])
                if video:
                    opts.update(format='bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                                merge_output_format='mp4')
                else:
                    # Stream the original audio instead of transcoding to MP3.
                    opts.update(format='bestaudio[abr<=128]/bestaudio/best')
                with self.ydl(opts) as ydl:
                    info = ydl.extract_info(link or f'ytsearch1:{query}', download=True)
                    if info and 'entries' in info:
                        info = next((x for x in info['entries'] if x), None)
            if not info or info.get('is_live'):
                raise MediaError('Please select a recorded song or video, not a live stream.')
            if video:
                candidates = [p for p in directory.iterdir() if p.suffix.lower() in ('.mp4', '.webm', '.mkv', '.mov')]
            else:
                extensions = {'.m4a', '.webm', '.opus', '.ogg', '.mp3', '.aac', '.wav', '.flac', '.mp4'}
                candidates = [p for p in directory.glob('audio.*') if p.is_file() and p.suffix.lower() in extensions]
            if len(candidates) != 1:
                raise MediaError('The media download did not finish. Please try another video.')
            self.stage('preparing')
            thumbs = list(directory.glob('*.jpg')) + list(directory.glob('*.png'))
            return dict(file_path=str(candidates[0]), title=info.get('title') or query,
                        duration=int(info.get('duration') or 0), directory=str(directory), video=video,
                        source_url=youtube_url(info.get('webpage_url') or link or ''),
                        thumb=str(thumbs[0]) if thumbs else info.get('thumbnail'))
        except BaseException as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, (MediaError, KeyboardInterrupt, SystemExit)):
                raise
            raise self.error(exc) from None

    def clean(self):
        with self.lock:
            shutil.rmtree(self.cache, ignore_errors=True)
