"""Tests for EVAL-01: SQuAD normalization and the multi-person splitter.

The two named guards are test_maclennan_not_split and test_pub015_pub099_split.

The guard is not cosmetic. Unguarded, the lowercase->uppercase rule splits
`Rosannagh MacLennan` into "Rosannagh Mac" + "Lennan" and turns a correct
answer into a wrong one — a scoring bug that would look like a model failure.
"""

from __future__ import annotations

from ogr.common.names import (
    GUARDED_PREFIXES,
    normalize_answer,
    normalized_name_set,
    split_multi_person,
    tokenize,
)


class TestNormalization:
    def test_lowercases_and_strips_punctuation(self):
        assert normalize_answer("Men's Marathon!") == "mens marathon"

    def test_drops_articles(self):
        assert normalize_answer("The United States") == "united states"
        assert normalize_answer("A Coruña") == "coruna"  # accents folded too

    def test_collapses_whitespace(self):
        assert normalize_answer("  United   States \n") == "united states"

    def test_empty_input(self):
        assert normalize_answer("") == ""

    def test_numeric_answers_survive(self):
        assert normalize_answer("26") == "26"

    def test_tokenize_uses_the_same_normalization(self):
        assert tokenize("The Men's Marathon") == ["mens", "marathon"]


class TestMacLennanGuard:
    """test_maclennan_not_split — pub-067."""

    def test_maclennan_not_split(self):
        assert split_multi_person("Rosannagh MacLennan") == ["Rosannagh MacLennan"]

    def test_every_guarded_prefix_holds(self):
        samples = {
            "Mac": "Rosannagh MacLennan",
            "Mc": "Paul McCartney",
            "Van": "Ruud van Nistelrooy",
            "Di": "Joe DiMaggio",
            "De": "Kevin De Bruyne",
            "Le": "Thierry LeBlanc",
            "La": "Tony LaRussa",
            "O'": "Sinead O'Connor",
        }
        assert set(samples) == set(GUARDED_PREFIXES), "A guarded prefix has no sample"
        for prefix, name in samples.items():
            assert split_multi_person(name) == [name], f"{prefix} guard failed on {name}"

    def test_guarded_name_still_splits_from_a_second_person(self):
        """The guard protects the particle, it does not disable splitting."""
        assert split_multi_person("Rosannagh MacLennanJane Smith") == [
            "Rosannagh MacLennan",
            "Jane Smith",
        ]


class TestMultiPersonSplit:
    """test_pub015_pub099_split — the two genuine concatenations."""

    def test_pub015_shaped_concatenation_splits(self):
        assert split_multi_person("Jane SmithJohn Doe") == ["Jane Smith", "John Doe"]

    def test_pub099_shaped_three_way_concatenation_splits(self):
        assert split_multi_person("Ann BlakeBeth CarrCarl Dunn") == [
            "Ann Blake",
            "Beth Carr",
            "Carl Dunn",
        ]

    def test_single_answers_are_one_element_sets(self):
        for answer in ("Usain Bolt", "26", "Men's marathon", "United States", "1964"):
            assert split_multi_person(answer) == [answer]

    def test_name_set_is_order_independent(self):
        assert normalized_name_set("Jane SmithJohn Doe") == normalized_name_set(
            "John DoeJane Smith"
        )

    def test_empty_input(self):
        assert split_multi_person("") == []
        assert normalized_name_set("") == frozenset()
