import os

from app.config import log_file_path

log_line_count = 0
last_processed_log_line_count = 0


class LogEntry:
    def __init__(self):
        self.arena_ids = None
        self.actions_dict = None
        self.file_handle = None

        if self.file_handle is None and log_file_path.exists():
            self.file_handle = open(log_file_path, 'rb')
            self.file_handle.seek(0, os.SEEK_END)

        if self.file_handle:
            self.file_handle.seek(-2, os.SEEK_END)
            while self.file_handle.read(1) != b'\n':
                if self.file_handle.tell() == 1:
                    self.file_handle.seek(0)
                    break
                self.file_handle.seek(-2, os.SEEK_CUR)

    def parse_cards_log_line(self, log_line):
        try:
            log_segments = log_line.split("::")
            if len(log_segments) < 3:
                return []

            cards_section = log_segments[2].split(": ")
            if len(cards_section) < 2:
                return []

            if "cards" in log_line:
                arena_ids_str = cards_section[1].strip("[]")
                self.arena_ids = [id.strip() for id in arena_ids_str.split(", ") if id.strip()]
                return self.arena_ids

        except (IndexError, AttributeError):
            return []

    def parse_actions_log_line(self, log_line):
        import jsonpickle
        try:
            log_segments = log_line.split("::")
            if len(log_segments) < 3:
                return []
            actions_section = log_segments[2]
            if "actions" in log_line:
                actions_str = actions_section.split("actions: ")[1]
                self.actions_dict = jsonpickle.decode(actions_str)
                return self.actions_dict
        except (IndexError, AttributeError):
            return []


async def get_last_log_line() -> str | None:
    global log_line_count
    try:
        if not log_file_path.exists():
            return None

        with open(log_file_path, 'rb') as file:
            log_line_count = sum(1 for _ in file)

            file.seek(0, os.SEEK_END)
            file_size = file.tell()

            if file_size == 0:
                return None

            file.seek(-2, os.SEEK_END)
            while file.read(1) != b'\n':
                if file.tell() == 1:
                    file.seek(0)
                    break
                file.seek(-2, os.SEEK_CUR)

            last_line = file.readline().decode('utf-8').strip()
            return last_line
    except Exception as e:
        print(f"Error reading log file: {e}")
        return None


def parse_arena_ids_from_log(log_entry: str) -> list[str]:
    try:
        log_segments = log_entry.split("::")
        if len(log_segments) < 3:
            return []

        cards_section = log_segments[2].split(": ")
        if len(cards_section) < 2:
            return []

        arena_ids_str = cards_section[1].strip("[]")
        return [id.strip() for id in arena_ids_str.split(", ") if id.strip()]
    except (IndexError, AttributeError):
        return []


async def get_log_line_count() -> int:
    return log_line_count


async def get_last_processed_count() -> int:
    return last_processed_log_line_count


async def set_last_processed_count(count: int) -> None:
    global last_processed_log_line_count
    last_processed_log_line_count = count
