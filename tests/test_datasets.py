"""Checks on the committed dataset definitions (clips.csv, photos.csv). No media needed."""

import collections

from eval.clips import load_clips
from eval.photo_attacks import COLLAGE_FILLERS
from eval.photos import load_photos

ROLES, SPLITS = {"original", "negative"}, {"train", "test"}
MIN_GAP_S = 5


def seconds(hms: str) -> int:
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s


def test_clips_have_unique_ids_and_valid_labels():
    clips = load_clips()
    assert len({c.clip_id for c in clips}) == len(clips)
    assert all(c.role in ROLES and c.split in SPLITS and c.duration > 0 for c in clips)


def test_clips_never_overlap_and_keep_a_gap():
    by_source = collections.defaultdict(list)
    for c in load_clips():
        start = seconds(c.start)
        by_source[c.source].append((start, start + c.duration, c.clip_id))
    for ranges in by_source.values():
        ranges.sort()
        for (_, end, a), (start, _, b) in zip(ranges, ranges[1:], strict=False):
            assert start - end >= MIN_GAP_S, f"{a} and {b} are {start - end} s apart"


def test_clip_subclips_fit_inside_every_clip():
    assert min(c.duration for c in load_clips()) > 15  # subclip_15 needs room


def test_photos_have_unique_ids_and_valid_labels():
    photos = load_photos()
    assert len({p.photo_id for p in photos}) == len(photos)
    assert len({p.picsum_id for p in photos}) == len(photos)
    assert all(p.role in ROLES and p.split in SPLITS for p in photos)


def test_near_duplicate_groups_stay_in_one_split():
    groups = collections.defaultdict(list)
    for p in load_photos():
        if p.group:
            groups[p.group].append(p)
    assert groups
    for name, members in groups.items():
        assert len({p.split for p in members}) == 1, f"group {name} spans train and test"
        assert {p.role for p in members} == ROLES, f"group {name} needs an original and a negative"


def test_collage_fillers_are_ungrouped_negatives():
    photos = {p.photo_id: p for p in load_photos()}
    for name in COLLAGE_FILLERS:
        assert photos[name].role == "negative" and photos[name].group == ""


def test_both_splits_have_originals_and_negatives():
    for items in (load_clips(), load_photos()):
        assert {(i.role, i.split) for i in items} == {(r, s) for r in ROLES for s in SPLITS}
