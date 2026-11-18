"""Offline regression for confirmed-appointment scoring version overflow."""
import unittest
from types import SimpleNamespace as NS
from app.modules.sales_crm.models import LeadScoreSnapshot
from app.modules.sales_agent.profile_intelligence import (VERSION,CONFIRMED_SCORING_VERSION,update)

class _Query:
    def __init__(self,confirmed):self.confirmed=confirmed
    def filter(self,*args,**kwargs):return self
    def filter_by(self,**kwargs):return self
    def first(self):return ('synthetic-meeting',) if self.confirmed else None
    def all(self):return []

class _DB:
    def __init__(self,confirmed):self.confirmed=confirmed;self.rows=[]
    def query(self,*args):return _Query(self.confirmed)
    def add_all(self,rows):self.rows.extend(rows)

class TestConfirmedScoringVersion(unittest.TestCase):
    def lead(self):
        return NS(id='synthetic-lead',project_id='synthetic-project',created_at=None,
                  external_lead_id=None,meta_form_data={},lead_profile_data={},
                  assigned_segment=None,buyer_type=None,intent_score=None,intent_tier=None)
    def test_both_persisted_variants_fit_the_database_column(self):
        maximum=LeadScoreSnapshot.__table__.c.scoring_version.type.length
        self.assertEqual(maximum,40)
        self.assertLessEqual(len(VERSION),maximum)
        self.assertLessEqual(len(CONFIRMED_SCORING_VERSION),maximum)
        self.assertNotEqual(VERSION,CONFIRMED_SCORING_VERSION)
    def test_confirmed_meeting_uses_short_version(self):
        db=_DB(True)
        row=update(db,self.lead(),commercial={'inventory':[],'property_types':[]},message_count=1)
        self.assertEqual(row.scoring_version,CONFIRMED_SCORING_VERSION)
        self.assertEqual(len(db.rows),2)
    def test_regular_lead_keeps_original_version(self):
        db=_DB(False)
        row=update(db,self.lead(),commercial={'inventory':[],'property_types':[]},message_count=1)
        self.assertEqual(row.scoring_version,VERSION)
        self.assertEqual(len(db.rows),2)

if __name__=='__main__':unittest.main(verbosity=2)
