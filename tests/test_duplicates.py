from spec_to_test.duplicates import NEAR_THRESHOLD, find_duplicates
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import Requirement


def req(n: int, text: str) -> Requirement:
    return Requirement(id=f"REQ-{n}", text=text, has_explicit_id=True)


def test_identical_wording_is_an_exact_duplicate():
    [pair] = find_duplicates([req(1, "The password must be at least 8 characters long."),
                              req(2, "The password must be at least 8 characters long.")])
    assert (pair.first_id, pair.second_id, pair.exact, pair.similarity) == ("REQ-1", "REQ-2", True, 1.0)


def test_case_punctuation_and_spacing_are_ignored():
    [pair] = find_duplicates([req(1, "The password must be at least 8 characters long."),
                              req(2, "the  PASSWORD must be at least 8 characters long")])
    assert pair.exact


def test_a_copy_with_one_word_changed_is_a_near_duplicate():
    [pair] = find_duplicates([
        req(1, "The user must be able to reset the password from the login page."),
        req(2, "The user must be able to reset the password from the sign-in page."),
    ])
    assert not pair.exact
    assert NEAR_THRESHOLD <= pair.similarity < 1.0


def test_different_rules_on_the_same_topic_are_not_duplicates():
    assert find_duplicates([
        req(1, "The password must be at least 8 characters long."),
        req(2, "The password must contain at least one digit."),
        req(3, "The password must not be the same as the email address."),
    ]) == []


def test_a_requirement_is_never_paired_with_itself():
    assert find_duplicates([req(1, "The system must save drafts."), req(1, "The system must save drafts.")]) == []


def test_empty_wording_is_not_compared():
    assert find_duplicates([req(1, "..."), req(2, "...")]) == []


def test_pairs_follow_document_order():
    pairs = find_duplicates([
        req(1, "Users must log in with email."), req(2, "Sessions expire after 30 minutes."),
        req(3, "Users must log in with email."), req(4, "Users must log in with email"),
    ])
    assert [(p.first_id, p.second_id) for p in pairs] == [("REQ-1", "REQ-3"), ("REQ-1", "REQ-4"), ("REQ-3", "REQ-4")]


def test_the_example_document_has_no_duplicates(example_text):
    assert find_duplicates(extract_requirements(example_text)) == []
