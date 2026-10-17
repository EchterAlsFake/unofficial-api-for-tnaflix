from enum import StrEnum


class Sort(StrEnum):
    Sort_relevance = "relevance"
    Sort_recent = "recent"
    Sort_most_viewed = "views"
    Sort_top_rated = "rating"
    Sort_longest = "duration"


class SortDate(StrEnum):
    Sort_all = "all"
    Sort_today = "today"
    Sort_week = "week"
    Sort_month = "month"
    Sort_year = "year"
