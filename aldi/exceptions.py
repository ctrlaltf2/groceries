"""
Scraper exceptions
"""
class FailedButRetrying(BaseException):
    pass


class ScraperNeedsHumanIntervention(BaseException):
    pass
