import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';
import { ProjectChatComponent } from './project-chat';
import { OnboardingLocationComponent } from '../../../../shared/ui/onboarding-location';

describe('Screenshot-driven onboarding journey',()=>{
  it('prioritizes the city timezone and retains explicit alternatives',()=>{
    const c=new OnboardingLocationComponent({} as never,{} as never);
    c.options={cities:[{country:'US',city:'Virginia Beach',timezone:'America/New_York'},{country:'US',city:'Los Angeles',timezone:'America/Los_Angeles'}]};
    c.country='US';c.city='Virginia Beach, Virginia';
    expect(c.zones).toEqual(['America/New_York']);c.cityChanged();expect(c.timezone).toBe('America/New_York');
    expect(c.zoneLabel(c.timezone)).toContain('America/New_York');expect(c.zoneLabel(c.timezone)).toContain('UTC');
    c.showAllZones=true;expect(c.zones).toHaveLength(2);
  });
  it('blocks type confirmation while selected images are not attached',()=>{
    const c=new ProjectChatComponent({} as never,{} as never,{detectChanges:vi.fn()} as never,{} as never,{} as never);
    const item={id:'type-1',name:'Residence'};
    c.propertyTypeImageSelection.set('type-1',new Set(['image-1']));
    expect(c.canSavePropertyType(item as any)).toBe(false);
    c.propertyTypeImageSelection.get('type-1')!.clear();expect(c.canSavePropertyType(item as any)).toBe(true);
  });
  it('keeps availability review open for unknown quantities',()=>{
    const c=new ProjectChatComponent({} as never,{} as never,{detectChanges:vi.fn()} as never,{} as never,{} as never);
    c.nextQuestion={label:'Confirm current availability'} as any;
    expect(c.propertyReviewComplete({id:'one',review_status:'confirmed',available_units:null} as any)).toBe(false);
  });
});
