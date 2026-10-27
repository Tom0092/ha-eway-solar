"""Every translation covers every string, with the same placeholders."""
import json
from pathlib import Path
from string import Formatter

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "eway_solar"


def flatten(tree, prefix=""):
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from flatten(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}", value


def placeholders(text):
    return {name for _, name, _, _ in Formatter().parse(text) if name}


@pytest.mark.parametrize("language", sorted(
    p.stem for p in (COMPONENT / "translations").glob("*.json")))
def test_translation_matches_strings(language):
    source = dict(flatten(json.loads((COMPONENT / "strings.json").read_text())))
    translated = dict(flatten(json.loads(
        (COMPONENT / "translations" / f"{language}.json").read_text(encoding="utf-8"))))
    assert translated.keys() == source.keys()
    for key, text in source.items():
        assert placeholders(translated[key]) == placeholders(text), key
