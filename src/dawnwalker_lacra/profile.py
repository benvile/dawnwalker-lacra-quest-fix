"""Versioned, donor-free target state for the tested q103 continuation repair."""

from __future__ import annotations

INVESTIGATION = (
    "/Game/_Dawnwalker/Quest/q103_lacra/Journal/"
    "q103_journal_investigation.q103_journal_investigation"
)
URIASHES = (
    "/Game/_Dawnwalker/Quest/q103_lacra/Journal/"
    "q103_journal_uriashes.q103_journal_uriashes"
)
LACRA = "/Game/_Dawnwalker/NPC/MainNPC/CR_Lacra::Lacra"
VICTIM = "/Game/_Dawnwalker/Quest/q103_lacra/Spawn/q103_start::Victim"

FACT_TARGETS: dict[int, int | None] = {
    0x05B64571: 0,
    0x1194B475: None,
    0x1354BBB1: 1,
    0x2005C830: None,
    0x37E379B0: 1,
    0x40EF07F8: 2,
    0x5A70A2B0: 1,
    0x80A8F66A: None,
    0x92610763: 1,
    0x976C1080: 3,
    0x97A42C79: 1,
    0xAEF0B669: 0,
    0xBF329AF8: 2,
    0xC943478B: 1,
    0xD898282F: 2,
}

# Exact observed bad-branch values. Missing and zero are intentionally distinct.
FACT_PRECONDITIONS: dict[int, int | None] = {
    0x05B64571: None,
    0x1194B475: 1,
    0x1354BBB1: None,
    0x2005C830: 1,
    0x37E379B0: None,
    0x40EF07F8: None,
    0x5A70A2B0: None,
    0x80A8F66A: 1,
    0x92610763: None,
    0x976C1080: None,
    0x97A42C79: None,
    0xAEF0B669: None,
    0xBF329AF8: None,
    0xC943478B: None,
    0xD898282F: None,
}

Q103_PATHS = (
    (0, 18878, 29332, 28945, 3380),
    (0, 18878, 16820),
    (0, 18878, 16820, 13723),
    (0, 18878, 16820, 185),
)
Q103_ENTRIES = (
    (14374147212387527897, 18878, 0),
    (10519233958176626871, 4421, 0),
    (7428281267370871075, 13723, 0),
    (10519233958176626871, 16820, 0),
    (10519233958176626871, 18853, 0),
    (10519233958176626871, 30429, 0),
    (7428281267370871075, 31673, 0),
    (7428281267370871075, 361, 0),
    (7428281267370871075, 27106, 0),
    (7428281267370871075, 6672, 0),
    (7428281267370871075, 8142, 0),
    (7428281267370871075, 16696, 0),
    (7428281267370871075, 6244, 0),
    (7428281267370871075, 185, 0),
    (2872270914693871206, 12111, 0),
    (2872270914693871206, 28943, 0),
    (723488969846943316, 32721, 0),
    (10519233958176626871, 16593, 0),
)
HELPER_ENTRY = (279601046206211, 15597, 1)
ANCHOR_GUID = bytes.fromhex("6c09a9c52928b546a332295a7d4b2bd2")
PLACEMENT = bytes.fromhex("23248a5f933de240aa1c1f54a7cc07417983e1c79c1fe34000004842")
LIFECYCLE = bytes.fromhex("001c8401")
AI_TAIL = bytes.fromhex("010001000601001000000000")

URIASHES_RECORD = {
    "kind": 1,
    "arrays": [
        [1142597282, 840616699, 1279733102, 272889234, 3759329428, 871818752,
         3588929586, 1769434529, 3794548203, 2917782646, 2610847810, 507659293,
         515397597, 3681943420, 2499969106, 3894912559, 2847753234, 387494341,
         178458799, 1047808189, 65598277, 4210782790],
        [639269120871020000, 639269120871040000] + [0] * 20,
        [0] * 22,
        [1, 1] + [0] * 20,
    ],
    "asset": URIASHES,
    "fname_number": 0,
    "flag": 0,
}

SUPPORTED_SAVE_VERSION = 134
SUPPORTED_GAME_VERSION = 5
SUPPORTED_BUILD_VERSION = 258504
