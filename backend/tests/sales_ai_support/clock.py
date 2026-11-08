from datetime import datetime, timedelta, timezone


class FrozenClock:
    """Explicit UTC clock; production globals are patched only when requested."""
    def __init__(self, instant='2026-11-08T13:23:42+00:00'):
        self.instant = datetime.fromisoformat(instant) if isinstance(instant, str) else instant
        if self.instant.tzinfo is None:
            raise ValueError('The test clock requires an aware instant.')
        self.instant = self.instant.astimezone(timezone.utc)

    def now(self, tz=timezone.utc):
        return self.instant.astimezone(tz) if tz else self.instant.replace(tzinfo=None)

    def utcnow(self):
        return self.instant.replace(tzinfo=None)

    def advance(self, **delta):
        amount = timedelta(**delta)
        if amount.total_seconds() < 0:
            raise ValueError('Use a new clock rather than moving evidence backwards.')
        self.instant += amount
        return self.instant

    def install(self, monkeypatch, *modules):
        clock = self
        class ControlledDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.now(tz)

            @classmethod
            def utcnow(cls):
                return clock.utcnow()
        for module in modules:
            monkeypatch.setattr(module, 'datetime', ControlledDatetime)
        # Bound ORM Column defaults are NOT patched. Seed their timestamps explicitly.
