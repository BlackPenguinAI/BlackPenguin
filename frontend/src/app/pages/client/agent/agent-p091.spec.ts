import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { AgentP091Component } from './agent-p091';

function component(): AgentP091Component {
  const value = new AgentP091Component(
    {} as any,
    { markForCheck: () => undefined } as any,
    { snapshot: { queryParamMap: { get: () => null } } } as any,
  );
  value.loading = false;
  return value;
}

describe('P09.1 Agent stale selection', () => {
  it('clears selected deleted lead, messages and context when the server inbox no longer contains it', () => {
    const value = component();
    value.selected = { id: 'deleted', lead_id: 'old-lead' };
    value.conversations = [];
    value.messages = [{ content: 'old private message' }];
    value.slots = [{ start_at: '2026-11-26T10:00:00Z' }];
    value.selectedSlot = 'old';
    value.reviewNote = 'old evidence';
    value.ngDoCheck();
    expect(value.selected).toBeNull();
    expect(value.messages).toEqual([]);
    expect(value.slots).toEqual([]);
    expect(value.selectedSlot).toBe('');
    expect(value.reviewNote).toBe('');
    expect(value.setupOpen).toBe(true);
  });

  it('keeps the active selection when unrelated leads disappear', () => {
    const value = component();
    value.selected = { id: 'kept' };
    value.conversations = [{ id: 'kept' }];
    value.messages = [{ content: 'current' }];
    value.ngDoCheck();
    expect(value.selected.id).toBe('kept');
    expect(value.messages).toHaveLength(1);
  });

  it('does not clear a selection while the initial inbox is loading', () => {
    const value = component();
    value.loading = true;
    value.selected = { id: 'unresolved' };
    value.conversations = [];
    value.ngDoCheck();
    expect(value.selected.id).toBe('unresolved');
  });

  it('keeps the workspace available when another conversation remains', () => {
    const value = component();
    value.selected = { id: 'deleted' };
    value.conversations = [{ id: 'surviving' }];
    value.ngDoCheck();
    expect(value.selected).toBeNull();
    expect(value.setupOpen).toBe(false);
  });
});
