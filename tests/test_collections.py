import json

from steamshelf.collections import Collection, CollectionSet, parse_entry


def test_parse_entry_reads_a_collection():
    entry = {
        "key": "user-collections.uc-abc",
        "version": "314",
        "value": json.dumps({"id": "uc-abc", "name": "Shooters", "added": [70, 220], "removed": []}),
    }
    collection = parse_entry(entry)
    assert collection.name == "Shooters"
    assert collection.added == [70, 220]
    assert collection.editable


def test_deleted_entries_are_not_editable():
    collection = parse_entry({"key": "user-collections.uc-x", "is_deleted": True, "version": "9"})
    assert collection.is_deleted
    assert not collection.editable


def test_dynamic_collections_are_left_alone():
    entry = {
        "key": "user-collections.uc-dyn",
        "value": json.dumps({"id": "uc-dyn", "name": "Unplayed", "added": [], "removed": [],
                             "filterSpec": {"nFormatVersion": 2}}),
    }
    collection = parse_entry(entry)
    assert collection.is_dynamic
    assert not collection.editable


def test_non_collection_keys_are_ignored():
    assert parse_entry({"key": "GameReleased", "value": "{}"}) is None


def test_round_trip_through_an_entry():
    collection = Collection(id="uc-abc", name="Shooters", added=[220, 70, 70])
    value = json.loads(collection.to_entry()["value"])
    assert value["added"] == [70, 220]  # sorted and de-duplicated


def test_ensure_reuses_a_collection_by_name():
    cs = CollectionSet(collections={"uc-1": Collection(id="uc-1", name="(Deck) Verified")})
    assert cs.ensure("(Deck) Verified").id == "uc-1"
    assert cs.ensure("(Deck) Playable").id != "uc-1"


def test_apps_block_is_brace_matched():
    from steamshelf.store import _apps_block

    vdf = '''"UserLocalConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"apps"
\t\t\t\t{
\t\t\t\t\t"70"
\t\t\t\t\t{
\t\t\t\t\t\t"LastPlayed"\t\t"1700000000"
\t\t\t\t\t}
\t\t\t\t\t"548430"
\t\t\t\t\t{
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
\t"friends"
\t{
\t\t"99999999"
\t\t{
\t\t}
\t}
}'''
    block = _apps_block(vdf)
    assert '"70"' in block and '"548430"' in block
    # The friends section sits outside the matched braces and must not leak in.
    assert "99999999" not in block
