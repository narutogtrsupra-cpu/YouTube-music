import os
import asyncio
import logging
import tempfile
import time
import secrets
import sys
import shutil
from pathlib import Path
from html import escape
from threading import Thread
from flask import Flask

# Automatically load static ffmpeg for pytgcalls
if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
    import static_ffmpeg
    static_ffmpeg.add_paths()

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from pytgcalls import PyTgCalls, filters as call_filters
from pytgcalls.types import MediaStream, StreamEnded, Device
from pyrogram.enums import ParseMode, ChatMemberStatus
from player import Player, timestamp, progress, discard
from storage import Storage
from media import YouTube, MediaError
from media_jobs import MediaJobs
from commands import COMMANDS, HELP
from plugin_manager import Plugins

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("musicbot")

# --- WEB SERVICE PORT BINDER (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# ---------------------------------------------

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
SESSION_STRING = os.environ["SESSION_STRING"]
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in the host environment.")

bot = Client("music_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
calls = PyTgCalls(user)

youtube = YouTube()
media_jobs = MediaJobs()
plugins = Plugins(Path(__file__).parent / 'plugins')
restart_event = asyncio.Event()
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))


def download_audio_track(query, direct=False, video=False):
    return youtube.download(query, direct=direct, video=video)


def get_control_markup(paused=False):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('↺ Replay', callback_data='cb_restart'),
         InlineKeyboardButton('▶ Resume' if paused else '⏸ Pause', callback_data='cb_toggle')],
        [InlineKeyboardButton('⏹ Stop', callback_data='cb_stop'),
         InlineKeyboardButton('⏭ Skip', callback_data='cb_skip')],
        [InlineKeyboardButton('🔀 Shuffle', callback_data='cb_shuffle'),
         InlineKeyboardButton('🔁 Loop queue', callback_data='cb_loop')],
        [InlineKeyboardButton('🗳 Vote to skip', callback_data='cb_vote')],
    ])


def caption(state):
    song = state.queue[0]
    return (
        f"{'⏸ PAUSED' if state.paused else '▶ NOW PLAYING'}\n\n"
        f"<b>{escape(song['title'][:180])}</b>\n"
        f"Requested by: {escape(song['user'][:100])}\n"
        f"{'Video' if song.get('video') else 'Audio'} · Volume: {state.volume}% · Queue loop: {'ON' if state.loop else 'OFF'}\n\n"
        f"{progress(state.position(), song['duration'])}\n"
        f"Up next: {len(state.queue) - 1} song(s)"
    )


async def announce(chat, state):
    kwargs = dict(reply_markup=get_control_markup(state.paused), parse_mode=ParseMode.HTML)
    if state.queue[0].get('thumb'):
        try:
            return await bot.send_photo(chat, photo=state.queue[0]['thumb'], caption=caption(state), **kwargs)
        except Exception:
            log.warning('Thumbnail unavailable; sending text card', exc_info=True)
    return await bot.send_message(chat, caption(state), **kwargs)


async def refresh(state):
    kwargs = dict(reply_markup=get_control_markup(state.paused), parse_mode=ParseMode.HTML)
    if state.card.photo:
        await state.card.edit_caption(caption(state), **kwargs)
    else:
        await state.card.edit_text(caption(state), **kwargs)


def make_stream(path, offset=0, video=False):
    return MediaStream(path, video_flags=MediaStream.Flags.REQUIRED if video else MediaStream.Flags.IGNORE,
                       ffmpeg_parameters=f'-ss {int(offset)}' if offset else None)


player = Player(calls, make_stream, announce, refresh)
store = Storage(os.environ.get('MUSIC_DB_PATH', 'music.sqlite3'))
searches = {}


def search_tracks(query):
    return youtube.search(query)


async def is_admin(chat, user_id):
    if not user_id:
        return False
    try:
        member = await bot.get_chat_member(chat, user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        log.warning('Could not check group administrator', exc_info=True)
        return False


async def may_control(chat, user_id):
    restricted, _ = store.settings(chat)
    return not restricted or (bool(user_id) and store.is_authorized(chat, user_id)) or await is_admin(chat, user_id)


def parse_seek(value):
    parts = value.split(':')
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise ValueError('Use /seek 1:30 or /seek 90.')
    if any(int(part) >= 60 for part in parts[1:]):
        raise ValueError('Minutes and seconds after a colon must be below 60.')
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds



async def chat_media_job(state, operation, query, **kwargs):
    task = asyncio.create_task(media_jobs.run(operation, query, **kwargs))
    state.pending_media.add(task)
    try:
        return await task
    except asyncio.CancelledError:
        # /stop and /clearqueue cancel the worker without cancelling the handler.
        if asyncio.current_task().cancelling():
            raise
        raise MediaError('Request cancelled by /stop or /clearqueue.') from None
    finally:
        state.pending_media.discard(task)


async def autoplay_track(chat, previous, recent):
    state = player.chats[chat]
    async with state.requests:
        if state.queue or not state.autoplay:
            return None
        try:
            results = await chat_media_job(state, 'search', previous['title'] + ' music', limit=10)
            # Use a different video, keeping a short history to avoid immediate repeats.
            last_error = None
            for candidate in results[:5]:
                if candidate['url'] in recent:
                    continue
                try:
                    track = await chat_media_job(state, 'download', candidate['url'], direct=True)
                    track['user'] = 'Autoplay'
                    return track
                except MediaError as exc:
                    if 'requires verification' in str(exc):
                        raise
                    last_error = exc
            if last_error:
                raise last_error
            await bot.send_message(chat, 'Autoplay found no new tracks. Request another song with /play.')
        except MediaError as exc:
            if state.autoplay:
                await bot.send_message(chat, 'Autoplay paused: ' + str(exc), parse_mode=ParseMode.DISABLED)
        return None


player.autofill = autoplay_track


@bot.on_message(filters.command(['settings', 'autoplay', 'auth', 'mode']) & filters.group)
async def group_settings_command(_, message):
    chat = message.chat.id
    action = message.command[0].lower()
    args = message.command[1:]
    uid = message.from_user.id if message.from_user else None
    if action == 'settings':
        restricted, votes = store.settings(chat)
        await message.reply_text(f"Controls: {'admins and authorized users' if restricted else 'everyone'}\nAutoplay preference: {'ON' if store.autoplay(chat) else 'OFF'}\nSkip votes required: {votes}\nYour Telegram user ID: {uid or 'unavailable'}\nUse /mode, /auth, /autoplay or /votethreshold to change settings.")
        return
    if action == 'autoplay':
        if not await may_control(chat, uid):
            await message.reply_text('Only group admins or authorized users can change autoplay in this mode.')
            return
        if args and (len(args) != 1 or args[0].lower() not in ('on', 'off')):
            await message.reply_text('Use /autoplay on or /autoplay off.')
            return
        enabled = args[0].lower() == 'on' if args else not store.autoplay(chat)
        store.set_autoplay(chat, enabled)
        state = player.chats[chat]
        async with state.lock:
            state.autoplay = enabled
            state.auto_epoch += 1
            if not enabled and not state.queue and state.auto_task and not state.auto_task.done():
                state.auto_task.cancel()
        await message.reply_text(f"Autoplay {'ON' if enabled else 'OFF'}." + (' Start with /play <song>.' if enabled and not state.queue else ''))
        return
    if not await is_admin(chat, uid):
        await message.reply_text('Only group admins can change control mode or authorize users.')
        return
    if action == 'mode':
        if len(args) != 1 or args[0].lower() not in ('everyone', 'admins'):
            await message.reply_text('Use /mode everyone or /mode admins.')
            return
        store.set_setting(chat, admins_only=args[0].lower() == 'admins')
        await message.reply_text('Control mode updated.')
        return
    remove = bool(args and args[0].lower() == 'remove')
    target_args = args[1:] if remove else args
    replied = message.reply_to_message
    target = replied.from_user.id if replied and replied.from_user else None
    if target_args:
        if len(target_args) != 1 or not target_args[0].isdigit():
            await message.reply_text('Reply to a user with /auth, or use /auth <user ID>. Revoke with /auth remove <user ID>.')
            return
        target = int(target_args[0])
    if not target:
        await message.reply_text('Reply to a user with /auth, or use /auth <user ID>.')
        return
    if not remove:
        try:
            member = await bot.get_chat_member(chat, target)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                raise ValueError('not a member')
        except Exception:
            await message.reply_text('Could not confirm that this user is in the group.')
            return
    store.authorize(chat, target, not remove)
    await message.reply_text('User authorization removed.' if remove else 'User authorized to use playback controls in this group.')


@bot.on_message(filters.command('speed'))
async def speed_command(_, message):
    started = time.monotonic()
    status = await message.reply_text('Checking Telegram response time…')
    await status.edit_text(f'Telegram response time: {(time.monotonic() - started) * 1000:.0f} ms')


@bot.on_message(filters.command(['clean', 'reload', 'reboot', 'restart']))
async def maintenance_command(_, message):
    if not OWNER_ID or not message.from_user or message.from_user.id != OWNER_ID:
        await message.reply_text('This command is for the bot owner. Set OWNER_ID on the host to enable maintenance commands.')
        return
    action = message.command[0].lower()
    if action == 'clean':
        await asyncio.to_thread(youtube.clean)
        await message.reply_text('YouTube extraction cache cleared. Active and queued media are kept.')
    elif action == 'reload':
        try:
            count = await plugins.reload(bot)
            await bot.set_bot_commands([BotCommand(name, description) for name, description in COMMANDS])
            await message.reply_text(f'Reloaded {count} local plugin handler(s) and refreshed the command menu.')
        except Exception:
            log.exception('Plugin reload failed')
            await message.reply_text('Plugin reload failed. Check the host logs. Existing handlers were preserved when registration failed.')
    else:
        await message.reply_text('Restarting the bot process. Active sessions and queues will end; saved settings and playlists are kept.')
        restart_event.set()


@calls.on_update(call_filters.stream_end(StreamEnded.Type.AUDIO, Device.MICROPHONE))
async def stream_end_handler(client, update):
    state = player.chats[update.chat_id]
    current = state.queue[0] if state.queue else None
    if current is not None:
        await player.advance(update.chat_id, natural=True, expected=current)


@bot.on_message(filters.command("start"))
async def start_command(_, message):
    welcome_caption = '🎵 NGS Music Bot\n\nPlay songs or videos with friends in your group voice chat. Tap Help for commands.'

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD ME IN YOUR GROUP ➕", url=f"https://t.me/{message._client.me.username}?startgroup=true")],
        [InlineKeyboardButton("🛠 HELP COMMANDS", callback_data="cb_help")],
        [
            InlineKeyboardButton("🌙 OWNER", url="https://t.me/NGSAKHIL"),
            InlineKeyboardButton("📢 UPDATES", url="https://t.me/chilkamut")
        ],
        [InlineKeyboardButton("💬 SUPPORT", url="https://t.me/chilkamut")],
        [InlineKeyboardButton("💻 SOURCE CODE", url="https://github.com/")]
    ])

    try:
        await message.reply_photo(
            photo="start_img.jpg", 
            caption=welcome_caption,
            reply_markup=keyboard
        )
    except Exception:
        await message.reply_text(
            text=welcome_caption,
            reply_markup=keyboard
        )

async def enqueue_item(chat, item, requester, generation, on_ready=None):
    state = player.chats[chat]
    track = None
    # A fresh manual request takes precedence over autoplay still downloading.
    async with state.lock:
        if not state.queue and state.auto_task and not state.auto_task.done():
            state.auto_epoch += 1
            state.auto_task.cancel()
    try:
        await asyncio.wait_for(state.requests.acquire(), timeout=120)
    except asyncio.TimeoutError:
        raise MediaError('Another request is still loading. Please try again shortly.') from None
    try:
        if generation != state.generation:
            return None
        try:
            if item['kind'] in ('audio', 'video'):
                directory = tempfile.mkdtemp(prefix='music-')
                track = {'directory': directory}
                try:
                    path = await asyncio.wait_for(bot.download_media(item['file_id'], file_name=f'{directory}/audio'), timeout=120)
                except asyncio.TimeoutError:
                    raise MediaError('Telegram audio/video download took too long. Please try again.') from None
                if not path:
                    raise ValueError('Audio download failed.')
                track.update(file_path=os.path.abspath(path), title=item['title'],
                             duration=item.get('duration', 0), thumb=None, audio_id=item['file_id'],
                             thumb_id=item.get('thumb_id'), video=item['kind'] == 'video')
                if item.get('thumb_id'):
                    try:
                        track['thumb'] = await asyncio.wait_for(bot.download_media(item['thumb_id'], file_name=f'{directory}/thumb.jpg'), timeout=15)
                    except Exception:
                        log.warning('Could not download thumbnail', exc_info=True)
            else:
                track = await chat_media_job(state, 'download', item['query'], direct=item['kind'] == 'url', video=item.get('video', False))
            track['user'] = requester
            if on_ready:
                try:
                    await asyncio.wait_for(on_ready(), timeout=10)
                except Exception:
                    log.warning('Could not update loading status')
            log.info('Media prepared; adding to queue or starting voice chat')
            position = await player.enqueue(chat, track, generation)
            track = None
            return position
        except BaseException:
            if track:
                discard(track)
            raise

    finally:
        state.requests.release()


def position_message(position):
    if position is None:
        return 'Request cancelled by /stop or /clearqueue.'
    if position == -1:
        return 'Could not start playback. Check that the voice chat is active and the assistant has joined.'
    return f'➕ Added to queue · position {position}' if position else 'Song started. Use /queue to see upcoming songs.'


@bot.on_message(filters.command(['song', 'play', 'vplay']) & filters.group)
async def song_command(_, message):
    video = message.command[0].lower() == 'vplay'
    replied = message.reply_to_message
    offline = (getattr(replied, 'video', None) if video else getattr(replied, 'audio', None)) if replied else None
    if len(message.command) < 2 and not offline:
        await message.reply_text('Use /song <name> or reply to an audio file with /play.')
        return
    chat = message.chat.id
    player.chats[chat].autoplay = store.autoplay(chat)
    generation = player.chats[chat].generation
    status = await message.reply_text('📥 Waiting for YouTube or Telegram download…')
    if offline:
        thumbs = getattr(offline, 'thumbs', None) or []
        item = dict(kind='video' if video else 'audio', file_id=offline.file_id,
                    title=getattr(offline, 'title', None) or offline.file_name or 'Media', duration=offline.duration or 0,
                    thumb_id=thumbs[-1].file_id if thumbs else None)
    else:
        item = dict(kind='query', query=' '.join(message.command[1:]), video=video)
    try:
        async def show_ready():
            await status.edit_text('🎧 Download complete. Adding to queue or starting voice chat…')
        result = await enqueue_item(chat, item, message.from_user.first_name if message.from_user else 'Admin', generation, on_ready=show_ready)
        await status.edit_text(position_message(result))
    except MediaError as exc:
        await status.edit_text(str(exc), parse_mode=ParseMode.DISABLED)
    except Exception:
        log.exception('Song request failed')
        await status.edit_text('Could not load song. Try another title or upload an audio file.')


@bot.on_message(filters.command('search') & filters.group)
async def search_command(_, message):
    if len(message.command) < 2 or not message.from_user:
        await message.reply_text('Use /search <song name>.')
        return
    status = await message.reply_text('🔎 Searching…')
    try:
        results = await media_jobs.run('search', ' '.join(message.command[1:]))
        if not results:
            await status.edit_text('No songs found. Try another search.')
            return
        now = time.monotonic()
        for key in list(searches):
            if searches[key]['expires'] <= now:
                del searches[key]
        token = secrets.token_urlsafe(8)
        player.chats[message.chat.id].autoplay = store.autoplay(message.chat.id)
        searches[token] = dict(chat=message.chat.id, user=message.from_user.id,
                               generation=player.chats[message.chat.id].generation,
                               expires=now + 300, results=results)
        buttons = [[InlineKeyboardButton(f"{i + 1}. {r['title'][:55]} ({timestamp(r['duration'])})",
                                         callback_data=f'search:{token}:{i}')]
                   for i, r in enumerate(results)]
        await status.edit_text('Choose a song (results expire in 5 minutes):', reply_markup=InlineKeyboardMarkup(buttons))
    except MediaError as exc:
        await status.edit_text(str(exc), parse_mode=ParseMode.DISABLED)
    except Exception:
        log.exception('Search failed')
        await status.edit_text('Search failed. Please try again.')


@bot.on_message(filters.command(['stop', 'end', 'pause', 'resume', 'skip', 'next', 'replay',
                                  'shuffle', 'loop', 'volume']) & filters.group)
async def control_command(_, message):
    action = message.command[0].lower()
    action = {'next': 'skip', 'end': 'stop', 'replay': 'restart'}.get(action, action)
    if not await may_control(message.chat.id, message.from_user.id if message.from_user else None):
        await message.reply_text('Only group admins can use playback controls in this group. Try /voteskip.')
        return
    volume = None
    if action == 'volume':
        if len(message.command) != 2 or not message.command[1].isdigit() or not 1 <= int(message.command[1]) <= 200:
            await message.reply_text('Usage: /volume <1-200>')
            return
        volume = int(message.command[1])
    try:
        await message.reply_text(await player.control(message.chat.id, action, volume))
    except Exception:
        log.exception('Control failed')
        await message.reply_text('Could not control playback. Check the voice chat.')


@bot.on_message(filters.command(['remove', 'clearqueue', 'seek']) & filters.group)
async def queue_control_command(_, message):
    chat = message.chat.id
    if not await may_control(chat, message.from_user.id if message.from_user else None):
        await message.reply_text('Only group admins can use this control.')
        return
    action = message.command[0].lower()
    try:
        if action == 'clearqueue':
            result = await player.clear_queue(chat)
        elif action == 'remove':
            if len(message.command) != 2 or not message.command[1].isdigit():
                raise ValueError('Use /remove <upcoming queue number>.')
            result = await player.remove(chat, int(message.command[1]))
        else:
            if len(message.command) != 2:
                raise ValueError('Use /seek 1:30 or /seek 90.')
            result = await player.seek(chat, parse_seek(message.command[1]))
        await message.reply_text(result)
    except ValueError as exc:
        await message.reply_text(str(exc))
    except Exception:
        log.exception('Queue control failed')
        await message.reply_text('Could not complete that action. Check the voice chat.')


@bot.on_message(filters.command('voteskip') & filters.group)
async def vote_command(_, message):
    if not message.from_user:
        await message.reply_text('A user account is needed to vote.')
        return
    _, threshold = store.settings(message.chat.id)
    await message.reply_text(await player.vote_skip(message.chat.id, message.from_user.id, threshold))


@bot.on_message(filters.command(['admincontrols', 'votethreshold']) & filters.group)
async def settings_command(_, message):
    chat = message.chat.id
    if not await is_admin(chat, message.from_user.id if message.from_user else None):
        await message.reply_text('Only a group admin can change these settings. Send the command from your user account.')
        return
    action = message.command[0].lower()
    if action == 'admincontrols':
        if len(message.command) != 2 or message.command[1].lower() not in ('on', 'off'):
            await message.reply_text('Use /admincontrols on or /admincontrols off.')
            return
        enabled = message.command[1].lower() == 'on'
        store.set_setting(chat, admins_only=enabled)
        await message.reply_text(f"Admin-only playback controls: {'ON' if enabled else 'OFF'}. Members can still request songs and use /voteskip.")
    else:
        if len(message.command) != 2 or not message.command[1].isdigit() or not 1 <= int(message.command[1]) <= 20:
            await message.reply_text('Use /votethreshold <1-20>.')
            return
        value = int(message.command[1])
        store.set_setting(chat, votes_required=value)
        # Start a fresh vote when the rule changes.
        state = player.chats[chat]
        async with state.lock:
            state.votes.clear()
        await message.reply_text(f'Skip voting now requires {value} distinct user(s).')


def saved_track(song):
    if song.get('audio_id'):
        return dict(kind='video' if song.get('video') else 'audio', file_id=song['audio_id'], title=song['title'],
                    duration=song['duration'], thumb_id=song.get('thumb_id'))
    if song.get('source_url'):
        return dict(kind='url', query=song['source_url'], title=song['title'], video=song.get('video', False))
    raise ValueError('This song has no reusable source. Search for it again or upload an audio file.')


@bot.on_message(filters.command('playlist') & filters.group)
async def playlist_command(_, message):
    chat = message.chat.id
    args = message.command[1:]
    help_text = ('/playlist list · /playlist show <name> · /playlist save <name> (current song) · '
                 '/playlist play <name> · /playlist remove <name> <number> · /playlist delete <name>')
    if not args:
        await message.reply_text(help_text)
        return
    action = args[0].lower()
    try:
        if action == 'list' and len(args) == 1:
            names = store.names(chat)
            await message.reply_text('Playlists:\n' + '\n'.join(f'{name}: {count} song(s)' for name, count in names[:80]) + (f'\n…and {len(names)-80} more' if len(names) > 80 else '') if names else 'No playlists yet. Use /playlist save <name>.', parse_mode=ParseMode.DISABLED)
        elif action == 'save' and len(args) == 2:
            state = player.chats[chat]
            async with state.lock:
                if not state.queue:
                    await message.reply_text('Play a song first, then use /playlist save <name>.')
                    return
                item = saved_track(state.queue[0])
                count = store.save(chat, args[1], item)
            await message.reply_text(f'Saved to {args[1]} ({count} song(s)).', parse_mode=ParseMode.DISABLED)
        elif action == 'show' and len(args) == 2:
            items = store.items(chat, args[1])
            lines = [f"{i}. {item.get('title', 'Audio')[:100]}" for i, item in enumerate(items[:30], 1)]
            if len(items) > 30:
                lines.append(f'…and {len(items) - 30} more')
            await message.reply_text(('Playlist ' + args[1] + ':\n' + '\n'.join(lines)) if lines else 'Playlist is empty or does not exist.', parse_mode=ParseMode.DISABLED)
        elif action == 'play' and len(args) == 2:
            items = store.items(chat, args[1])
            if not items:
                await message.reply_text('Playlist is empty or does not exist.')
                return
            player.chats[chat].autoplay = store.autoplay(chat)
            generation = player.chats[chat].generation
            status = await message.reply_text(f'Loading {len(items)} song(s) from playlist…')
            added = failed = 0
            for item in items:
                try:
                    result = await enqueue_item(chat, item, message.from_user.first_name if message.from_user else 'Admin', generation)
                    if result is None:
                        break
                    if result == -1:
                        failed += 1
                    else:
                        added += 1
                except Exception:
                    failed += 1
                    log.warning('Playlist item failed', exc_info=True)
            cancelled = generation != player.chats[chat].generation
            await status.edit_text(f'Playlist: {added} song(s) loaded, {failed} failed.' + (' Remaining requests cancelled.' if cancelled else ''))
        elif action == 'remove' and len(args) == 3 and args[2].isdigit():
            found = store.remove(chat, args[1], int(args[2]))
            await message.reply_text('Song removed from playlist.' if found else 'Song number not found.')
        elif action == 'delete' and len(args) == 2:
            found = store.delete(chat, args[1])
            await message.reply_text('Playlist deleted.' if found else 'Playlist not found.')
        else:
            await message.reply_text(help_text)
    except ValueError as exc:
        await message.reply_text(str(exc), parse_mode=ParseMode.DISABLED)
    except Exception:
        log.exception('Playlist action failed')
        await message.reply_text('Playlist action failed. Check the bot storage and try again.')


@bot.on_message(filters.command('queue') & filters.group)
async def queue_command(_, message):
    state = player.chats[message.chat.id]
    if not state.queue:
        await message.reply_text('The music queue is empty.')
        return
    lines = ['🎵 Music queue:']
    for index, song in enumerate(state.queue[:25]):
        label = 'Paused' if state.paused else 'Playing'
        lines.append(f"{label if index == 0 else index}: {song['title'][:100]} ({timestamp(song['duration'])})")
    if len(state.queue) > 25:
        lines.append(f'…and {len(state.queue) - 25} more')
    await message.reply_text('\n'.join(lines), parse_mode=ParseMode.DISABLED)


@bot.on_callback_query()
async def callback_handler(_, callback_query):
    if callback_query.data.startswith('search:'):
        try:
            _, token, raw_index = callback_query.data.split(':')
            result_set = searches.get(token)
            requester = callback_query.from_user
            if (not result_set or result_set['expires'] <= time.monotonic()
                    or result_set['chat'] != callback_query.message.chat.id):
                await callback_query.answer('Search expired. Please search again.', show_alert=True)
                return
            if not requester or requester.id != result_set['user']:
                await callback_query.answer('Only the person who searched can choose.', show_alert=True)
                return
            index = int(raw_index)
            if index < 0 or index >= len(result_set['results']):
                raise ValueError('Invalid result')
            result = result_set['results'][index]
            del searches[token]
            await callback_query.answer('Loading selected song…')
            try:
                await callback_query.message.edit_text('📥 Loading selected song…')
                position = await enqueue_item(result_set['chat'], dict(kind='url', query=result['url']),
                                              requester.first_name, result_set['generation'])
                await callback_query.message.edit_text(position_message(position))
            except MediaError as exc:
                await callback_query.message.edit_text(str(exc), parse_mode=ParseMode.DISABLED)
            except Exception:
                log.exception('Could not load search result')
                await callback_query.message.edit_text('Could not load this song. Try another result.')
        except (ValueError, IndexError):
            await callback_query.answer('Invalid search result.', show_alert=True)
        return
    if callback_query.data == 'cb_vote':
        if not callback_query.from_user:
            await callback_query.answer('A user account is needed to vote.', show_alert=True)
            return
        chat = callback_query.message.chat.id
        _, threshold = store.settings(chat)
        result = await player.vote_skip(chat, callback_query.from_user.id, threshold, callback_query.message.id)
        await callback_query.answer(result, show_alert=True)
        return
    if callback_query.data == 'cb_help':
        await callback_query.answer()
        await callback_query.message.reply_text(HELP, parse_mode=ParseMode.DISABLED)
        return
    action = callback_query.data.removeprefix('cb_')
    if action not in {'restart', 'toggle', 'stop', 'skip', 'shuffle', 'loop'}:
        await callback_query.answer('Use the controls on the latest song card.')
        return
    chat = callback_query.message.chat.id
    if not await may_control(chat, callback_query.from_user.id if callback_query.from_user else None):
        await callback_query.answer('Only group admins can use these controls. You can vote to skip.', show_alert=True)
        return
    try:
        result = await player.control(chat, action,
                                      card_id=callback_query.message.id)
        await callback_query.answer(result)
    except Exception:
        log.exception('Button action failed')
        await callback_query.answer('Action failed. Check the voice chat.', show_alert=True)


async def main():
    keep_alive()
    await bot.start()
    await user.start()
    await calls.start()
    await bot.set_bot_commands([BotCommand(name, description) for name, description in COMMANDS])
    await plugins.reload(bot)
    log.info('NGS-MUSIC-BOT started successfully')
    try:
        await restart_event.wait()
    finally:
        pending = [job for state in player.chats.values() for job in state.pending_media]
        for chat in list(player.chats):
            await player.control(chat, 'stop')
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await calls.stop()
        await user.stop()
        await bot.stop()


if __name__ == '__main__':
    bot.run(main())
    if restart_event.is_set():
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])
