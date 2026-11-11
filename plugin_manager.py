"""Reload trusted local plugin handlers without duplicating registrations."""
import types
from pathlib import Path


class Plugins:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.handlers = []

    async def reload(self, bot):
        staged = []
        if self.directory.exists():
            for path in sorted(self.directory.glob('*.py')):
                if path.name.startswith('_'):
                    continue
                module = types.ModuleType('music_plugin_' + path.stem)
                module.__file__ = str(path)
                exec(compile(path.read_text(), str(path), 'exec'), module.__dict__)
                # Plugins declare HANDLERS = [(MessageHandler(...), group), ...].
                for handler, group in module.HANDLERS:
                    if not isinstance(group, int) or group < 1:
                        raise ValueError('Plugins must use handler groups >= 1.')
                    staged.append((handler, group))
        old = self.handlers
        added = []
        removed = []
        try:
            for handler, group in old:
                bot.remove_handler(handler, group)
                removed.append((handler, group))
            for handler, group in staged:
                bot.add_handler(handler, group)
                added.append((handler, group))
        except Exception:
            for handler, group in added:
                bot.remove_handler(handler, group)
            for handler, group in removed:
                bot.add_handler(handler, group)
            raise
        self.handlers = staged
        return len(staged)
