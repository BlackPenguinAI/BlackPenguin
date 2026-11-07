"""Structured input, stable human-readable storage in existing approved profile fields."""
import calendar
import re
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class DeliveryEntry(BaseModel):
    scope: Literal['project','phase','property_type','unit']
    reference: str = Field(default='',max_length=150)
    timing: str = Field(pattern=r'^\d{4}-\d{2}(-\d{2})?$')

    @model_validator(mode='after')
    def validate_entry(self):
        self.reference=self.reference.strip()
        if any(ord(char)<32 for char in self.reference) or ' — ' in self.reference:
            raise ValueError('Use a single-line phase, type or unit reference.')
        if self.scope!='project' and not self.reference:
            raise ValueError('Identify the phase, property type or unit for this delivery date.')
        if self.scope=='project' and self.reference:
            raise ValueError('A Project-wide date must not name a phase, type or unit.')
        date.fromisoformat(self.timing+'-01' if len(self.timing)==7 else self.timing)
        return self


class ParkingDetails(BaseModel):
    applies_to: str = Field(min_length=1,max_length=150)
    garage: str = Field(default='',max_length=1000)
    assigned_spaces: str = Field(default='',max_length=1000)
    visitor_parking: str = Field(default='',max_length=1000)
    storage: str = Field(default='',max_length=1000)
    conditions: str = Field(default='',max_length=2000)


class DetailDecision(BaseModel):
    field: Literal['delivery_dates','parking_and_storage']
    question_message_id: str
    client_message_id: str = Field(min_length=36,max_length=36)
    deliveries: list[DeliveryEntry] = Field(default_factory=list,max_length=100)
    parking: ParkingDetails | None = None

    def formatted_value(self):
        if self.field=='delivery_dates':
            if not self.deliveries or self.parking:
                raise ValueError('Add at least one scoped delivery date.')
            seen=set();lines=[]
            for entry in self.deliveries:
                key=(entry.scope,entry.reference.casefold())
                if key in seen:raise ValueError('Use one delivery date per scope/reference, or clarify distinct phases or units.')
                seen.add(key)
                label={'project':'Project','phase':'Phase','property_type':'Property type','unit':'Unit'}[entry.scope]
                if entry.reference:label+=': '+entry.reference
                parts=[int(value) for value in entry.timing.split('-')]
                timing=f'{calendar.month_name[parts[1]]} {parts[0]:04d}' if len(parts)==2 else f'{calendar.month_name[parts[1]]} {parts[2]:02d}, {parts[0]:04d}'
                lines.append(label+' — '+timing)
            return '\n'.join(lines)
        if not self.parking or self.deliveries:raise ValueError('Provide parking/storage details separately from delivery dates.')
        labels={'garage':'Garage','assigned_spaces':'Assigned spaces','visitor_parking':'Visitor parking','storage':'Storage','conditions':'Inclusion, pricing and conditions'}
        details=[label+': '+re.sub(r'\s+', ' ',getattr(self.parking,key)).strip() for key,label in labels.items() if getattr(self.parking,key).strip()]
        if not details:raise ValueError('Provide at least one confirmed parking or storage detail, or choose Not applicable / Complete later.')
        if not self.parking.applies_to.strip():raise ValueError('Specify what these details apply to.')
        return 'Applies to: '+re.sub(r'\s+', ' ',self.parking.applies_to).strip()+'\n'+'\n'.join(details)
