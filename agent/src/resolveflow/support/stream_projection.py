"""Bounded, incremental projection of candidate ANSWER_PARTS text.

This is a lexical/structural reader, not a domain validator. Its deltas are
provisional and must pass the source/attempt gate before reaching a customer.
An unresolved brace or number holds the rest of that part for final grounding.
Only the ordinary complete answer pipeline can commit an assistant message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

Path = tuple[str | int, ...]


class ProjectionError(ValueError):
    """Discard this attempt's provisional view; never promote it into history."""


@dataclass(frozen=True, slots=True)
class AnswerDelta:
    """Offset counts decoded Unicode code points, not bytes or UTF-16 code units."""

    part_id: str
    offset: int
    text: str


@dataclass(slots=True)
class _Frame:
    kind: str
    path: Path
    state: str
    key: str = ""
    index: int = 0
    keys: set[str] = field(default_factory=set)


class AnswerProjection:
    def __init__(self, *, max_chars: int = 131_072) -> None:
        self.max_chars = max_chars
        self._size = 0
        self._raw: list[str] = []
        self._stack: list[_Frame] = []
        self._root = "value"
        self._string = False
        self._key = False
        self._path: Path = ()
        self._chars: list[str] = []
        self._escape = False
        self._unicode: str | None = None
        self._high: int | None = None
        self._atom = ""
        self._kind: str | None = None
        self._prefixes: dict[int, list[str]] = {}
        self._lengths: dict[int, int] = {}
        self._held: set[int] = set()
        self._offsets: dict[int, int] = {}
        self._failed = False
        self._finished = False

    def feed(self, fragment: str) -> list[AnswerDelta]:
        if self._failed or self._finished:
            raise ProjectionError("projection is no longer active")
        try:
            self._size += len(fragment)
            if self._size > self.max_chars:
                raise ProjectionError("projection exceeds character limit")
            self._raw.append(fragment)
            for character in fragment:
                self._consume(character)
            deltas = []
            if self._kind in {"ANSWER_PARTS", "RESPOND"}:
                for index, prefix in sorted(self._prefixes.items()):
                    offset = self._offsets.get(index, 0)
                    if len(prefix) > offset:
                        deltas.append(AnswerDelta(f"part-{index}", offset, "".join(prefix[offset:])))
                        self._offsets[index] = len(prefix)
            return deltas
        except ProjectionError:
            self._failed = True
            raise

    def finish(self) -> None:
        """Check complete JSON syntax only; this does not approve or commit an answer."""
        if self._failed or self._finished:
            raise ProjectionError("projection is no longer active")
        try:
            if self._atom:
                self._end_atom()
            if self._string or self._stack or self._root != "done":
                raise ProjectionError("incomplete JSON document")
            if not isinstance(json.loads("".join(self._raw)), dict):
                raise ProjectionError("decision must be an object")
            self._finished = True
        except ValueError as error:
            self._failed = True
            raise ProjectionError("invalid or incomplete JSON document") from error

    def _consume(self, character: str) -> None:
        if self._string:
            self._string_character(character)
            return
        if self._atom:
            if character not in " \t\n\r,]}":
                self._atom += character
                return
            self._end_atom()
        if character in " \t\n\r":
            return
        frame = self._stack[-1] if self._stack else None
        state = frame.state if frame else self._root
        if frame and frame.kind == "object" and state in {"key", "key_or_end"}:
            if character == "}" and state == "key_or_end":
                self._stack.pop()
            elif character == '"':
                self._start_string(key=True, path=frame.path)
            else:
                raise ProjectionError("expected object key")
        elif state == "colon":
            if character != ":" or frame is None:
                raise ProjectionError("expected colon")
            frame.state = "value"
        elif state == "comma_or_end":
            assert frame is not None
            closer = "}" if frame.kind == "object" else "]"
            if character == closer:
                self._stack.pop()
            elif character == ",":
                frame.state = "key" if frame.kind == "object" else "value"
            else:
                raise ProjectionError("expected comma or container end")
        elif state in {"value", "value_or_end"}:
            if frame and state == "value_or_end" and character == "]":
                self._stack.pop()
                return
            path: Path = () if frame is None else frame.path + (
                frame.key if frame.kind == "object" else frame.index,
            )
            if frame:
                frame.state = "comma_or_end"
                frame.index += 1
            else:
                self._root = "done"
            if character in "{[":
                if len(self._stack) >= 32:
                    raise ProjectionError("JSON nesting exceeds limit")
                self._stack.append(_Frame("object" if character == "{" else "array", path,
                                          "key_or_end" if character == "{" else "value_or_end"))
            elif character == '"':
                self._start_string(key=False, path=path)
            elif character in "-0123456789tfn":
                self._atom = character
            else:
                raise ProjectionError("expected JSON value")
        else:
            raise ProjectionError("unexpected content after root object")

    def _end_atom(self) -> None:
        try:
            value = json.loads(self._atom)
            if isinstance(value, (dict, list, str)):
                raise ValueError("not a scalar token")
        except ValueError as error:
            raise ProjectionError("invalid JSON scalar") from error
        self._atom = ""

    def _start_string(self, *, key: bool, path: Path) -> None:
        self._string, self._key, self._path = True, key, path
        self._chars, self._escape, self._unicode, self._high = [], False, None, None

    def _string_character(self, character: str) -> None:
        if self._unicode is not None:
            if character not in "0123456789abcdefABCDEF":
                raise ProjectionError("invalid Unicode escape")
            self._unicode += character
            if len(self._unicode) == 4:
                point = int(self._unicode, 16)
                self._unicode = None
                self._decoded(chr(point))
        elif self._escape:
            self._escape = False
            if character == "u":
                self._unicode = ""
            else:
                escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
                if character not in escapes:
                    raise ProjectionError("invalid JSON string escape")
                self._decoded(escapes[character])
        elif character == "\\":
            self._escape = True
        elif character == '"':
            if self._high is not None:
                raise ProjectionError("unpaired Unicode surrogate")
            self._string = False
            value = "".join(self._chars)
            if self._key:
                frame = self._stack[-1]
                if value in frame.keys:
                    raise ProjectionError("duplicate JSON key")
                frame.keys.add(value)
                frame.key, frame.state = value, "colon"
            elif self._path == ("kind",):
                self._kind = value
        elif ord(character) < 32:
            raise ProjectionError("unescaped control character")
        else:
            self._decoded(character)

    def _decoded(self, character: str) -> None:
        point = ord(character)
        if self._high is not None:
            if not 0xDC00 <= point <= 0xDFFF:
                raise ProjectionError("unpaired Unicode surrogate")
            character = chr(0x10000 + ((self._high - 0xD800) << 10) + point - 0xDC00)
            self._high = None
        elif 0xD800 <= point <= 0xDBFF:
            self._high = point
            return
        elif 0xDC00 <= point <= 0xDFFF:
            raise ProjectionError("unpaired Unicode surrogate")
        self._chars.append(character)
        if self._key or len(self._path) != 3 or self._path[0] != "parts" or self._path[2] != "text":
            return
        index = self._path[1]
        if not isinstance(index, int) or not 0 <= index < 8:
            raise ProjectionError("answer part exceeds limit")
        self._lengths[index] = self._lengths.get(index, 0) + 1
        if self._lengths[index] > 4000:
            raise ProjectionError("answer text exceeds limit")
        prefix = self._prefixes.setdefault(index, [])
        if character in "{}¥￥" or character.isdecimal():
            self._held.add(index)
        if index not in self._held:
            prefix.append(character)
