"""Telegram slash-command descriptions and text help."""
COMMANDS = [
    ('start', '🚀 Sᴛᴀʀᴛ Bᴏᴛ / Mᴀɪɴ Mᴇɴᴜ'),
    ('play', '╍╍ Pʟᴀʏ Mᴜsɪᴄ ╍╍'), ('vplay', '╍╍ Pʟᴀʏ Vɪᴅᴇᴏ ╍╍'),
    ('pause', '⏸ Pᴀᴜsᴇ Sᴛʀᴇᴀᴍ'), ('resume', '▶️ Rᴇsᴜᴍᴇ Mᴜsɪᴄ'),
    ('skip', '⏭ Sᴋɪᴘ Tʀᴀᴄᴋ'), ('stop', '⏹ Sᴛᴏᴘ Pʟᴀʏɪɴɢ'),
    ('end', '🛑 Eɴᴅ Sᴇssɪᴏɴ'), ('replay', '🔄 Rᴇᴘʟᴀʏ Tʀᴀᴄᴋ'),
    ('queue', '📜 Vɪᴇᴡ Qᴜᴇᴜᴇ'), ('shuffle', '🔀 Sʜᴜғғʟᴇ Qᴜᴇᴜᴇ'),
    ('seek', '⏱ Sᴇᴇᴋ Tɪᴍᴇ'), ('loop', '🔁 Lᴏᴏᴘ Mᴏᴅᴇ'),
    ('settings', '⚙️ Bᴏᴛ Sᴇᴛᴛɪɴɢs'), ('autoplay', '✨ Aᴜᴛᴏᴘʟᴀʏ Tᴏɢɢʟᴇ'),
    ('auth', '🔐 Aᴜᴛʜᴏʀɪᴢᴇ Usᴇʀ'), ('mode', '🎛️ Cᴏɴᴛʀᴏʟ Mᴏᴅᴇ'),
    ('volume', '🔊 Sᴇᴛ Vᴏʟᴜᴍᴇ'), ('reboot', '🔄 Rᴇʙᴏᴏᴛ Bᴏᴛ'),
    ('reload', '♻️ Rᴇʟᴏᴀᴅ Pʟᴜɢɪɴs'), ('restart', '⚡ Rᴇsᴛᴀʀᴛ Sᴇʀᴠᴇʀ'),
    ('speed', '🚀 Cʜᴇᴄᴋ Pɪɴɢ'), ('clean', '🧹 Cʟᴇᴀʀ Cᴀᴄʜᴇ'),
    ('song', 'Play or queue a song'), ('search', 'Choose a YouTube result'),
    ('remove', 'Remove an upcoming song'), ('clearqueue', 'Clear upcoming songs'),
    ('voteskip', 'Vote to skip'), ('votethreshold', 'Set required votes (admin)'),
    ('playlist', 'Save and play group playlists'), ('admincontrols', 'Restrict controls (admin)'),
]
HELP = '''🎵 Music bot commands
/play <name> or /song <name> — YouTube audio
/vplay <name> — YouTube video
/play or /vplay replying to an audio/video upload
/search <name> — choose a result
/pause · /resume · /skip · /stop · /end
/replay — replay track (button also works)
/queue · /remove <number> · /clearqueue · /shuffle
/seek 1:30 · /loop · /volume <1-200>
/autoplay on|off — keep music playing after the queue ends
/settings — show group settings
/mode everyone|admins — choose who controls playback
/auth <user ID> or reply to their message — allow controls
/auth remove <user ID> — revoke authorization
/voteskip · /votethreshold <1-20>
/playlist — list playlist subcommands
/speed — Telegram round-trip time
Owner only: /clean · /reload · /restart · /reboot
/start — main menu

/restart and /reboot restart the bot process and end all active sessions. Use /replay to replay a song.'''
