import os
from dataclasses import dataclass, field

from app.config import log_file_path

log_line_count = 0
last_processed_log_line_count = 0


@dataclass
class LogState:
    cards_log: list[str] = field(default_factory=list)
    actions_log: list[dict] = field(default_factory=list)
    annotations_log: list[dict] = field(default_factory=list)

    def has_cards(self) -> bool:
        return bool(self.cards_log)

    def has_actions(self) -> bool:
        return bool(self.actions_log)

    def has_annotations(self) -> bool:
        return bool(self.annotations_log)

    def has_all(self) -> bool:
        return all([self.cards_log, self.actions_log, self.annotations_log])

    def has_any(self) -> bool:
        return any([self.cards_log, self.actions_log, self.annotations_log])


class LogEntry:
    def __init__(self):
        self._cards_log: list[str] | None = None
        self._actions_log: list[dict] | None = None
        self._annotations_log: list[dict] | None = None
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

    @property
    def cards_log(self) -> list[str] | None:
        return self._cards_log

    @property
    def actions_log(self) -> list[dict] | None:
        return self._actions_log

    @property
    def annotations_log(self) -> list[dict] | None:
        return self._annotations_log

    def get_current_state(self) -> LogState:
        return LogState(
            cards_log=self._cards_log or [],
            actions_log=self._actions_log or [],
            annotations_log=self._annotations_log or [],
        )

    def reset(self) -> None:
        self._cards_log = None
        self._actions_log = None
        self._annotations_log = None

    def reset_cards(self) -> None:
        self._cards_log = None

    def reset_actions(self) -> None:
        self._actions_log = None

    def reset_annotations(self) -> None:
        self._annotations_log = None

    def parse_cards_log_line(self, log_line: str) -> list[str]:
        try:
            log_segments = log_line.split("::")
            if len(log_segments) < 3:
                return []

            cards_section = log_segments[2].split(": ")
            if len(cards_section) < 2:
                return []

            if "cards" in log_line:
                arena_ids_str = cards_section[1].strip("[]")
                self._cards_log = [id.strip() for id in arena_ids_str.split(", ") if id.strip()]
                return self._cards_log

            return []
        except (IndexError, AttributeError):
            return []

    def parse_actions_log_line(self, log_line: str) -> list[dict]:
        import jsonpickle
        try:
            log_segments = log_line.split("::")
            if len(log_segments) < 3:
                return []

            actions_section = log_segments[2]
            if "actions" in log_line:
                actions_str = actions_section.split("actions: ")[1]
                self._actions_log = jsonpickle.decode(actions_str)
                return self._actions_log

            return []
        except (IndexError, AttributeError):
            return []

    def parse_annotations_log_line(self, log_line: str) -> list[dict]:
        import jsonpickle
        try:
            log_segments = log_line.split("::")
            if len(log_segments) < 3:
                return []

            annotations_str = log_segments[2].strip()
            if "annotations" in log_line:
                self._annotations_log = jsonpickle.decode(annotations_str)
                return self._annotations_log

            return []
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