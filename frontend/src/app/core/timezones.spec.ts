import { describe, expect, it } from 'vitest';
import { canonicalTimezone, deviceTimezone, filterTimezoneOptions, supportedTimezones, timezoneLabel, timezoneOptions } from './timezones';

describe('timezone catalog', () => {
  const reference = new Date('2026-08-25T12:00:00Z');

  it('keeps distinct IANA zones even when their current offsets match', () => {
    const zones = supportedTimezones(reference);
    expect(zones).toContain('America/Lima');
    expect(zones).toContain('America/Bogota');
    expect(canonicalTimezone('America/Bogota')).toBe('America/Bogota');
  });

  it('uses the requested offset, city and exact IANA identifier', () => {
    expect(timezoneLabel('America/Lima', reference)).toBe('(UTC-05:00) Lima — America/Lima');
    expect(timezoneLabel('America/Bogota', reference)).toBe('(UTC-05:00) Bogotá — America/Bogota');
  });

  it('searches by city, normalized accents, IANA identifier and compact UTC offset', () => {
    expect(filterTimezoneOptions('bogota', reference).some(option => option.value === 'America/Bogota')).toBe(true);
    expect(filterTimezoneOptions('America/Lima', reference).some(option => option.value === 'America/Lima')).toBe(true);
    expect(filterTimezoneOptions('UTC-5', reference).some(option => option.value === 'America/Lima')).toBe(true);
  });

  it('sorts by current offset without collapsing options', () => {
    const offsets = timezoneOptions(reference).map(option => option.offsetMinutes);
    expect(offsets).toEqual([...offsets].sort((left, right) => left - right));
    expect(new Set(offsets).size).toBeLessThan(offsets.length);
  });

  it('returns a valid exact device timezone', () => {
    expect(() => new Intl.DateTimeFormat('en-US', { timeZone: deviceTimezone() })).not.toThrow();
  });
});
