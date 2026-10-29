"""QA Agent memory as transactions: entries added from two tabs at once, stale edits, and unreadable files."""

import json
import threading

import pytest

from spec_to_test import storage
from spec_to_test.qa_agent.memory import DiskMemoryStore, MemoryEntryError, new_rule


def rule(text: str):
    return new_rule(text, ["critic"], True)


def test_rules_added_at_the_same_time_from_two_tabs_are_all_kept():
    store = DiskMemoryStore()
    errors = []

    def add(n):
        try:
            store.add("default", rule(f"Rule {n}"))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=add, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert not errors
    assert sorted(e.text for e in store.entries("default")) == sorted(f"Rule {n}" for n in range(8))


def test_a_stale_edit_does_not_erase_a_rule_another_tab_added():
    store = DiskMemoryStore()
    first = rule("First rule")
    store.add("default", first)
    stale = store.entries("default")[0]  # tab A still shows the list as it was
    store.add("default", rule("Added in tab B"))  # tab B saves a rule meanwhile
    store.update("default", stale.model_copy(update={"text": "First rule, edited"}))  # tab A saves its edit
    texts = sorted(e.text for e in store.entries("default"))
    assert texts == ["Added in tab B", "First rule, edited"]


def test_a_damaged_memory_file_is_never_overwritten():
    path = storage.memory_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(MemoryEntryError) as error:
        DiskMemoryStore().add("default", rule("New rule"))
    assert error.value.code == "unreadable"
    assert path.read_text(encoding="utf-8") == "{not json"


def test_a_memory_file_of_another_format_is_never_overwritten():
    path = storage.memory_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"format": "someone-else", "format_version": 7, "entries": []})
    path.write_text(original, encoding="utf-8")
    assert DiskMemoryStore().entries("default") == []
    with pytest.raises(MemoryEntryError):
        DiskMemoryStore().delete("default", "abc")
    assert path.read_text(encoding="utf-8") == original


def test_an_unreadable_entry_is_kept_when_another_is_deleted():
    store = DiskMemoryStore()
    keep = rule("Keep me")
    store.add("default", keep)
    store.add("default", rule("Delete me"))
    path = storage.memory_path("default")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"].append({"id": "not-an-entry", "from": "a newer version"})
    path.write_text(json.dumps(data), encoding="utf-8")
    target = next(e for e in store.entries("default") if e.text == "Delete me")
    store.delete("default", target.id)
    kept = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert {"id": "not-an-entry", "from": "a newer version"} in kept


def test_fields_a_newer_version_added_survive_an_edit_by_this_version():
    store = DiskMemoryStore()
    store.add("default", rule("Rule"))
    path = storage.memory_path("default")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["reviewer_note"] = "added later"
    path.write_text(json.dumps(data), encoding="utf-8")
    entry = store.entries("default")[0]
    store.update("default", entry.model_copy(update={"text": "Rule, edited"}))
    [saved] = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert (saved["text"], saved["reviewer_note"]) == ("Rule, edited", "added later")
