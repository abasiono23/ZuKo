"""Zuko's spending categories and the keyword rules used to tag them.

Keywords cover English, Nigerian Pidgin and campus slang. Matching is on whole
words / phrases, so "data" does not match inside "database".
"""

import re
from enum import Enum


class Category(str, Enum):
    FOOD = "food"
    TRANSPORT = "transport"
    DATA_AIRTIME = "data_airtime"
    SCHOOL_MATERIALS = "school_materials"
    DUES = "dues"
    ACCOMMODATION = "accommodation"
    PERSONAL_LEISURE = "personal_leisure"
    INCOME = "income"
    OTHER = "other"


LABELS: dict[Category, str] = {
    Category.FOOD: "Food & Chow",
    Category.TRANSPORT: "Campus Transport",
    Category.DATA_AIRTIME: "Mobile Data & Airtime",
    Category.SCHOOL_MATERIALS: "School Materials & Prints",
    Category.DUES: "Departmental & Hall Dues",
    Category.ACCOMMODATION: "Accommodation & Power",
    Category.PERSONAL_LEISURE: "Personal & Leisure",
    Category.INCOME: "Income",
    Category.OTHER: "Miscellaneous",
}

# Order matters: the first category with a hit wins, so more specific groups come first.
KEYWORDS: dict[Category, list[str]] = {
    Category.INCOME: [
        "allowance", "salary", "stipend", "got paid", "received", "receive", "credited", "credit alert",
        "payout", "refund", "send me", "sent me", "dash me", "gave me", "give me", "scholarship",
        "bursary", "gig payment", "freelance", "pocket money",
    ],
    Category.DATA_AIRTIME: [
        "data", "airtime", "recharge", "subscription", "mtn", "glo", "airtel", "9mobile",
        "bundle", "wifi", "router", "mifi",
    ],
    Category.TRANSPORT: [
        "keke", "keke napep", "okada", "bike", "bolt", "uber", "indrive", "taxi", "cab", "brt", "danfo",
        "bus", "shuttle", "transport", "t-fare", "tfare", "fare", "drop", "ride", "train", "lamata",
        "fuel", "petrol",
    ],
    Category.SCHOOL_MATERIALS: [
        "handout", "handouts", "textbook", "textbooks", "book", "books", "print", "printed", "printing", "prints",
        "photocopy", "photocopied", "photocopies", "biro", "pen", "notebook", "lab manual", "manual", "course pack",
        "stationery", "calculator", "lab coat", "project", "typing", "binding", "bookshop",
    ],
    Category.ACCOMMODATION: [
        "rent", "hostel", "gas", "generator", "gen", "nepa", "light", "electricity", "power", "token",
        "prepaid", "water", "laundry", "detergent", "toiletries", "soap",
    ],
    Category.DUES: [
        "dues", "levy", "registration", "reg fee", "school fees", "tuition", "acceptance fee",
        "departmental", "faculty", "association", "exco", "hall dues",
    ],
    Category.PERSONAL_LEISURE: [
        "cinema", "movie", "movies", "film", "party", "outing", "hangout", "club", "drinks", "beer",
        "netflix", "spotify", "showmax", "game", "games", "betting", "bet", "gift", "birthday",
        "date night", "haircut", "barbing", "salon", "makeup", "clothes", "shoe", "shoes", "skincare",
    ],
    Category.FOOD: [
        "food", "chow", "chop", "lunch", "dinner", "breakfast", "brunch", "supper", "snack", "snacks",
        "rice", "jollof", "fried rice", "amala", "eba", "fufu", "pounded yam", "semo", "beans", "moi moi",
        "suya", "shawarma", "pizza", "burger", "chicken", "meat", "fish", "plantain", "dodo", "indomie",
        "noodles", "spaghetti", "bread", "egg", "eggs", "akara", "pap", "ogi", "garri", "gala", "puff puff",
        "buns", "meat pie", "chin chin", "yoghurt", "zobo", "drink", "water bottle", "pure water",
        "sachet water", "malt", "coke", "fanta", "cafeteria", "caf", "canteen", "buka", "mama put",
        "restaurant", "eatery", "chicken republic", "kfc", "dominos", "mr biggs", "tantalizers",
        "foodstuff", "groceries", "provisions", "market",
    ],
}

_PATTERNS: list[tuple[Category, re.Pattern[str]]] = [
    (cat, re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(words, key=len, reverse=True)) + r")\b", re.I))
    for cat, words in KEYWORDS.items()
]


def categorize(text: str, default: Category = Category.OTHER) -> Category:
    """Return the best keyword category for a free-text description."""
    for cat, pattern in _PATTERNS:
        if pattern.search(text):
            return cat
    return default


def label(cat: Category | str) -> str:
    return LABELS.get(Category(cat), str(cat))
