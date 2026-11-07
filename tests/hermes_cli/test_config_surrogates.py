from starlette.testclient import TestClient

from hermes_cli.config import (
    _LOAD_CONFIG_CACHE,
    _RAW_CONFIG_CACHE,
    get_config_path,
    load_config,
    read_raw_config,
    repair_surrogates,
)
from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN


def test_repair_surrogates_pairs():
    # surrogate pair for call me hand emoji (u+1f919)
    raw = "surfing \ud83e\udd19 vibes"
    repaired = repair_surrogates(raw)
    assert repaired == "surfing 🤙 vibes"


def test_repair_surrogates_lone_surrogates():
    # lone high or low surrogates are dropped cleanly
    raw = "lead \ud83e middle \udd19 trail"
    repaired = repair_surrogates(raw)
    assert repaired == "lead  middle  trail"


def test_repair_surrogates_fast_path_clean_string():
    clean = "regular clean text without any surrogates"
    assert repair_surrogates(clean) is clean


def test_repair_surrogates_nested_structures():
    data = {
        "title": "surf \ud83e\udd19",
        "nested": {
            "tags": ["beach", "waves \ud83e\udd19", 123, None, True],
            "score": 42.5,
        },
    }
    repaired = repair_surrogates(data)
    assert repaired["title"] == "surf 🤙"
    assert repaired["nested"]["tags"][1] == "waves 🤙"
    assert repaired["nested"]["tags"][2] == 123
    assert repaired["nested"]["tags"][3] is None
    assert repaired["nested"]["tags"][4] is True
    assert repaired["nested"]["score"] == 42.5


def test_load_config_and_api_config_with_disk_surrogates(_isolate_hermes_home):
    # write config.yaml with pyyaml surrogate escapes to disk
    cfg_path = get_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text('custom_greeting: "surf \\uD83E\\uDD19 vibes"\n', encoding="utf-8")

    _RAW_CONFIG_CACHE.clear()
    _LOAD_CONFIG_CACHE.clear()

    # verify load_config and read_raw_config ingest clean unicode
    loaded = load_config()
    assert loaded.get("custom_greeting") == "surf 🤙 vibes"

    raw = read_raw_config()
    assert raw.get("custom_greeting") == "surf 🤙 vibes"

    # verify get /api/config returns 200 and valid json with the repaired emoji
    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("custom_greeting") == "surf 🤙 vibes"
