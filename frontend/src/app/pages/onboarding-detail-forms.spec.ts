import '@angular/compiler';
import { describe,it,expect,vi } from 'vitest';
import { OnboardingDetailEditor } from '../shared/ui/onboarding-detail-editor';

describe('Scoped delivery and parking forms',()=>{
 it('requires an explicit scope and preserves month precision',()=>{
   const c=new OnboardingDetailEditor();c.field='delivery_dates';c.currentValue='Dec 2026';c.ngOnChanges();expect(c.valid).toBe(false);
   c.deliveries[0]={scope:'phase',reference:'North',timing:'2026-12',precision:'month'};const save=vi.fn();c.saved.subscribe(save);c.submit();
   expect(save).toHaveBeenCalledWith({field:'delivery_dates',deliveries:[{scope:'phase',reference:'North',timing:'2026-12'}]});
 });
 it('round-trips human-readable scoped dates without defaulting a day',()=>{
   const c=new OnboardingDetailEditor();c.currentValue={phase:'North',delivery:'Dec 2026'};expect(c.previousText).toBe('phase: North; delivery: Dec 2026');const rows=c.parseDates('Phase: North — December 2026\nUnit: U001 — February 14, 2027');
   expect(rows.map(row=>row.timing)).toEqual(['2026-12','2027-02-14']);expect(rows.map(row=>row.precision)).toEqual(['month','date']);
 });
 it('restores a deferred form and does not treat blank parking as absent',()=>{
   const c=new OnboardingDetailEditor();c.field='parking_and_storage';c.records={'field:parking_and_storage':{deferred:false,resumed:true,draft:{parking:{applies_to:'Residence A',garage:'2-car garage included'}}}};c.ngOnChanges();
   expect(c.parking['garage']).toBe('2-car garage included');expect(c.valid).toBe(true);
   c.parking['garage']='';expect(c.valid).toBe(false);
 });
});
