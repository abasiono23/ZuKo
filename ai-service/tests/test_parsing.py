from datetime import date

import pytest

from app.categories import Category
from app.parsing.rules import parse

REF = date(2024, 10, 24)  # a Thursday


def test_design_example_two_items():
    items, _ = parse("I spent ₦2,000 on lunch at Moremi cafeteria and ₦1,500 on Keke transport today", REF)
    assert [(i.amount, i.category) for i in items] == [(2000, Category.FOOD), (1500, Category.TRANSPORT)]
    assert items[0].merchant == "Moremi Cafeteria"
    assert all(i.date == REF for i in items)


@pytest.mark.parametrize("text,amount", [
    ("chop 1.5k", 1500), ("N500 keke", 500), ("NGN 2,500 data", 2500), ("2000 naira for rice", 2000),
    ("shawarma 2.5K", 2500), ("₦12,000 rent", 12000),
])
def test_amount_formats(text, amount):
    items, _ = parse(text, REF)
    assert items[0].amount == amount


def test_pidgin_and_slang_categories():
    items, _ = parse("chop 1.5k, keke 200, mtn data 2k yesterday", REF)
    assert [i.category for i in items] == [Category.FOOD, Category.TRANSPORT, Category.DATA_AIRTIME]
    assert all(i.date == date(2024, 10, 23) for i in items)


def test_income_is_credit():
    items, _ = parse("my papa send me 30k via kuda", REF)
    assert items[0].direction == "credit" and items[0].category == Category.INCOME
    assert items[0].payment_method == "kuda"


def test_ignores_course_codes_and_data_sizes():
    items, _ = parse("printed PHY 202 handout 800 cash, bought 10GB data for 2500 naira", REF)
    assert [i.amount for i in items] == [800, 2500]
    assert items[0].category == Category.SCHOOL_MATERIALS


def test_clause_without_amount_joins_next():
    items, _ = parse("rice and beans 1500 at mama cass", REF)
    assert len(items) == 1 and items[0].category == Category.FOOD


def test_weekday_resolves_to_past_date():
    items, _ = parse("cinema 4000 on Saturday", REF)
    assert items[0].date == date(2024, 10, 19)


def test_no_amount_gives_note():
    items, notes = parse("had lunch with friends", REF)
    assert items == [] and notes
