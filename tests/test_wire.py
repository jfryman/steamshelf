from steamshelf import wire

ENTRY = {
    1: ("key", "string"),
    2: ("is_deleted", "bool"),
    3: ("value", "string"),
    4: ("timestamp", "fixed32"),
    5: ("version", "uint64"),
}
NAMESPACE = {
    1: ("enamespace", "uint32"),
    2: ("version", "uint64"),
    3: ("entries", "message", True, ENTRY),
    4: ("horizon", "uint64"),
}


def test_round_trip_scalars():
    message = {"key": "user-collections.uc-abc", "value": '{"id":1}', "timestamp": 1700000000,
               "version": 42, "is_deleted": True}
    assert wire.decode(wire.encode(message, ENTRY), ENTRY) == message


def test_round_trip_repeated_messages():
    message = {
        "enamespace": 1,
        "version": 1181,
        "entries": [{"key": "a", "value": "1"}, {"key": "b", "is_deleted": True}],
    }
    assert wire.decode(wire.encode(message, NAMESPACE), NAMESPACE) == message


def test_negative_varints_survive():
    schema = {7: ("os_type", "int32")}
    assert wire.decode(wire.encode({"os_type": -203}, schema), schema) == {"os_type": -203}


def test_unknown_fields_are_ignored():
    blob = wire.encode({"key": "x", "version": 9}, ENTRY)
    assert wire.decode(blob, {1: ("key", "string")}) == {"key": "x"}
