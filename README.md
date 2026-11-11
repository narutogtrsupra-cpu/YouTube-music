<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:02d6cf0e0e9c833c6a256d540492487188bbbc2c43c6816b5007e1e08f4fbb02 -->

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:8c8bdfe9d4521ed5d52426a8f4d052b4c92f913db1cac9738182b4a8fbfeb627 -->

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:ad65057ca485fdfd319cc37cbfb5b4261bf7cf77fe3feca0c66152f49edccbc2 -->

# Telegram Voice-Chat Music Bot

YouTube audio and video in Telegram group voice chats, with a queue, continuous autoplay, playlists and controls. The slash-command menu is installed automatically when the bot starts.

## Deploy and update

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:e1cc824ee52fa88ab4b299b46bfc7431f011e0e4ed8efc93e8d671ce7316e474 -->

Upload every runtime file in the new ZIP to the repository root: `main.py`, `player.py`, `storage.py`, `media.py`, `media_jobs.py`, `media_worker.py`, `commands.py`, `plugin_manager.py`, `requirements.txt`, `Procfile`, and `start_img.jpg`. Tests are optional for deployment. Rebuild dependencies and start with `python main.py`. On FadeHost, files under `/data/app` can disappear during redeploy: store cookies in a private persistent location outside `/data/app` when possible, and check the configured file still exists after deployment.

<!-- /coderabbit-ai-generated:v1 -->

Host configuration:

- `API_ID`, `API_HASH`, `BOT_TOKEN` (or `TELEGRAM_BOT_TOKEN`), `SESSION_STRING`: existing Telegram credentials. Never commit or share them.
- `OWNER_ID`: your numeric Telegram user ID; maintenance commands are disabled until set. `/settings` shows your ID when sent from your user account.
- `MUSIC_DB_PATH`: optional SQLite file on a writable persistent disk, such as `/data/music.sqlite3`. Preserve this database to retain playlists, authorization and settings after redeploys.
<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:6417bba70f55104406bfc5ef0011738504b2624847fc6a04342d27c59ac270ef -->

- `YOUTUBE_JS_RUNTIME`: optional override, such as `node` or `node:/usr/bin/node`. `requirements.txt` installs Deno, and the bot automatically finds it in the Python environment even if its bin directory is missing from PATH. yt-dlp's EJS challenge solver is installed through `yt-dlp[default]`. If you previously set this override to an unavailable runtime, remove it so automatic detection works.

<!-- /coderabbit-ai-generated:v1 -->
- `YOUTUBE_COOKIES_FILE`: optional absolute path to a private Netscape-format YouTube cookie file on the host. See the YouTube section below.

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:7b9ebbdd797f6f9acc41f68f7e01cf9dc7fa01285def220091b69af59d3aad24 -->

The bot and assistant user must be in your Telegram group. Start a group voice chat before playback. The host must support py-tgcalls 3.0.0 native dependencies, FFmpeg, persistent workers and video processing. System FFmpeg/ffprobe are reused if available; static-ffmpeg supplies them otherwise. Stream only media you have permission to use.

## Low-memory hosts

The bot downloads an audio-only source at up to 128 kbps where available and plays it in its original format. This removes the extra MP3 conversion and reduces CPU, storage and bandwidth use. It keeps queue controls, replay, seeking and thumbnails. Video still needs more resources.

This does not guarantee operation in 256 MB. A local synthetic test of the bot imports, an audio decoder and a YouTube job peaked at about 523 MiB of sampled process PSS, mainly because of the YouTube JavaScript solver; actual host usage differs. The test had no connected Telegram clients and did not enforce a memory limit. YouTube may still challenge the host or time out. Playing an uploaded Telegram audio file with `/play` avoids YouTube extraction, but a real voice-chat test is still needed to establish whether it fits a given host.

FadeHost's console shows safe labels `YouTube stage: extracting`, `downloading` and `preparing`, plus `challenge_failed`, `verification_required`, `access_denied` or `rate_limited` when detected. These are fixed labels and do not include cookie contents, source URLs or provider messages. Use them to identify which step stalls; do not share your cookies, tokens or session strings.

<!-- /coderabbit-ai-generated:v1 -->

## Commands and examples

### Start and play

- `/start`: main menu and help, in private or group chat.
- `/play Believer` or `/song Believer`: start or queue YouTube audio.
- `/vplay Believer official video`: start or queue a YouTube video (up to 720p).
- `/play` replying to a Telegram audio file, or `/vplay` replying to a Telegram video: queue the upload.
- `/search Safar`: choose from up to five YouTube results. Only the requester can choose; results expire in five minutes. Search selections queue audio.

### Playback and queue

- `/pause`, `/resume`: pause or continue audio/video.
- `/skip` or `/next`: remove the current track and start the next.
- `/stop` or `/end`: clear the queue, stop autoplay for the current session, cancel pending requests and leave the call.
- `/replay`: play the current track from the beginning. The Replay button does the same.
- `/queue`: see the current track and numbered upcoming tracks.
- `/remove 2`: remove upcoming track number 2 from `/queue`.
- `/clearqueue`: remove upcoming tracks and cancel pending downloads while the current track continues.
- `/shuffle`: shuffle upcoming tracks.
- `/seek 1:30` or `/seek 90`: jump to a time before the end of the track; requires known duration. A paused track stays paused.
- `/loop`: toggle repeating the entire queue. Skip still removes a track. Loop takes precedence while the queue still has songs.
- `/volume 150`: choose a value from 1 to 200.

### Continuous autoplay

Send `/autoplay on`, then `/play Believer`. When the queue ends, the bot searches YouTube for another music track using the previous title and downloads it automatically. You do not need to keep requesting songs. It excludes the last 20 video URLs and tries up to five new candidates. This is search-based continuation, not YouTube account recommendations. Autoplay continues with audio even after a video.

`/autoplay off` disables continuation; `/autoplay` toggles the preference. Manually queued songs take priority over a pending autoplay result. `/stop` and `/end` stop the session without allowing an in-flight download to restart it. The saved autoplay preference applies the next time someone starts playback. If YouTube blocks extraction or no new result is available, the bot reports it and waits for another request rather than retrying forever.

### Settings and authorization

- `/settings`: display control mode, autoplay preference, required votes and your user ID.
- `/mode everyone`: everyone can use playback controls (default).
- `/mode admins`: only admins and explicitly authorized users can control playback.
- `/auth 123456789` or `/auth` replying to a user: allow that group member to use controls in restricted mode.
- `/auth remove 123456789` or `/auth remove` replying to a user: revoke that access.
- `/admincontrols on` and `/admincontrols off`: existing aliases for restricting or opening controls.
- `/voteskip`: one vote per user per track; two votes skip by default. The song card has a vote button.
- `/votethreshold 3`: set required votes from 1 to 20. Changing it clears current votes.

Only Telegram group administrators can change mode, authorize users or set the vote threshold. In restricted mode, members can still request songs, use playlists and vote. The autoplay toggle follows playback-control permissions. With open controls, users may also skip directly. Send admin commands from your user account if anonymous admin mode is enabled.

### Shared playlists

- `/playlist save favourites`: save the current audio or video source.
- `/playlist list`: show the group's playlists.
- `/playlist show favourites`: show its tracks and numbers.
- `/playlist play favourites`: download and queue saved tracks in order.
- `/playlist remove favourites 2`: remove song number 2 from the saved playlist.
- `/playlist delete favourites`: delete the playlist.

Playlists are shared within each group. Names contain up to 30 letters, numbers, underscores or hyphens. Each playlist holds up to 100 tracks. Sources can later become unavailable. Older SoundCloud playlist entries must be saved again from YouTube; online extraction now accepts YouTube sources only.

### Maintenance

- `/speed`: measure a Telegram message round trip in milliseconds; available to members.
- `/clean`: owner only; clear YouTube extraction cache. Current and queued media stay intact.
- `/reload`: owner only; reload trusted local plugin handlers and refresh the command menu.
- `/restart` or `/reboot`: owner only; stop active sessions and restart this Python bot process. Saved data is retained. These commands do not reboot the hosting provider's machine or deploy new code.

**Compatibility change:** `/restart` previously replayed a track. It now restarts the bot process as requested. Use `/replay` to repeat the current track. Restart/reboot is global and ends playback in every group.

## YouTube: sign in to confirm you are not a bot

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:d1aae2594d61b5a0758bc8237f291fe99a64269617ece1b3f73e10b490207eca -->

The bot now uses YouTube for search, audio, video and autoplay. It enables an installed JS runtime and supports private cookie files. A host's IP or account may still be challenged; there is no guaranteed code-only bypass. Media workers have a two-minute time limit, and voice-chat joining has a 45-second limit; on timeout the bot reports an error and cleans up the worker. The loading message changes when the download completes. A worker adds a Python process and can increase memory use; if the host kills or restarts the bot, an old loading message may remain, so check its console and memory usage. If the bot reports verification is required:

<!-- /coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:289eaa432dea8175b6f7fa01f7990c622ff43c948827e069d6f774f3e9164455 -->

1. Deploy the updated `requirements.txt` and `media.py`; the Python build installs yt-dlp, EJS and Deno. If an old `YOUTUBE_JS_RUNTIME` override points to a missing executable, remove it.

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:1080b419525018314a5f8e8420a9b173a0d6cbbf03be6abedda99266e084f194 -->

For FadeHost: deploy the updated files and let the Python build install `requirements.txt`. Its [Files tab](https://fadehost.com/docs/app-files/) shows files under `/data`, and [Settings → Environment variables](https://fadehost.com/docs/app-hosting/) sets the cookie path. Use the full path of the exact uploaded file, including every `.txt` in its filename. The app working directory is `/data/app`; a file uploaded next to repository files may be there, rather than directly under `/data`. Confirm the actual folder using the file breadcrumb or FadeHost support. Files in `/data/app` can disappear on redeploy; prefer a persistent location under `/data` outside `/data/app` when possible. Files can be accessed by team members with full app access and may be included in backups. Never commit cookies to the repository.

If the bot reports that the file is missing, check the full path and filename; if it reports an unreadable file, check its permissions. If it reports an invalid format, export Netscape cookies again. Never send a cookie file or its contents in a support message.

<!-- /coderabbit-ai-generated:v1 -->

<!-- /coderabbit-ai-generated:v1 -->
2. Follow yt-dlp's [YouTube cookie export instructions](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies) to export a Netscape cookie file from a browser you control. The [runtime/EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS) explains supported runtimes.
3. Upload the file through your host's private secret-file facility, for example `/etc/secrets/youtube-cookies.txt`. Set `YOUTUBE_COOKIES_FILE` to that path and restart the bot. Do not add the cookie file to GitHub or send it in Telegram/chat. The bot copies it privately for each operation and does not overwrite the original.
4. Retry `/play`. Cookies may expire or be rejected. Follow the provider's reported requirements; some restrictions may require a different host network or additional provider-supported configuration. Do not repeatedly retry a blocked account. Using account cookies with yt-dlp carries account restriction risk, as documented by yt-dlp.

## Optional local plugins

There are no additional plugins bundled by default. To add one, create a trusted Python file inside `plugins/` (without an `__init__.py`) that declares `HANDLERS = [(handler, group), ...]`, using Pyrogram handler objects and group numbers of 1 or higher. `/reload` compiles all files before changing registrations, replaces old handlers, and restores previous registrations if registration fails. Plugins execute as local Python code with the bot's permissions; install only your own trusted code. Updating the core Python files requires a process restart.

## Progress and verification

Cards show a thumbnail when available and an estimated progress display about every 10 seconds. If no thumbnail is usable, a text card is sent and playback continues. Queues, votes and playback position are in memory; persistent settings and playlists use SQLite. Temporary media is removed after playback, skip or stop.

Run `python -m unittest discover -s tests -v`. Automated tests mock Telegram. After deployment, verify commands, permissions, voice-chat audio/video, autoplay, cookie-file access and persistence in your real group. The older PDF guide describes the previous command set; this README is the current guide.


<!-- /coderabbit-ai-generated:v1 -->

<!-- /coderabbit-ai-generated:v1 -->

<!-- /coderabbit-ai-generated:v1 -->