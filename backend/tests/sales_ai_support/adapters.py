"""Scripted model/provider boundaries; no sockets or production credentials."""
from collections import deque
from copy import deepcopy
from datetime import timezone
import json


def captured(value):
    """Record call arguments without copying DB sessions or credential objects."""
    if isinstance(value,dict):
        return {str(k):('[redacted]' if any(s in str(k).lower() for s in ('secret','token','api_key','password')) else captured(v)) for k,v in value.items()}
    if isinstance(value,(tuple,list)):
        return [captured(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)):
        return value
    return {'object_type':type(value).__name__}


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.requests = []

    async def __call__(self, *args, **kwargs):
        self.requests.append(captured({'args':args, 'kwargs':kwargs}))
        if not self.responses:
            raise AssertionError('Unscripted inference; no provider fallback is allowed.')
        value = self.responses.popleft()
        if isinstance(value, BaseException):
            raise value
        if hasattr(value, 'model_dump_json'):
            return value.model_dump_json()
        return json.dumps(value) if isinstance(value, dict) else value


class RecordingMessenger:
    """Acceptance is not delivery. Only receipt() produces a delivered status."""
    def __init__(self):
        self.calls, self.receipts = [], {}
        self.failures = deque()

    async def __call__(self, *args, **kwargs):
        if self.failures:
            raise self.failures.popleft()
        sid = 'offline-message-'+str(len(self.calls)+1)
        self.calls.append(captured({'sid':sid,'args':args,'kwargs':kwargs}))
        self.receipts[sid] = 'sent'
        return {'sid':sid, 'status':'sent'}

    def receipt(self, sid, status='delivered'):
        if sid not in self.receipts:
            raise KeyError('Unknown simulated delivery.')
        if status not in {'delivered','read','failed'}:
            raise ValueError('Unsupported simulated receipt.')
        self.receipts[sid] = status


class FakeCalendar:
    """Synthetic external busy intervals, including errors and duplicate calls.

    This fake does not implement the application's booking transaction or imply
    that production rescheduling has been implemented.
    """
    def __init__(self):
        self.events, self.calls, self.failures = {}, [], deque()

    @staticmethod
    def aware(value):
        if value.tzinfo is None:
            raise ValueError('Calendar test intervals require timezones.')
        return value.astimezone(timezone.utc)

    def busy(self, user_id, start, end):
        start, end = self.aware(start), self.aware(end)
        if start >= end:
            raise ValueError('Invalid interval.')
        return [deepcopy(e) for e in self.events.values()
                if e['user_id']==user_id and e['start']<end and e['end']>start]

    def create(self, user_id, start, end, *, key):
        start, end = self.aware(start), self.aware(end)
        self.calls.append(('create',key))
        if self.failures:
            raise self.failures.popleft()
        value = {'user_id':user_id,'start':start,'end':end,'provider_id':'offline-calendar-'+key}
        if key in self.events:
            if self.events[key] != value:
                raise ValueError('A simulated request key was reused with different details.')
            return deepcopy(self.events[key])
        if self.busy(user_id,start,end):
            raise ValueError('Simulated external Calendar conflict.')
        self.events[key] = value
        return deepcopy(value)

    def delete(self, key):
        self.calls.append(('delete',key))
        if self.failures:
            raise self.failures.popleft()
        self.events.pop(key, None)
