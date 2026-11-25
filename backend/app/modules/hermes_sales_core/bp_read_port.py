"""P02 read-only Hermes -> BlackPenguin business-tool adapter.

No booking, calendar lookup, asset issuance, provider messages or CRM writes.
Uses only the published/confirmed commercial snapshot from bp_context.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .bp_context import BPSnapshot
from .contracts import TurnScope
from . import sales_preferences, commercial_turn

READ_TOOLS = frozenset({
    'get_project_overview', 'search_properties', 'evaluate_properties_for_lead',
    'get_unit_details', 'compare_properties', 'list_unit_assets',
})
DRAFT_TOOLS = frozenset({'update_search_preferences'})
LOCKED_TOOLS = frozenset({
    'get_unit_media', 'get_available_visit_slots', 'select_visit_time',
    'book_onsite_visit', 'cancel_onsite_visit', 'reschedule_onsite_visit',
    'update_lead_profile', 'track_property_interest',
})


def _safe_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    import math
    return result if math.isfinite(result) else None


def _bool_filter_pass(record: dict, criteria: dict[str, Any]) -> bool | None:
    """True=matched, False=nonmatch, None=not verified.

    Never turn absent price, bedrooms, area or feature data into a match.
    """
    unknown = False
    for field, minimum, maximum in (
        ('bedrooms', 'bedrooms_min', 'bedrooms_max'),
        ('bathrooms', 'min_bathrooms', 'max_bathrooms'),
        ('area', 'min_area_sqm', 'max_area_sqm'),
    ):
        required_min = criteria.get(minimum)
        required_max = criteria.get(maximum)
        if field == 'bedrooms':
            required_min = criteria.get('bedrooms', required_min)
            required_max = criteria.get('bedrooms', required_max)
        if required_min is None and required_max is None:
            continue
        value = _safe_number(record.get(field))
        if value is None:
            unknown = True
            continue
        if required_min is not None and value < required_min:
            return False
        if required_max is not None and value > required_max:
            return False
    if criteria.get('bedrooms_any'):
        beds = _safe_number(record.get('bedrooms'))
        if beds is None:
            unknown = True
        elif beds not in set(criteria['bedrooms_any']):
            return False
    # Properties may have typed features only if they were approved. Unknown
    # kitchen/parking/backyard features do NOT match a requested feature.
    fields = {'min_parking_spaces': 'parking_spaces',
              'kitchen_layout': 'kitchen_layout', 'private_backyard': 'private_backyard'}
    for key, field in fields.items():
        requested = criteria.get(key)
        if requested is None:
            continue
        features = record.get('verified_features') or {}
        if not isinstance(features, dict) or field not in features:
            unknown = True
            continue
        actual = features[field]
        if key == 'min_parking_spaces':
            num = _safe_number(actual)
            if num is None:
                unknown = True
            elif num < requested:
                return False
        elif actual != requested:
            return False
    return None if unknown else True


class BlackPenguinReadPort:
    """A pure per-turn adapter; scope was authorized when snapshot was built."""

    def __init__(self, snapshot: BPSnapshot, *, state: dict | None = None,
                 buyer_message: str = '', enable_preference_drafts: bool = False):
        self.snapshot = snapshot
        self.state = state if state is not None else {}
        self.message = buyer_message
        self.enable_preference_drafts = bool(enable_preference_drafts)

    def invoke(self, name: str, arguments: Mapping[str, Any], scope: TurnScope) -> dict[str, Any]:
        if scope != self.snapshot.scope:
            raise PermissionError('Cross-tenant or cross-conversation Hermes tool request.')
        args = dict(arguments)
        if name == 'update_search_preferences' and self.enable_preference_drafts:
            return self._preferences_draft(args)
        if name in LOCKED_TOOLS or name == 'update_search_preferences':
            return {'error': 'This tool requires later operational integration.',
                    'error_code': 'P04_EFFECTS_DISABLED'}
        if name not in READ_TOOLS:
            raise PermissionError('Hermes tool is not allowlisted in P02.')
        if name == 'get_project_overview':
            return {'ok': True, 'company': deepcopy(self.snapshot.company),
                    'project': deepcopy(self.snapshot.project),
                    'verified_facts': deepcopy(self.snapshot.commercial.get('confirmed_project_facts') or {}),
                    'catalog_coverage': deepcopy(self.snapshot.commercial.get('catalog_coverage') or {})}
        if name == 'search_properties':
            return self._search(args)
        if name == 'evaluate_properties_for_lead':
            criteria = {}
            if args.get('max_budget_usd') is not None:
                criteria['max_price_usd'] = args['max_budget_usd']
            if args.get('min_bedrooms') is not None:
                criteria['bedrooms_min'] = args['min_bedrooms']
            # Do not infer House/Apartment from unit codes or free text typology.
            if args.get('preferred_property_type') not in (None, 'Either'):
                return {'error': 'An explicit catalog property type is required for this filter.',
                        'error_code': 'UNMAPPED_PROPERTY_TYPE'}
            if args.get('required_features'):
                return {'error': 'Unverified feature comparisons cannot be evaluated.',
                        'error_code': 'UNVERIFIED_FEATURE_FILTER'}
            return self._search({'scope': 'temporary', 'criteria': criteria})
        if name == 'get_unit_details':
            return self._details(args)
        if name == 'compare_properties':
            return self._compare(args)
        if name == 'list_unit_assets':
            return self._assets(args)
        raise AssertionError('unreachable')

    def _rows(self) -> list[dict]:
        commercial = self.snapshot.commercial
        inventory = commercial.get('inventory') or []
        # Prefer unit-level entries when present; catalog fallback must be
        # identified as a property type, not invented as an individual unit.
        has_units = commercial.get('inventory_source') == 'individual_units'
        rows = inventory if has_units else commercial.get('property_types') or []
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref = row.get('unit_code') if has_units else row.get('id')
            if not ref:
                continue
            results.append({
                'id': row.get('id'),
                'reference': str(ref),
                'kind': 'unit' if has_units else 'property_type',
                'property_type': row.get('property_type'),
                'bedrooms': row.get('bedrooms'), 'bathrooms': row.get('bathrooms'),
                'area': row.get('area') if has_units else row.get('area_min'),
                'price': row.get('price') if has_units else row.get('starting_price'),
                'currency': row.get('currency'),
                'status': row.get('status') if has_units else 'catalog_type',
                'inventory_updated_at': row.get('inventory_updated_at'),
                'available_units': row.get('available_units') if not has_units else None,
                'description': row.get('description') if not has_units else None,
                'verified_features': {},  # No typed/approved unit features in source projection.
                'availability_verified': bool(row.get('inventory_updated_at')) and
                                         row.get('status') in ('available','ready','active') if has_units else
                                         bool(row.get('inventory_updated_at') and row.get('available_units') is not None),
            })
        return results

    def _resolve(self, token: Any) -> dict | None:
        if not token or not isinstance(token, str):
            return None
        token = token.strip().casefold()
        exact = [row for row in self._rows()
                 if token == row['reference'].casefold() or token == str(row['id']).casefold()]
        return exact[0] if len(exact) == 1 else None

    def _search(self, args: dict) -> dict[str, Any]:
        raw = args.get('criteria') or {}
        if not isinstance(raw, dict) or args.get('scope') not in (None, 'temporary', 'permanent'):
            return {'error': 'Invalid search arguments.', 'error_code': 'INVALID_SEARCH'}
        allowed = {'bedrooms', 'bedrooms_any', 'bedrooms_min', 'bedrooms_max',
                   'max_price_usd', 'min_price_usd', 'min_area_sqm', 'max_area_sqm',
                   'min_bathrooms', 'max_bathrooms', 'min_parking_spaces',
                   'kitchen_layout', 'private_backyard', 'relative_price_lt', 'relative_price_gt'}
        if set(raw) - allowed:
            return {'error': 'Unsupported search fields.', 'error_code': 'INVALID_SEARCH'}
        criteria = dict(raw)
        saved_preferences = self.state.get('search_preferences') or {}
        primary = saved_preferences.get('budget') or {}
        bedrooms = saved_preferences.get('bedrooms') or {}
        if not any(k in criteria for k in ('bedrooms', 'bedrooms_any', 'bedrooms_min', 'bedrooms_max')):
            mode = bedrooms.get('mode')
            if mode == 'exact' and bedrooms.get('preferred') is not None:
                criteria['bedrooms'] = bedrooms['preferred']
            if mode in ('minimum','range') and bedrooms.get('minimum') is not None:
                criteria['bedrooms_min'] = bedrooms['minimum']
            if mode in ('maximum','range') and bedrooms.get('maximum') is not None:
                criteria['bedrooms_max'] = bedrooms['maximum']
        hard_max = primary.get('maximum_usd')
        if hard_max is not None and 'max_price_usd' not in criteria:
            criteria['max_price_usd'] = hard_max
        # A model may not silently convert a temporary higher-budget request
        # into permanent acceptance. The persisted primary budget is unchanged.
        if (args.get('scope') == 'permanent' and not (
                commercial_turn.clear_permanent_revision(self.message) or (
                    bool(sales_preferences.parse_declarations(self.message)) and
                    commercial_turn.scope(self.message, bool((self.state.get('search_preferences') or {}).get('revision', 0))) == 'permanent'
                ))):
            # Explicit lasting revisions are handled by update_search_preferences.
            return {'error': 'Permanent preferences need explicit buyer evidence.',
                    'error_code': 'PERMANENT_SCOPE_REQUIRES_EVIDENCE'}
        numeric = ('bedrooms','bedrooms_min','bedrooms_max','max_price_usd','min_price_usd',
                   'min_area_sqm','max_area_sqm','min_bathrooms','max_bathrooms',
                   'min_parking_spaces','relative_price_lt','relative_price_gt')
        if any(key in criteria and (isinstance(criteria[key], bool) or
                                    not isinstance(criteria[key], (int, float)) or
                                    _safe_number(criteria[key]) is None or
                                    criteria[key] < 0)
               for key in numeric):
            return {'error': 'Invalid numeric filters.', 'error_code': 'INVALID_SEARCH'}
        if ('bedrooms_any' in criteria and (
                not isinstance(criteria['bedrooms_any'], list) or
                not 1 <= len(criteria['bedrooms_any']) <= 20 or
                any(type(v) is not int or v < 0 for v in criteria['bedrooms_any']))):
            return {'error': 'Invalid bedroom alternatives.', 'error_code': 'INVALID_SEARCH'}
        if criteria.get('kitchen_layout') not in (None, 'open', 'closed', 'semi_open'):
            return {'error': 'Invalid kitchen selection.', 'error_code': 'INVALID_SEARCH'}
        if ('private_backyard' in criteria and type(criteria['private_backyard']) is not bool):
            return {'error': 'Invalid backyard selection.', 'error_code': 'INVALID_SEARCH'}
        for lo, hi in (('min_price_usd','max_price_usd'), ('min_area_sqm','max_area_sqm'),
                       ('min_bathrooms','max_bathrooms'),('bedrooms_min','bedrooms_max')):
            if criteria.get(lo) is not None and criteria.get(hi) is not None and criteria[lo] > criteria[hi]:
                return {'error': 'Conflicting search limits.', 'error_code': 'INVALID_SEARCH'}
        candidates = self._rows()
        good, unknown = [], []
        price_fields = ['max_price_usd', 'min_price_usd', 'relative_price_lt', 'relative_price_gt']
        needs_price = any(criteria.get(k) is not None for k in price_fields)
        for row in candidates:
            if row['kind'] == 'unit':
                status = str(row.get('status') or '').casefold()
                if status in {'sold', 'reserved', 'unavailable', 'inactive'}:
                    continue
                if not row.get('availability_verified'):
                    unknown.append(row['reference'])
                    continue
            elif row.get('available_units') == 0 and row.get('inventory_updated_at'):
                continue
            numeric_price = _safe_number(row.get('price'))
            if needs_price:
                if str(row.get('currency') or '').upper() != 'USD' or numeric_price is None:
                    unknown.append(row['reference'])
                    continue
                if (criteria.get('max_price_usd') is not None and numeric_price > criteria['max_price_usd']
                        or criteria.get('min_price_usd') is not None and numeric_price < criteria['min_price_usd']
                        or criteria.get('relative_price_lt') is not None and numeric_price >= criteria['relative_price_lt']
                        or criteria.get('relative_price_gt') is not None and numeric_price <= criteria['relative_price_gt']):
                    continue
            result = _bool_filter_pass(row, criteria)
            if result is True:
                good.append(row)
            elif result is None:
                unknown.append(row['reference'])
        preferred_beds = bedrooms.get('preferred') if bedrooms.get('mode') == 'preferred' else None
        if preferred_beds is not None and not any(k in raw for k in ('bedrooms','bedrooms_any','bedrooms_min','bedrooms_max')):
            good.sort(key=lambda row: (row.get('bedrooms') != preferred_beds, row['reference']))
        return {
            'ok': True,
            'matching_properties': deepcopy(good[:20]),
            'match_count': len(good),
            'criteria': deepcopy(criteria),
            'search_scope': args.get('scope') or 'temporary',
            'unverified_references': unknown[:30],
            'coverage_complete': not unknown and bool(self.snapshot.commercial.get('catalog_coverage', {}).get('exhaustive', False)),
            'message': ('No verified matches under the supplied filters.' if not good else 'Matching published catalog entries returned; availability may still be unverified.'),
            'rule': 'Missing information and foreign currencies are unknown, never matching or disproving these USD criteria.',
        }

    def _details(self, args: dict) -> dict[str, Any]:
        reference = args.get('unit_id')
        if not reference:
            focus = self.state.get('conversation_focus') or {}
            reference = focus.get('unit_id') or focus.get('property_type_id')
        if not reference:
            offered = self.state.get('last_presented_units') or []
            if len(offered) == 1:
                reference = offered[0]
        row = self._resolve(reference)
        if not row:
            return {'error': 'The requested property is not an unambiguous approved catalog entry.',
                    'error_code': 'PROPERTY_NOT_FOUND_OR_AMBIGUOUS'}
        return {'ok': True, 'property': deepcopy(row), 'project_name': self.snapshot.project['name'],
                'timezone': self.snapshot.project['timezone'], 'location': self.snapshot.project.get('address'),
                'rule': 'Availability is not confirmed merely by a catalog listing.',
                'availability_verified': bool(row.get('inventory_updated_at')) and row.get('status') in ('available','ready','active')}

    def _compare(self, args: dict) -> dict[str, Any]:
        ids = args.get('unit_ids')
        if not ids:
            ids = self.state.get('last_presented_units') or []
        if (not isinstance(ids, list) or not 2 <= len(ids) <= 3
                or any(not isinstance(v, str) for v in ids)
                or len(set(ids)) != len(ids)):
            return {'error': 'Select two or three distinct verified references.',
                    'error_code': 'COMPARISON_NEEDS_REFERENCES'}
        rows = [self._resolve(v) for v in ids]
        if any(row is None for row in rows):
            return {'error': 'A comparison reference is outside the approved catalog.',
                    'error_code': 'COMPARISON_REFERENCE_NOT_FOUND'}
        return {'ok': True, 'properties': deepcopy(rows),
                'note': 'Compare values only when present and in the same currency; unknown data is not zero.'}

    def _assets(self, args: dict) -> dict[str, Any]:
        details = self._details(args)
        if not details.get('ok'):
            return details
        row = details['property']
        assets = []
        for asset in self.snapshot.commercial.get('available_assets', []):
            if asset.get('coverage') is not None:
                # Unit/multi-target coverage requires the P04 coverage validator.
                continue
            name = asset.get('property_type')
            if name and row.get('property_type') != name:
                continue
            # Without explicit unit-level coverage, show discovery as potential
            # property-type material, NEVER assert verified coverage for unit.
            assets.append({'asset_id': asset['asset_id'], 'name': asset['name'],
                           'asset_type': asset['asset_type'],
                           'content_tags': list(asset.get('content_tags') or []),
                           'unit_coverage_verified': False})
        return {'ok': True, 'unit_id': row['reference'], 'assets': assets,
                'delivery': 'not_sent', 'sharing_enabled': False}

    def _preferences_draft(self, args: dict) -> dict[str, Any]:
        # Treat Hermes arguments as proposals only. Extract the actual values
        # from the CURRENT buyer message, not from the LLM's tool arguments.
        declarations = sales_preferences.parse_declarations(self.message)
        if not declarations:
            return {'error': 'The buyer has not made a clear lasting declaration.',
                    'error_code': 'PREFERENCE_EVIDENCE_REQUIRED'}
        existing = self.state.get('search_preferences') or sales_preferences.empty()
        has_primary = existing.get('revision', 0) > 0
        if commercial_turn.scope(self.message, has_primary) != 'permanent':
            return {'error': 'This is an exploratory search, not a lasting preference change.',
                    'error_code': 'TEMPORARY_SEARCH_ONLY'}
        source_id = self.state.get('_active_source_message_id')
        if not source_id:
            return {'error': 'Source message evidence is required.',
                    'error_code': 'SOURCE_MESSAGE_REQUIRED'}
        return sales_preferences.apply(self.state, declarations, source_message_id=source_id)


assert not (READ_TOOLS & LOCKED_TOOLS)
assert not (DRAFT_TOOLS & LOCKED_TOOLS)
