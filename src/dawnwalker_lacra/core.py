"""DSAV container, tree parser, q103 planner and patch implementation."""

from __future__ import annotations

import hashlib
import struct
import subprocess
import tempfile
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import xxhash

from . import profile


class SaveError(ValueError):
    """A safe, user-facing refusal to inspect or modify a save."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SaveError(message)


def uint(data: bytes, pos: int, fmt: str = "I") -> int:
    require(0 <= pos <= len(data) - struct.calcsize("<" + fmt), "Truncated integer")
    return struct.unpack_from("<" + fmt, data, pos)[0]


def packed(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 35, 7):
        require(pos < len(data), "Truncated packed integer")
        byte = data[pos]
        pos += 1
        value |= (byte >> 1) << shift
        if byte & 1 == 0:
            return value, pos
    raise SaveError("Invalid packed integer")


def pack(value: int) -> bytes:
    require(0 <= value < 2**35, "Packed integer out of range")
    result = bytearray()
    while value >= 128:
        result.append(((value & 127) << 1) | 1)
        value >>= 7
    result.append(value << 1)
    return bytes(result)


class Decoder(Protocol):
    def decode(self, compressed: bytes, expected_size: int) -> bytes: ...


class PyOozDecoder:
    """In-process Kraken decoder supplied by the GPLv3+ pyooz package."""

    def decode(self, compressed: bytes, expected_size: int) -> bytes:
        try:
            import ooz
        except ImportError as exc:
            raise SaveError("pyooz decoder is not installed") from exc
        try:
            result = ooz.decompress(compressed, expected_size)
        except Exception as exc:
            raise SaveError(f"Kraken decoder failed: {exc}") from exc
        require(isinstance(result, bytes) and len(result) == expected_size,
                "Decoder returned an unexpected byte count")
        return result


@dataclass(frozen=True)
class ExternalDecoder:
    executable: Path
    timeout: float = 30.0

    def decode(self, compressed: bytes, expected_size: int) -> bytes:
        require(self.executable.is_file(), f"Decoder not found: {self.executable}")
        with tempfile.TemporaryDirectory(prefix="lacra-decoder-") as work:
            source = Path(work, "input.bin")
            target = Path(work, "output.bin")
            source.write_bytes(compressed)
            try:
                subprocess.run(
                    [str(self.executable.resolve()), str(source), str(expected_size), str(target)],
                    check=True, timeout=self.timeout, capture_output=True,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                raise SaveError(f"Kraken decoder failed: {exc}") from exc
            require(target.is_file(), "Decoder did not create output")
            result = target.read_bytes()
        require(len(result) == expected_size, "Decoder returned an unexpected byte count")
        return result


@dataclass
class Node:
    ident: int
    name: str
    name_index: int
    start: int
    end: int
    parent: int | None
    sibling: int
    child: int


class Save:
    MAX_FILE = 64 * 1024 * 1024
    MAX_BLOCK = 131072

    def __init__(self, file_bytes: bytes, decoder: Decoder | None = None):
        self.file = file_bytes
        self.decoder = decoder
        self.chunks: list[tuple[int, int]] = []
        self.raw = self._decode_container()
        self._parse_tree()

    @classmethod
    def from_path(cls, path: Path, decoder: Decoder | None = None) -> Save:
        return cls(path.read_bytes(), decoder)

    @classmethod
    def from_decoded_fixture(cls, raw: bytes, header: bytes) -> Save:
        """Build a parser input around trusted decoded test material."""
        require(len(header) >= 36, "Missing fixture header")
        blocks = []
        pairs = []
        for start in range(0, len(raw), cls.MAX_BLOCK):
            plain = raw[start:start + cls.MAX_BLOCK]
            stored = b"\xcc\x06" + plain
            pairs.append((len(stored), len(plain)))
            blocks.append(b"CHNK" + struct.pack("<II", *pairs[-1]) + stored)
        result_header = bytearray(header[:36])
        struct.pack_into("<I", result_header, 28, sum(map(len, blocks)))
        file_bytes = bytes(result_header) + b"".join(blocks)
        file_bytes += b"VASD" + struct.pack("<I", len(pairs))
        file_bytes += b"".join(struct.pack("<II", *pair) for pair in pairs) + b"VASD"
        return cls(file_bytes)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.file).hexdigest()

    def _decode_container(self) -> bytes:
        b = self.file
        require(36 <= len(b) <= self.MAX_FILE, "Unsupported save size")
        require(b[:4] == b[32:36] == b"DSAV" and uint(b, 4) == 36, "Invalid DSAV header")
        self.save_version = uint(b, 8, "H")
        self.game_version = uint(b, 10, "H")
        require(uint(b, 12) == 2, "Unsupported DSAV header variant")
        stop = 36 + uint(b, 28)
        require(36 <= stop <= len(b), "Invalid compressed body size")
        pos = 36
        parts = []
        while pos < stop:
            require(b[pos:pos + 4] == b"CHNK", "Missing CHNK marker")
            compressed, size = struct.unpack_from("<II", b, pos + 4)
            pos += 12
            require(0 < size <= self.MAX_BLOCK, "Invalid decoded chunk size")
            require(0 < compressed <= stop - pos, "Invalid compressed chunk size")
            block = b[pos:pos + compressed]
            if block[:2] == b"\xcc\x06":
                data = block[2:]
            else:
                require(self.decoder is not None, "Compressed save requires a Kraken decoder")
                data = self.decoder.decode(block, size)
            require(len(data) == size, "Decoded chunk length mismatch")
            parts.append(data)
            self.chunks.append((compressed, size))
            pos += compressed
        footer = b"VASD" + struct.pack("<I", len(self.chunks))
        footer += b"".join(struct.pack("<II", *pair) for pair in self.chunks) + b"VASD"
        require(pos == stop and b[stop:] == footer, "Invalid DSAV footer")
        return b"".join(parts)

    def _parse_tree(self) -> None:
        b = self.raw
        self.names_pos, self.directory_pos, logical_end = (
            uint(self.file, pos) - 36 for pos in (16, 20, 24)
        )
        require(logical_end == len(b), "Logical payload length mismatch")
        require(0 <= self.names_pos < self.directory_pos < len(b), "Invalid logical offsets")
        require(b[self.names_pos:self.names_pos + 4] == b"NAME", "Missing NAME section")
        names_end = self.names_pos + 8 + uint(b, self.names_pos + 4)
        pos = self.names_pos + 8
        self.names: list[str] = []
        while pos < names_end:
            size = b[pos]
            pos += 1
            require(size > 0 and pos + size <= names_end, "Invalid NAME entry")
            self.names.append(b[pos:pos + size].decode("utf-8"))
            pos += size
        require(pos == names_end, "NAME entries overrun")
        require(b[names_end:names_end + 4] == b"NAME", "Missing NAME trailer")
        require(names_end + 4 == self.directory_pos, "NAME boundary mismatch")
        require(b[self.directory_pos:self.directory_pos + 4] == b"DWNT", "Missing DWNT")
        count = uint(b, self.directory_pos + 4, "H")
        require(self.directory_pos + 6 + count * 16 + 4 == len(b), "Invalid DWNT length")
        require(b[-4:] == b"DWNT", "Missing DWNT trailer")
        self.nodes: list[Node] = []
        ancestors: list[Node] = []
        for ident in range(count):
            name_index, sibling, child, offset, size = struct.unpack_from(
                "<IHHII", b, self.directory_pos + 6 + ident * 16
            )
            start = offset - 36
            end = start + size
            require(1 <= name_index <= len(self.names), "Invalid node name index")
            require(0 <= start < end <= self.names_pos, "Invalid node bounds")
            require(b[start:start + 4] == b"SN" + struct.pack("<H", ident), "Bad SN ordinal")
            while ancestors and start >= ancestors[-1].end:
                ancestors.pop()
            require(not ancestors or end <= ancestors[-1].end, "Overlapping nodes")
            node = Node(ident, self.names[name_index - 1], name_index, start, end,
                        ancestors[-1].ident if ancestors else None, sibling, child)
            self.nodes.append(node)
            ancestors.append(node)
        require(self.nodes and self.nodes[0].start == 0 and self.nodes[0].end == self.names_pos,
                "Invalid root node")
        children: dict[int, list[int]] = {}
        for node in self.nodes[1:]:
            require(node.parent is not None, "Orphaned node")
            children.setdefault(node.parent, []).append(node.ident)
        for node in self.nodes:
            ids = children.get(node.ident, [])
            require(node.child == (ids[0] if ids else 65535), "Invalid child pointer")
            for index, ident in enumerate(ids):
                expected = ids[index + 1] if index + 1 < len(ids) else 65535
                require(self.nodes[ident].sibling == expected, "Invalid sibling pointer")
        self.sections = {n.name: n for n in self.nodes if n.parent == 0}

    def prefix(self, node: Node | str) -> bytes:
        if isinstance(node, str):
            require(node in self.sections, f"Missing section: {node}")
            node = self.sections[node]
        stop = self.nodes[node.child].start if node.child != 65535 else node.end
        return self.raw[node.start + 4:stop]

    def fname(self, pos: int) -> tuple[str, int, int]:
        value, pos = packed(self.raw, pos)
        base = value & 65535
        require(1 <= base <= len(self.names), "Invalid FName index")
        number = value >> 16
        return self.names[base - 1], number, pos


def facts(save: Save) -> dict[int, int]:
    body = save.prefix("FactsDB")
    require(uint(body, 0, "H") == 1, "Unsupported FactsDB")
    count = uint(body, 2)
    require(len(body) == 6 + count * 8, "Invalid FactsDB length")
    result = dict(struct.iter_unpack("<Ii", body[6:]))
    require(len(result) == count, "Duplicate fact hash")
    return result


def runtime(save: Save):
    body = save.prefix("QuestSystemImpl")
    pos = 2 + uint(body, 0, "H")
    count_pos = pos
    count = uint(body, pos)
    start = pos + 4
    require(start + count * 8 <= len(body), "Invalid runtime path table")
    values = struct.unpack_from("<" + "Q" * count, body, start)
    paths, current = [], []
    for value in values:
        if value == 2**64 - 1:
            paths.append(tuple(current))
            current = []
        else:
            current.append(value)
    require(not current and len(paths) == len(set(paths)), "Invalid runtime paths")
    mapping = {}
    for path in paths:
        digest = xxhash.xxh3_64(struct.pack("<" + "Q" * len(path), *path)).intdigest()
        require(digest not in mapping or mapping[digest] == path, "Runtime path collision")
        mapping[digest] = path
    pos = start + count * 8
    entry_count = uint(body, pos, "H")
    entry_start = pos + 2
    entry_end = entry_start + 24 * entry_count
    require(entry_end <= len(body), "Invalid runtime entries")
    entries = list(struct.iter_unpack("<QQQ", body[entry_start:entry_end]))
    return body, count_pos, paths, mapping, entries, body[entry_end:]


def belongs_to_q103(entry, mapping) -> bool:
    path = mapping.get(entry[0], ())
    return path[:2] == (0, 18878) or (path == (0,) and entry[1] == 18878)


def journal(save: Save):
    body = save.prefix("Journal")
    pos, groups = 0, []
    for group_index in range(2):
        count = uint(body, pos)
        pos += 4
        rows = []
        for _ in range(count):
            require(pos < len(body), "Truncated journal")
            kind = body[pos]
            pos += 1
            valid_kinds = {1} if group_index == 0 else {2, 3}
            require(kind in valid_kinds, "Unexpected journal category")
            arrays = []
            for fmt in ("I", "Q", "I", "B"):
                count = uint(body, pos, "H")
                pos += 2
                require(0 < count < 1000, "Invalid journal array size")
                size = struct.calcsize(fmt) * count
                require(pos + size <= len(body), "Truncated journal array")
                arrays.append(list(struct.unpack_from("<" + fmt * count, body, pos)))
                pos += size
            require(len({len(array) for array in arrays}) == 1, "Journal array mismatch")
            value, pos = packed(body, pos)
            base = value & 65535
            require(1 <= base <= len(save.names), "Invalid journal FName")
            require(pos < len(body), "Missing journal outcome")
            rows.append({"kind": kind, "arrays": arrays, "asset": save.names[base - 1],
                         "fname_number": value >> 16, "flag": body[pos]})
            pos += 1
        require(len({row["asset"] for row in rows}) == len(rows), "Duplicate journal asset")
        groups.append(rows)
    return groups, body[pos:]


def encode_journal(groups, tail: bytes, names: list[str]) -> bytes:
    indices = {name: index + 1 for index, name in enumerate(names)}
    result = bytearray()
    for rows in groups:
        result += struct.pack("<I", len(rows))
        for row in rows:
            result.append(row["kind"])
            for fmt, values in zip(("I", "Q", "I", "B"), row["arrays"], strict=True):
                result += struct.pack("<H", len(values))
                result += struct.pack("<" + fmt * len(values), *values)
            result += pack(indices[row["asset"]] | (row["fname_number"] << 16))
            result.append(row["flag"])
    return bytes(result) + tail


def communities(save: Save):
    result, tables = {}, {}
    section_id = save.sections["CommunitySystemImpl"].ident
    for node in save.nodes:
        if node.parent == section_id and node.name == "Table":
            name, number, _ = save.fname(node.start + 6)
            tables[node.ident] = name + (f"_{number - 1}" if number else "")
        elif node.parent in tables and node.name == "Entry":
            name, number, pos = save.fname(node.start + 4)
            name += f"_{number - 1}" if number else ""
            key = tables[node.parent] + "::" + name
            require(key not in result, "Duplicate community entry")
            result[key] = (node, pos, save.raw[pos:node.end])
    return result


def helper(save: Save):
    body = save.prefix("QuestHelperImpl")
    first = uint(body, 0, "H")
    pos = 2 + first * 24
    count = uint(body, pos, "H")
    end = pos + 2 + count * 24
    require(end <= len(body), "Invalid QuestHelper table")
    return body[:pos], list(struct.iter_unpack("<QQQ", body[pos + 2:end])), body[end:]


def ai_rows(save: Save):
    body = save.prefix("RebelAISubsystem")
    pos = 4
    for _ in range(uint(body, 0)):
        _, pos = packed(body, pos)
    count = uint(body, pos, "H")
    end = pos + 2 + count * 16
    require(end <= len(body), "Invalid AI table")
    return body[:pos], [body[pos + 2 + 16*i:pos + 2 + 16*(i+1)] for i in range(count)], body[end:]


def actor_stub(save: Save, handle: int):
    body = save.prefix("PersistencySystemImpl")
    count = uint(body, 4)
    require(8 + count * 20 <= len(body), "Invalid persistency map")
    anchors = {body[8 + 20*i:24 + 20*i]: uint(body, 24 + 20*i) for i in range(count)}
    require(len(anchors) == count, "Duplicate persistency GUID")
    require("ActorStubPS" in save.names, "Missing ActorStubPS name")
    needle = struct.pack("<I", handle) + b"\x01" + pack(save.names.index("ActorStubPS") + 1)
    start = 8 + count * 20 + 4
    pos = body.find(needle, start)
    require(pos >= 0 and body.find(needle, pos + 1) < 0, "Ambiguous Lacra actor stub")
    return body, pos + len(needle), anchors


@dataclass(frozen=True)
class Analysis:
    status: str
    reason: str
    handle: int | None = None


def analyze(save: Save) -> Analysis:
    if (save.save_version not in profile.SUPPORTED_SAVE_VERSIONS
            or save.game_version != profile.SUPPORTED_GAME_VERSION):
        versions = " or ".join(map(str, profile.SUPPORTED_SAVE_VERSIONS))
        return Analysis("unsupported", f"Only DSAV SaveVersion {versions} / GameVersion 5 is supported")
    current_facts = facts(save)
    if current_facts.get(0x97A42C79) == 1:
        return Analysis("already_progressed", "Lacra cooperation is already present")
    groups, _ = journal(save)
    all_assets = {row["asset"] for rows in groups for row in rows}
    if profile.URIASHES in all_assets:
        return Analysis("already_progressed", "Song of the Mountain is already in the journal")
    fact_preconditions = profile.FACT_PRECONDITIONS_BY_SAVE_VERSION[save.save_version]
    mismatches = [key for key, expected in fact_preconditions.items()
                  if current_facts.get(key) != expected]
    if mismatches:
        return Analysis("unsupported_branch", "Fact profile differs: " + ", ".join(f"{x:08x}" for x in mismatches))
    completed = [row for row in groups[1] if row["asset"] == profile.INVESTIGATION]
    if len(completed) != 1 or completed[0]["flag"] != 2:
        return Analysis("unsupported_branch", "A Friend Like This journal outcome is not the tested bad branch")
    _, _, _, mapping, entries, _ = runtime(save)
    if any(belongs_to_q103(entry, mapping) for entry in entries if entry[0]):
        return Analysis("already_progressed", "q103 runtime is already active")
    comm = communities(save)
    if profile.LACRA not in comm or profile.VICTIM not in comm:
        return Analysis("unsupported_layout", "Required Lacra community records are missing")
    _, _, lacra_data = comm[profile.LACRA]
    if len(lacra_data) != 17 or uint(lacra_data, 0, "H") != 65535:
        return Analysis("unsupported_layout", "Lacra community layout is not the tested bad layout")
    handle = uint(lacra_data, 13)
    _, _, victim_data = comm[profile.VICTIM]
    if uint(victim_data, 0, "H") != 65535:
        return Analysis("unsupported_layout", "Victim is not in the tested inactive phase")
    persist, offset, anchors = actor_stub(save, handle)
    if profile.ANCHOR_GUID not in anchors:
        return Analysis("unsupported_layout", "Destination anchor is missing")
    if offset + 36 > len(persist):
        return Analysis("unsupported_layout", "Lacra actor stub is truncated")
    if persist[offset + 32:offset + 36] not in profile.SOURCE_LIFECYCLE_STATES_BY_SAVE_VERSION[
        save.save_version
    ]:
        return Analysis("unsupported_layout", "Unknown Lacra lifecycle layout")
    _, rows, _ = ai_rows(save)
    own = [row for row in rows if uint(row, 0) == handle]
    if len(own) != 1:
        return Analysis("unsupported_layout", "Lacra AI record is missing or ambiguous")
    ai_state = own[0][4:]
    # Bytes 1..3 are transient activity flags: they vary across the user's
    # post-choice saves (and in the controlled bad branch). The discriminator,
    # layout marker, and trailing fields stay fixed. Validate those structural
    # bytes instead of pinning a single momentary AI state from ManualSave23.
    if (len(ai_state) != 12 or ai_state[0] != 2
            or ai_state[4:] != profile.AI_SOURCE_SUFFIX_BY_SAVE_VERSION[save.save_version]):
        return Analysis("unsupported_layout", "Unknown Lacra AI record layout")
    return Analysis("repair_available", "Tested release-Nish branch detected", handle)


def _build(save: Save, replacements: dict[int, bytes], extra_names: list[str]) -> tuple[bytes, bytes]:
    edits = []
    for ident, data in replacements.items():
        node = save.nodes[ident]
        stop = save.nodes[node.child].start if node.child != 65535 else node.end
        edits.append((node.start + 4, stop, data))
    names_data = save.raw[save.names_pos + 8:save.directory_pos - 4]
    for name in extra_names:
        encoded = name.encode("utf-8")
        require(0 < len(encoded) <= 255, "NAME entry too long")
        names_data += bytes([len(encoded)]) + encoded
    edits.append((save.names_pos, save.directory_pos,
                  b"NAME" + struct.pack("<I", len(names_data)) + names_data + b"NAME"))
    edits.sort()
    parts, cursor = [], 0
    for start, end, data in edits:
        require(cursor <= start <= end, "Overlapping patch edits")
        parts.extend((save.raw[cursor:start], data))
        cursor = end
    require(cursor == save.directory_pos, "Patch did not terminate at NAME boundary")
    raw = b"".join(parts)
    new_directory = len(raw)

    def moved(position: int) -> int:
        return position + sum(len(data) - (end - start) for start, end, data in edits if end <= position)

    raw += b"DWNT" + struct.pack("<H", len(save.nodes))
    for node in save.nodes:
        raw += struct.pack("<IHHII", node.name_index, node.sibling, node.child,
                           moved(node.start) + 36, moved(node.end) - moved(node.start))
    raw += b"DWNT"
    header = bytearray(save.file[:36])
    struct.pack_into("<III", header, 16, moved(save.names_pos) + 36,
                     new_directory + 36, len(raw) + 36)
    blocks, pairs = [], []
    for start in range(0, len(raw), Save.MAX_BLOCK):
        plain = raw[start:start + Save.MAX_BLOCK]
        stored = b"\xcc\x06" + plain
        pairs.append((len(stored), len(plain)))
        blocks.append(b"CHNK" + struct.pack("<II", *pairs[-1]) + stored)
    body = b"".join(blocks)
    struct.pack_into("<I", header, 28, len(body))
    result = bytes(header) + body + b"VASD" + struct.pack("<I", len(pairs))
    result += b"".join(struct.pack("<II", *pair) for pair in pairs) + b"VASD"
    return result, raw


def repair(save: Save) -> tuple[bytes, dict]:
    analysis = analyze(save)
    require(analysis.status == "repair_available", analysis.reason)
    handle = analysis.handle
    assert handle is not None
    replacements: dict[int, bytes] = {}
    names = list(save.names)
    extra_names = []
    if profile.URIASHES not in names:
        names.append(profile.URIASHES)
        extra_names.append(profile.URIASHES)

    current_facts = facts(save)
    fact_targets = profile.FACT_TARGETS_BY_SAVE_VERSION[save.save_version]
    fact_changes = []
    for key, target in fact_targets.items():
        old = current_facts.get(key)
        if target is None:
            current_facts.pop(key, None)
        else:
            current_facts[key] = target
        fact_changes.append({"hash": f"{key:08x}", "old": old, "new": target})
    replacements[save.sections["FactsDB"].ident] = b"\x01\x00" + struct.pack("<I", len(current_facts))
    replacements[save.sections["FactsDB"].ident] += b"".join(
        struct.pack("<Ii", *item) for item in current_facts.items()
    )

    body, count_pos, paths, _mapping, entries, tail = runtime(save)
    new_paths = [path for path in profile.Q103_PATHS if path not in paths]
    for entry in profile.Q103_ENTRIES_BY_SAVE_VERSION[save.save_version]:
        if entry in entries:
            continue
        free = next((index for index, item in enumerate(entries)
                     if item[0] == 0 and item[1] == 2**64 - 1), None)
        if free is None:
            entries.append(entry)
        else:
            entries[free] = entry
    path_bytes = b"".join(struct.pack("<" + "Q" * (len(path) + 1), *path, 2**64 - 1)
                          for path in paths + new_paths)
    replacements[save.sections["QuestSystemImpl"].ident] = body[:count_pos]
    replacements[save.sections["QuestSystemImpl"].ident] += struct.pack("<I", len(path_bytes) // 8)
    replacements[save.sections["QuestSystemImpl"].ident] += path_bytes + struct.pack("<H", len(entries))
    replacements[save.sections["QuestSystemImpl"].ident] += b"".join(
        struct.pack("<QQQ", *entry) for entry in entries
    ) + tail

    before, rows, suffix = helper(save)
    if profile.HELPER_ENTRY not in rows:
        rows.append(profile.HELPER_ENTRY)
    replacements[save.sections["QuestHelperImpl"].ident] = before + struct.pack("<H", len(rows))
    replacements[save.sections["QuestHelperImpl"].ident] += b"".join(
        struct.pack("<QQQ", *row) for row in rows
    ) + suffix

    groups, journal_tail = journal(save)
    uriashes_record = deepcopy(profile.URIASHES_RECORD)
    timestamps = profile.URIASHES_TIMESTAMPS_BY_SAVE_VERSION.get(save.save_version)
    if timestamps:
        uriashes_record["arrays"][1][:2] = timestamps
    groups[0].append(uriashes_record)
    investigation = next(row for row in groups[1] if row["asset"] == profile.INVESTIGATION)
    investigation["flag"] = 1
    target_journal_nodes = profile.JOURNAL_TARGET_NODES_BY_SAVE_VERSION[save.save_version]
    for node_id, (timestamp, value, status) in target_journal_nodes.items():
        require(node_id in investigation["arrays"][0], f"Missing investigation node {node_id}")
        index = investigation["arrays"][0].index(node_id)
        investigation["arrays"][1][index] = timestamp
        investigation["arrays"][2][index] = value
        investigation["arrays"][3][index] = status
    replacements[save.sections["Journal"].ident] = encode_journal(groups, journal_tail, names)

    comm = communities(save)
    lacra_node, lacra_offset, lacra_data = comm[profile.LACRA]
    identity = lacra_data[2:7]
    new_lacra = b"\x02\x00" + identity + b"\x00\x00\x01\x00" + struct.pack("<I", handle) + b"\x00\x00"
    replacements[lacra_node.ident] = save.raw[lacra_node.start + 4:lacra_offset] + new_lacra
    victim_node, victim_offset, victim_data = comm[profile.VICTIM]
    if save.save_version == 136:
        victim_handle = handle + 2
        victim_state = (
            b"\x00\x00" + victim_data[2:7] + b"\x00\x00\x01\x00"
            + struct.pack("<I", victim_handle) + b"\x00\x00"
        )
    else:
        victim_state = b"\x00\x00" + victim_data[2:]
    replacements[victim_node.ident] = save.raw[victim_node.start + 4:victim_offset] + victim_state

    persist, actor_offset, anchors = actor_stub(save, handle)
    new_persist = bytearray(persist)
    actor_state = (
        profile.PLACEMENT_BY_SAVE_VERSION[save.save_version]
        + struct.pack("<I", anchors[profile.ANCHOR_GUID])
        + profile.LIFECYCLE_BY_SAVE_VERSION[save.save_version]
    )
    new_persist[actor_offset:actor_offset + 36] = actor_state
    replacements[save.sections["PersistencySystemImpl"].ident] = bytes(new_persist)

    pre, ai, ai_suffix = ai_rows(save)
    indexes = [index for index, row in enumerate(ai) if uint(row, 0) == handle]
    require(len(indexes) == 1, "Ambiguous Lacra AI record")
    ai[indexes[0]] = struct.pack("<I", handle) + profile.AI_TAIL_BY_SAVE_VERSION[save.save_version]
    replacements[save.sections["RebelAISubsystem"].ident] = pre + struct.pack("<H", len(ai))
    replacements[save.sections["RebelAISubsystem"].ident] += b"".join(ai) + ai_suffix

    result_bytes, expected_raw = _build(save, replacements, extra_names)
    result = Save(result_bytes)
    require(result.raw == expected_raw, "Stored DSAV round-trip mismatch")
    validate(save, result, set(fact_targets))
    return result_bytes, {
        "profile": f"q103-release-nish-to-continuation-v1-save{save.save_version}",
        "source_sha256": save.sha256,
        "output_sha256": result.sha256,
        "facts": fact_changes,
        "added_paths": [list(path) for path in new_paths],
        "actor_handle": handle,
        "validation": "passed",
    }


def validate(source: Save, result: Save, changed_facts: set[int]) -> None:
    allowed = {"FactsDB", "Journal", "QuestSystemImpl", "QuestHelperImpl",
               "CommunitySystemImpl", "PersistencySystemImpl", "RebelAISubsystem"}
    require(source.sections.keys() == result.sections.keys(), "Top-level sections changed")
    for name, node in source.sections.items():
        if name not in allowed:
            after = result.sections[name]
            require(source.raw[node.start:node.end] == result.raw[after.start:after.end],
                    f"Protected section changed: {name}")
    before_facts, after_facts = facts(source), facts(result)
    require({k: v for k, v in before_facts.items() if k not in changed_facts} ==
            {k: v for k, v in after_facts.items() if k not in changed_facts},
            "Unrelated facts changed")
    require(result.names == source.names + ([profile.URIASHES] if profile.URIASHES not in source.names else []),
            "Existing NAME indices changed")
    before_groups, before_tail = journal(source)
    after_groups, after_tail = journal(result)
    require(before_tail == after_tail, "Tracked journal target changed")
    for group in range(2):
        excluded = {profile.INVESTIGATION, profile.URIASHES}
        before = {row["asset"]: row for row in before_groups[group] if row["asset"] not in excluded}
        after = {row["asset"]: row for row in after_groups[group] if row["asset"] not in excluded}
        require(before == after, "Unrelated journal changed")
    _, _, bp, bm, be, bt = runtime(source)
    _, _, ap, am, ae, at = runtime(result)
    require(ap[:len(bp)] == bp and bt == at, "Existing runtime paths or tail changed")
    require(Counter(e for e in be if e[0] and not belongs_to_q103(e, bm)) ==
            Counter(e for e in ae if e[0] and not belongs_to_q103(e, am)),
            "Unrelated runtime entries changed")
    before_comm, after_comm = communities(source), communities(result)
    for key in before_comm.keys() - {profile.LACRA, profile.VICTIM}:
        require(before_comm[key][2] == after_comm[key][2], "Unrelated community changed")
