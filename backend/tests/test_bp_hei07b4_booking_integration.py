"""Real ORM scheduling regression, no external provider or production DB."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_native_reservation_uses_internal_capacity_and_defers_google(monkeypatch):
    import app.db.base  # noqa: F401
    from app.db.postgres import Base
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project, ProjectProfile
    from app.modules.users.models import User, UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import CalendarConnection, Lead, Meeting, SalesAvailabilityBlock
    from app.modules.sales_crm import scheduling as s

    def forbidden(*args, **kwargs):
        pytest.fail('Provider must not be read or written in the deferred reservation lane')
    for name in ('calendar_busy_ranges', 'is_calendar_free', 'create_calendar_event_for_connection'):
        monkeypatch.setattr(s, name, forbidden)

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine, autoflush=False) as db:
            company=Company(name='Native schedule fixture',country_code='US',is_active=True)
            db.add(company);db.flush()
            project=Project(company_id=company.id,name='Test Homes',address='100 Test St',
                timezone='UTC',country='US',is_active=True,is_demo=False)
            project.profile=ProjectProfile(profile_data={},field_states={},final_approved=True)
            db.add(project);db.flush()
            starts=(datetime.now(timezone.utc)+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0,tzinfo=None)
            advisors=[];leads=[]
            for index in range(2):
                user=User(company_id=company.id,email=f'calendar-{index}@example.invalid',first_name='Test',
                    last_name=f'Sales {index}',hashed_password='OFFLINE',role=UserRole.SALES,is_active=True)
                db.add(user);db.flush();advisors.append(user)
                db.add(ProjectUserAssignment(project_id=project.id,user_id=user.id,responsibility='sales',
                    sales_enabled=True,is_active=True,accepts_appointments=True))
                db.add(SalesAvailabilityBlock(user_id=user.id,starts_at=starts,ends_at=starts+timedelta(hours=1),timezone='UTC'))
            # Intentionally invalid ciphertext: the scheduling lane must never decrypt it.
            db.add(CalendarConnection(user_id=advisors[0].id,provider='google',status='connected',
                calendar_id='fixture',access_token_ciphertext='not-a-real-secret',refresh_token_ciphertext='not-a-real-secret'))
            for index in range(3):
                lead=Lead(company_id=company.id,project_id=project.id,full_name=f'Buyer {index}',
                    phone=f'+1555010000{index}',source='manual',consent_status='granted',is_demo=False)
                db.add(lead);leads.append(lead)
            db.commit()
            kwargs=dict(project_id=project.id,starts_at=starts,duration_minutes=60)
            assert set(s.eligible_users_for_slot(db,**kwargs))=={u.id for u in advisors}
            slots=s.available_slots(db,project_id=project.id,after=starts-timedelta(minutes=30),
                duration_minutes=60,days=1,limit=5)
            assert len(slots)==1 and slots[0]['eligible_sales_users']==2
            first,_=s.create_agent_appointment(db,lead=leads[0],starts_at=starts,duration_minutes=60,
                modality='showroom',defer_calendar=True,required_sales_user_id=advisors[0].id,emit_notification=False)
            db.commit()
            assert first.calendar_sync_status=='pending'
            assert s.eligible_users_for_slot(db,**kwargs)==[advisors[1].id]
            second,_=s.create_agent_appointment(db,lead=leads[1],starts_at=starts,duration_minutes=60,
                modality='showroom',defer_calendar=True,required_sales_user_id=advisors[1].id,emit_notification=False)
            db.commit()
            assert second.calendar_sync_status=='not_connected'
            assert s.eligible_users_for_slot(db,**kwargs)==[]
            with pytest.raises(HTTPException) as failure:
                s.create_agent_appointment(db,lead=leads[2],starts_at=starts,duration_minutes=60,
                    modality='showroom',defer_calendar=True,emit_notification=False)
            assert failure.value.status_code==409
            db.rollback()
            assert db.query(Meeting).count()==2
    finally:
        engine.dispose()
