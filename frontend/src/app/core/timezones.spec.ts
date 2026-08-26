import { describe, expect, it } from 'vitest';
import { canonicalTimezone, filterTimezoneOptions, supportedTimezones, timezoneLabel, timezoneOptions } from './timezones';

describe('timezone catalog', () => {
  const reference = new Date('2026-08-25T12:00:00Z');

  it('contains one entry per UTC offset in numeric order', () => {
    const labels = supportedTimezones(reference).map(zone => timezoneLabel(zone, reference));
    const offsets = labels.map(label => {
      const [, sign, hours, minutes] = label.match(/^\(UTC([+-])(\d{2}):(\d{2})\)/) || [];
      const value = Number(hours) * 60 + Number(minutes);
      return sign === '-' ? -value : value;
    });
    expect(new Set(offsets).size).toBe(offsets.length);
    expect(offsets).toEqual([...offsets].sort((left, right) => left - right));
  });

  it('uses the requested offset and city format', () => {
    expect(timezoneLabel('America/Lima', reference)).toBe('(UTC-05:00) Bogotá, Lima, Quito');
    expect(supportedTimezones(reference)).toContain('America/Lima');
  });

  it('keeps one option per offset and searches city names without accents', () => {
    const options = timezoneOptions(reference);
    expect(new Set(options.map(option => option.offsetMinutes)).size).toBe(options.length);
    expect(filterTimezoneOptions('bogota', reference)[0]?.value).toBe('America/Lima');
    expect(canonicalTimezone('America/Bogota', reference)).toBe('America/Lima');
  });
});
