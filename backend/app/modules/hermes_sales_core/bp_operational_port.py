"""P04 operational Hermes tool boundary.

The model receives verified availability and can propose actions. Every tool
invoked during inference is *read or draft only*: no provider sends, asset
shares, meetings, CRM writes, calendar changes or human cases are committed.
P04 effects have a separate, explicit simulator executor with independent DB
checks. Production routing is NOT activated by importing this module.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .bp_context import BPSnapshot
from .bp_read_port import BlackPenguinReadPort
from .choice_state import resolve_visible_choice
from .contextual_choices import choice_from_slots, explicit_date, explicit_time
from .contracts import TurnScope

P04_TOOL_NAMES = frozenset({
    'get_unit_media', 'select_visit_time', 'book_onsite_visit',
    'cancel_onsite_visit', 'reschedule_onsite_visit', 'track_property_interest',
    'update_lead_profile',
})
SLOT_DURATION_MINUTES = 60  # 45-minute visit + 15-minute buffer
SLOT_EXPIRY_MINUTES = 15
CONFIRM_EXPIRY_MINUTES = 30
AFFIRMATIVE = re.compile(
    r"\s*(?:yes,?\s+(?:i\s+)?confirm(?:\s+(?:the|my)\s+visit)?|"
    r"i\s+confirm(?:\s+(?:this|the|my)\s+(?:visit|appointment|booking))?|"
    r"yes,?\s+please\s+book\s+(?:it|the\s+visit|this\s+appointment)|"
    r"please\s+book\s+(?:it|the\s+visit|this\s+appointment)|"
    r"book\s+(?:it|the\s+visit|this\s+appointment)\s+now)\s*[.!]?\s*",
    re.I,
)
CANCEL_DIRECT = re.compile(
    r"\b(?:cancel\s+(?:my|the|this)\s+(?:appointment|booking|visit)|"
    r"i\s+want\s+to\s+cancel\s+(?:my|the|this)\s+(?:appointment|booking|visit))\b",
    re.I,
)
RESCHEDULE_DIRECT = re.compile(
    r"\b(?:reschedule\s+(?:my|the|this)\s+(?:appointment|booking|visit)|"
    r"change\s+(?:my|the|this)\s+(?:appointment|booking|visit)\s+(?:to|for))\b",
    re.I,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('An aware ISO date is required')
    return parsed.astimezone(timezone.utc)


def _fresh(payload: dict | None, now: datetime) -> bool:
    if not isinstance(payload, dict) or not payload.get('expires_at'):
        return False
    try:
        return _timestamp(payload['expires_at']) > now
    except (ValueError, TypeError):
        return False


def _result(code: str, message: str) -> dict:
    return {'error': message, 'error_code': code, 'next_action': 'Use a verified offer or ask one useful clarification.'}


def _selected_property(port: BlackPenguinReadPort) -> dict | None:
    # The CURRENT buyer goal outranks an old visit draft. Explicit named
    # catalog references outrank the current focus, which outranks a stale
    # booking draft. Never silently move an existing booked visit.
    mentioned=[]
    for row in port._rows():
        ref=row['reference']
        if (re.search(r'(?<![\w-])'+re.escape(ref)+r'(?![\w-])',port.message,re.I)
                and ref not in mentioned):
            mentioned.append(ref)
    if len(mentioned)>1:
        return None
    if len(mentioned)==1:
        return port._resolve(mentioned[0])
    focus = port.state.get('conversation_focus') or {}
    draft = port.state.get('visit_draft') or {}
    ref = focus.get('unit_id') or focus.get('property_type_id') or draft.get('unit_id')
    return port._resolve(ref)


class BPOperationalDraftPort(BlackPenguinReadPort):
    P04_DRAFT_ONLY = True
    """All LLM-facing P04 operations are previews, never external effects.

    A persisted user message is required to bind selections, cancellations and
    explicit confirmations. Arbitrary SDK args are *not* consent or auth.
    """

    def __init__(self, db, snapshot: BPSnapshot, *, state: dict, buyer_message: str,
                 inbound_message_id: str, now: datetime | None = None,
                 availability_search=None, meeting_reader=None, material_reader=None):
        if snapshot.channel != 'simulation':
            raise PermissionError('P04 operational drafts are simulation-only')
        super().__init__(snapshot, state=state, buyer_message=buyer_message,
                         enable_preference_drafts=True)
        self.db = db
        self.inbound_id = inbound_message_id
        self.now = now or _now()
        if self.now.tzinfo is None:
            raise ValueError('P04 clock must be timezone-aware')
        self.now = self.now.astimezone(timezone.utc)
        self.menus: list[dict] = []
        self._availability_search = availability_search
        self._meeting_reader = meeting_reader
        self._material_reader = material_reader

    def invoke(self, name: str, arguments: Mapping[str, Any], scope: TurnScope) -> dict[str, Any]:
        if scope != self.snapshot.scope:
            raise PermissionError('Operational scope mismatch')
        args = dict(arguments)
        if name == 'get_available_visit_slots':
            return self._slots(args)
        if name == 'get_unit_media':
            return self._media_request(args)
        if name == 'select_visit_time':
            return self._select_time(args)
        if name == 'book_onsite_visit':
            return self._book_request(args)
        if name == 'cancel_onsite_visit':
            return self._cancel_request(args)
        if name == 'reschedule_onsite_visit':
            return self._reschedule_request(args)
        if name == 'track_property_interest':
            return self._interest_draft(args)
        if name == 'update_lead_profile':
            return self._lead_draft(args)
        return super().invoke(name, args, scope)

    def _slots(self, args: dict) -> dict:
        row = _selected_property(self)
        if not row:
            return _result('PROPERTY_REQUIRED', 'Please identify the property before checking visit availability.')
        name = self.snapshot.project.get('timezone') or 'UTC'
        try:
            zone = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return _result('INVALID_PROJECT_TIMEZONE', 'The project timezone needs staff review.')
        local_now = self.now.astimezone(zone)
        text = str(args.get('date_str') or '').strip()
        requested_date = None
        if text:
            if text.lower() == 'today':
                requested_date = local_now.date()
            elif text.lower() == 'tomorrow':
                requested_date = local_now.date() + timedelta(days=1)
            elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
                try: requested_date = date.fromisoformat(text)
                except ValueError: return _result('INVALID_DATE', 'The requested date is invalid.')
            elif text.lower() not in ('next week','this week','this weekend','next weekend','upcoming days'):
                parsed = explicit_date(text, anchor_year=local_now.year)
                if parsed:
                    requested_date = date.fromisoformat(parsed)
                else:
                    return _result('UNSUPPORTED_PERIOD', 'Please specify a calendar day or upcoming days.')
        first_day=local_now.date()
        last_day=first_day+timedelta(days=14)
        if requested_date is None and text.lower() in ('this week','next week','this weekend','next weekend'):
            monday=first_day-timedelta(days=first_day.weekday())
            if text.lower()=='this week':
                first_day,last_day=local_now.date(),monday+timedelta(days=6)
            elif text.lower()=='next week':
                first_day,last_day=monday+timedelta(days=7),monday+timedelta(days=13)
            elif text.lower()=='this weekend':
                first_day,last_day=monday+timedelta(days=5),monday+timedelta(days=6)
            else:
                first_day,last_day=monday+timedelta(days=12),monday+timedelta(days=13)
            first_day=max(first_day,local_now.date())
            last_day=min(last_day,local_now.date()+timedelta(days=14))
        if requested_date is not None and not local_now.date() <= requested_date <= local_now.date()+timedelta(days=14):
            return _result('DATE_OUT_OF_RANGE', 'Please choose a date within the next 14 days.')
        preference = args.get('time_preference') or 'any'
        if preference not in {'any','morning','afternoon','evening'}:
            return _result('INVALID_TIME_PREFERENCE', 'Unsupported time window.')
        def selected(starts, ends):
            start = starts.replace(tzinfo=timezone.utc).astimezone(zone)
            if start.minute != 0 or starts.replace(tzinfo=timezone.utc) <= self.now:
                return False
            if requested_date and start.date() != requested_date:
                return False
            if not first_day <= start.date() <= last_day:
                return False
            if preference == 'morning' and start.hour >= 12:
                return False
            if preference == 'afternoon' and not 12 <= start.hour < 17:
                return False
            if preference == 'evening' and start.hour < 17:
                return False
            return True
        # The existing BP availability engine reads eligible Sales calendars.
        # No advisor details or calendar tokens are returned to Hermes.
        if self._availability_search is not None:
            rows = self._availability_search(project_id=self.snapshot.scope.project_id,
                                             now=self.now, duration_minutes=SLOT_DURATION_MINUTES,
                                             slot_predicate=selected)
        else:
            from .bp_context import require_scoped_entities
            from app.modules.onboarding_versions import require_capability
            _, project, _, _ = require_scoped_entities(self.db, self.snapshot.scope)
            require_capability(project.profile, 'appointments')
            from app.modules.sales_crm.scheduling import available_slots
            rows = available_slots(self.db, project_id=self.snapshot.scope.project_id,
                                   after=self.now.replace(tzinfo=None), days=15,
                                   duration_minutes=SLOT_DURATION_MINUTES, limit=240,
                                   slot_predicate=selected)
        options = []
        for item in rows:
            starts = item['start_at']
            if starts.tzinfo is None:
                starts = starts.replace(tzinfo=timezone.utc)
            start = starts.astimezone(zone)
            if not selected(starts.astimezone(timezone.utc).replace(tzinfo=None), starts+timedelta(minutes=60)):
                continue
            option = {'date': start.date().isoformat(), 'start_time': start.strftime('%H:%M'),
                      'starts_at_utc': starts.astimezone(timezone.utc).isoformat()}
            if option not in options:
                options.append(option)
        options = options[:80]
        proposal_id = str(uuid4())
        expires = (self.now + timedelta(minutes=SLOT_EXPIRY_MINUTES)).isoformat()
        # Draft only. Commit requires an ACTUALLY delivered matching response.
        offer = {'proposal_id': proposal_id, 'expires_at': expires, 'unit_id': row['reference'],
                 'unit_row_id': row['id'], 'property_type_id': row['id'] if row['kind']=='property_type' else None,
                 'project_id': self.snapshot.scope.project_id, 'timezone': str(zone),
                 'options': options, 'source_reply_message_id': None,
                 'source_inbound_message_id': self.inbound_id}
        self.state['last_slot_search'] = offer
        self.state['visit_draft'] = {'unit_id': row['reference'], 'date': None, 'start_time': None,
                                     'status': 'hour_needed' if requested_date else 'day_needed'}
        if requested_date:
            offered = [x for x in options if x['date']==requested_date.isoformat()]
            result = {'ok': True, 'unit_id': row['reference'], 'date': requested_date.isoformat(),
                      'timezone': str(zone), 'proposal_id': proposal_id, 'expires_at': expires,
                      'available_slots': [{'date':x['date'],'start_time':x['start_time']} for x in offered],
                      'booking_confirmed': False}
        else:
            dates = list(dict.fromkeys(x['date'] for x in options))[:6]
            result = {'ok': True, 'unit_id': row['reference'], 'timezone': str(zone),
                      'available_dates':[{'date':x} for x in dates],
                      'proposal_id': proposal_id, 'expires_at': expires,
                      'booking_confirmed': False}
        menu = choice_from_slots(result)
        if menu and len(menu.get('options') or []) >= 2:
            self.menus.append(menu)
        return result

    def _offer(self) -> dict | None:
        offer = self.state.get('last_slot_search')
        if not _fresh(offer, self.now) or offer.get('project_id') != self.snapshot.scope.project_id:
            return None
        return offer

    def _select_time(self, args: dict) -> dict:
        offer = self._offer()
        if not offer or not offer.get('source_reply_message_id'):
            return _result('DELIVERED_OFFER_REQUIRED', 'Please show a valid available time before selecting it.')
        if args.get('proposal_id') != offer['proposal_id']:
            return _result('STALE_PROPOSAL', 'The slot proposal has changed.')
        date_text, clock = args.get('date_str'), args.get('start_time')
        matched = [x for x in offer['options'] if x['date']==date_text and x['start_time']==clock]
        if len(matched) != 1:
            return _result('SLOT_NOT_OFFERED', 'This exact time was not included in the delivered offer.')
        selection = resolve_visible_choice(self.state, self.message)
        explicit = (explicit_time(self.message) == clock and
                    (explicit_date(self.message, anchor_year=int(date_text[:4])) in (None,date_text)))
        from_menu = (selection is not None and selection.get('status') == 'resolved' and
                     selection.get('type') == 'visit_time' and
                     selection.get('choice',{}).get('date') == date_text and
                     selection.get('choice',{}).get('start_time') == clock)
        if not (explicit or from_menu):
            return _result('SELECTION_EVIDENCE_REQUIRED', 'The buyer has not selected this offered date and time.')
        self.state['visit_draft'] = {'unit_id': offer['unit_id'], 'date':date_text,
                                     'start_time':clock, 'status':'selected'}
        request_id = str(uuid4())
        self.state['confirmation_request'] = {
            'id':request_id, 'kind':'book', 'status':'recap_required',
            'proposal_id':offer['proposal_id'], 'unit_id':offer['unit_id'],
            'date':date_text, 'start_time':clock, 'starts_at_utc':matched[0]['starts_at_utc'],
            'timezone':offer['timezone'], 'expires_at':(self.now+timedelta(minutes=CONFIRM_EXPIRY_MINUTES)).isoformat(),
            'selected_inbound_message_id':self.inbound_id,
        }
        return {'ok':True,'selected':{'property':offer['unit_id'],'date':date_text,
                                      'start_time':clock,'timezone':offer['timezone']},
                'booking_confirmed':False, 'next_action':'Ask for explicit confirmation of the entire property/date/time recap.'}

    def _book_request(self, args: dict) -> dict:
        proposal = self.state.get('confirmation_request') or {}
        if (proposal.get('kind') != 'book' or proposal.get('status') != 'awaiting_confirmation'
                or not _fresh(proposal,self.now) or not proposal.get('recap_message_id')):
            return _result('BOOKING_CONFIRMATION_REQUIRED', 'The full visit recap must be delivered and accepted in a later turn.')
        if (args.get('proposal_id')!=proposal.get('proposal_id') or args.get('unit_id')!=proposal.get('unit_id')
                or args.get('date_str')!=proposal.get('date') or args.get('start_time')!=proposal.get('start_time')):
            return _result('BOOKING_DETAILS_MISMATCH', 'The proposed visit differs from the confirmed recap.')
        if not AFFIRMATIVE.fullmatch(self.message):
            return _result('EXPLICIT_BOOKING_CONSENT_REQUIRED', 'The buyer has not explicitly confirmed this visit.')
        if proposal['selected_inbound_message_id']==self.inbound_id:
            return _result('SEPARATE_TURN_REQUIRED', 'The selection and confirmation must occur in separate messages.')
        self.state['confirmation_request'] = {**proposal, 'status':'execution_requested',
                                              'confirmed_inbound_message_id':self.inbound_id}
        return {'ok':True,'status':'pending_backend_commit','booking_confirmed':False,
                'next_action':'Backend must recheck availability and persist a verified receipt.'}

    def _cancel_request(self, args: dict) -> dict:
        meeting_id = args.get('meeting_id')
        if not isinstance(meeting_id,str) or len(meeting_id)>36 or not CANCEL_DIRECT.search(self.message):
            return _result('CANCELLATION_CONSENT_REQUIRED', 'The buyer must directly request cancellation.')
        meeting = self._active_meeting(meeting_id)
        if not meeting:
            return _result('MEETING_NOT_FOUND', 'The specified visit does not belong to this lead or is not active.')
        from .bp_operation_receipts import booking_fingerprint
        self.state['confirmation_request'] = {
            'id':str(uuid4()),'kind':'cancel','status':'execution_requested',
            'meeting_id':meeting_id, 'booking_sha256':booking_fingerprint(meeting),
            'confirmed_inbound_message_id':self.inbound_id,
            'expires_at':(self.now+timedelta(minutes=CONFIRM_EXPIRY_MINUTES)).isoformat(),
            'reason':(re.search(r'\bbecause\s+(.{1,300})',self.message,re.I).group(1).strip()
                      if re.search(r'\bbecause\s+(.{1,300})',self.message,re.I) else None),
        }
        return {'ok':True,'status':'pending_backend_commit','cancelled':False}

    def _reschedule_request(self, args: dict) -> dict:
        meeting_id = args.get('original_meeting_id')
        meeting = self._active_meeting(meeting_id)
        if not meeting:
            return _result('MEETING_NOT_FOUND', 'The original visit is not active or is outside this lead.')
        from .bp_operation_receipts import booking_fingerprint
        old = self.state.get('confirmation_request') or {}
        offer = self._offer()
        exact = next((x for x in (offer or {}).get('options', []) if
                      x['date']==args.get('date_str') and x['start_time']==args.get('start_time')),None)
        if not offer or not offer.get('source_reply_message_id') or not exact or args.get('proposal_id')!=offer['proposal_id'] or args.get('unit_id')!=offer['unit_id']:
            return _result('FRESH_SLOT_REQUIRED', 'Recheck a fresh offered replacement time.')
        if old.get('kind')=='reschedule' and old.get('status')=='awaiting_confirmation':
            if (old.get('meeting_id')!=meeting_id or old.get('proposal_id')!=offer['proposal_id']
                    or old.get('date')!=exact['date'] or old.get('start_time')!=exact['start_time']
                    or not old.get('recap_message_id') or not AFFIRMATIVE.fullmatch(self.message)
                    or not _fresh(old,self.now) or old.get('booking_sha256')!=booking_fingerprint(meeting)):
                return _result('RESCHEDULE_CONFIRMATION_REQUIRED', 'Confirm the delivered exact replacement recap.')
            self.state['confirmation_request']={**old,'status':'execution_requested',
                                                 'confirmed_inbound_message_id':self.inbound_id}
            return {'ok':True,'status':'pending_backend_commit','rescheduled':False}
        # Stage a recap only from a current, explicit request for a replacement.
        if not RESCHEDULE_DIRECT.search(self.message):
            return _result('RESCHEDULE_REQUEST_REQUIRED', 'The buyer must request rescheduling this visit.')
        self.state['confirmation_request']={
            'id':str(uuid4()),'kind':'reschedule','status':'recap_required',
            'meeting_id':meeting_id,'booking_sha256':booking_fingerprint(meeting),
            'proposal_id':offer['proposal_id'],'unit_id':offer['unit_id'],
            'date':exact['date'],'start_time':exact['start_time'],
            'starts_at_utc':exact['starts_at_utc'],'timezone':offer['timezone'],
            'selected_inbound_message_id':self.inbound_id,
            'expires_at':(self.now+timedelta(minutes=CONFIRM_EXPIRY_MINUTES)).isoformat(),
        }
        return {'ok':True,'status':'recap_required','rescheduled':False,
                'next_action':'Show current and replacement visits, then request explicit confirmation.'}

    def _active_meeting(self, meeting_id: str):
        if not isinstance(meeting_id,str) or len(meeting_id)>36:
            return None
        if self._meeting_reader is not None:
            row = self._meeting_reader(meeting_id)
            if (not row or row.id != meeting_id or row.lead_id != self.snapshot.scope.lead_id
                    or row.project_id != self.snapshot.scope.project_id or not row.is_demo):
                return None
            return row
        from app.modules.sales_crm.models import Meeting, MeetingStatus
        return self.db.query(Meeting).filter(
            Meeting.id==meeting_id,Meeting.lead_id==self.snapshot.scope.lead_id,
            Meeting.project_id==self.snapshot.scope.project_id,
            Meeting.is_demo.is_(True),
            Meeting.status.in_([MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED]),
        ).one_or_none()

    def _media_request(self, args: dict) -> dict:
        details = self._details(args)
        if not details.get('ok'):
            return details
        if not re.search(r'\b(?:photos?|pictures?|gallery|pdf|brochure|floor\s*plan|fact\s*sheet|documents?)\b',self.message,re.I):
            return _result('MEDIA_REQUEST_REQUIRED', 'The buyer must explicitly request a material type.')
        row = details['property']
        # A generic "PDF" is ambiguous: do not silently choose a brochure or
        # fact sheet. The lead may select a concrete resource next.
        if re.search(r'\bpdf\b',self.message,re.I) and not re.search(
                r'\b(?:brochure|floor\s*plan|fact\s*sheet)\b',self.message,re.I):
            return _result('MEDIA_TYPE_REQUIRED','Please specify a brochure, fact sheet or floor plan.')
        requested_tag = ('floor_plan' if re.search(r'floor\s*plan',self.message,re.I) else
                         'gallery_image' if re.search(r'photos?|pictures?|gallery',self.message,re.I) else
                         'brochure' if re.search(r'brochure|pdf',self.message,re.I) else 'unit_sheet')
        matches = []
        for asset in self.snapshot.commercial.get('available_assets', []):
            if requested_tag not in (asset.get('content_tags') or [asset.get('asset_type')]):
                continue
            verified = (self._material_reader(asset['asset_id'], row, requested_tag)
                        if self._material_reader is not None else
                        self._verified_material(asset['asset_id'], row, requested_tag))
            if verified:
                matches.append({'asset_id':asset['asset_id'], 'name':asset['name'], 'asset_type':asset['asset_type']})
        if not matches:
            return {'ok':True,'assets':[],'delivery':'unavailable','share_issued':False}
        self.state['offered_assets']={'pending_request':{
            'id':str(uuid4()), 'source_inbound_message_id':self.inbound_id, 'unit_id':row['reference'],
            'subject':requested_tag, 'asset_ids':[m['asset_id'] for m in matches],
            'expires_at':(self.now+timedelta(minutes=CONFIRM_EXPIRY_MINUTES)).isoformat(),
        }}
        return {'ok':True,'assets':matches,'delivery':'pending_backend_share',
                'share_issued':False,'next_action':'Backend must validate and issue links before presenting any URL.'}

    def _verified_material(self, asset_id: str, row: dict, requested_tag: str) -> bool:
        """Review exact approval, coverage, channel and file bytes; no URL issue."""
        from app.modules.projects.models import ProjectSalesAsset
        from app.modules.projects.asset_coverage import matches
        from app.modules.sales_agent.material_delivery import snapshot
        asset = self.db.query(ProjectSalesAsset).filter_by(
            id=asset_id, company_id=self.snapshot.scope.company_id,
            project_id=self.snapshot.scope.project_id,
        ).one_or_none()
        if asset is None:
            return False
        property_id = row['id'] if row['kind'] == 'property_type' else None
        unit_id = row['id'] if row['kind'] == 'unit' else None
        subject = 'photos' if requested_tag == 'gallery_image' else requested_tag
        coverage = matches(asset, property_id=property_id, unit_id=unit_id, subject=subject)
        if not any(c['coverage'] == 'requested_tag' for c in coverage):
            return False
        try:
            snapshot(asset, channel='sms')
        except (ValueError, OSError):
            return False
        return True

    def _interest_draft(self, args: dict) -> dict:
        row = self._resolve(args.get('unit_id'))
        if not row or args.get('status') not in {'discussed','considering','interested'}:
            return _result('PROPERTY_NOT_APPROVED', 'Property interest must refer to an approved catalog item.')
        # A model suggestion alone is never an interest declaration.
        if args['status']=='interested' and not re.search(r'\b(?:i(?:\s+am|\x27m)\s+interested|i\s+like|i\s+prefer)\b',self.message,re.I):
            return _result('INTEREST_EVIDENCE_REQUIRED', 'The buyer did not express interest.')
        values = self.state.setdefault('property_interests', [])
        if not isinstance(values,list) or len(values)>50:
            return _result('INTEREST_HISTORY_LIMIT', 'The interest history needs review.')
        entry = {'unit_id':row['reference'],'status':args['status'],
                 'source_inbound_message_id':self.inbound_id}
        if entry not in values:
            values.append(entry)
        return {'ok':True,'interest':entry,'crm_updated':False}

    def _lead_draft(self, args: dict) -> dict:
        # Explicitly hold pending CRM updates for a later verified profile writer;
        # do not accept identity/contact fields from LLM tool arguments.
        return {'ok':False,'error':'Profile changes require verified buyer evidence and a CRM write contract.',
                'error_code':'CRM_WRITE_DISABLED','next_action':'Continue conversation using verified lead context.'}
