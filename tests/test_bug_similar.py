from spec_to_test.bug_generator.models import ProductBugReport
from spec_to_test.bug_generator.similar import MAX_MATCHES, find_similar


def bug(n: int, title: str, what: str = "", where: str = "", actual: str = "") -> ProductBugReport:
    return ProductBugReport(id=f"BR-{n:03d}", title=title, what=what, where=where, actual_result=actual)


def test_the_same_bug_written_again_is_a_possible_duplicate():
    saved = [bug(1, "Checkout fails with a 500 error", where="Cart page", actual="The order is not created")]
    draft = bug(2, "Checkout fails with error 500", where="Cart page", actual="Order is not created")
    [match] = find_similar(draft, saved)
    assert (match.report_id, match.title) == ("BR-001", "Checkout fails with a 500 error")
    assert match.similarity >= 0.5


def test_an_unrelated_bug_is_not_a_match():
    saved = [bug(1, "Login button is hidden on mobile", where="Login page")]
    assert find_similar(bug(2, "Export to CSV drops the last row", where="Reports"), saved) == []


def test_shared_common_words_alone_do_not_make_a_match():
    saved = [bug(1, "The problem with the page", actual="The page is blank")]
    draft = bug(2, "The problem with the cart", actual="The cart is empty")
    assert find_similar(draft, saved) == []


def test_a_report_is_never_compared_with_itself():
    report = bug(1, "Checkout fails with a 500 error")
    assert find_similar(report, [report]) == []


def test_a_report_without_words_matches_nothing():
    assert find_similar(bug(2, "", what=""), [bug(1, "Checkout fails")]) == []


def test_matches_are_most_similar_first_and_limited():
    draft = bug(9, "Search returns no results for cyrillic input")
    saved = [bug(n, "Search returns no results for cyrillic input " + extra)
             for n, extra in enumerate(["", "again", "today", "again today", "x"], start=1)]
    matches = find_similar(draft, saved)
    assert len(matches) == MAX_MATCHES
    assert [m.similarity for m in matches] == sorted((m.similarity for m in matches), reverse=True)
