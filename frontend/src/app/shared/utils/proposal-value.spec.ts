import { describe, expect, it } from 'vitest';
import { formatProposalValue, humanizeProposalKey, parseProposalValue } from './proposal-value';

describe('proposal value adapter', () => {
  it('formats lists without JSON punctuation and restores their type', () => {
    const original = ['Pool', 'Gym'];
    expect(formatProposalValue('amenities', original)).toBe('Pool\nGym');
    expect(parseProposalValue('amenities', 'Pool\nGym\nCoworking', original)).toEqual(['Pool', 'Gym', 'Coworking']);
  });

  it('formats and edits nested objects as labeled fields', () => {
    const original = { address: { city: 'Lima', country: 'Peru' }, active: true, units: 10 };
    const formatted = formatProposalValue('location', original);
    expect(formatted).not.toMatch(/[{}\"]/);
    expect(formatted).toContain('Address › City: Lima');
    expect(parseProposalValue('location', formatted.replace('Units: 10', 'Units: 12'), original)).toEqual({
      address: { city: 'Lima', country: 'Peru' }, active: true, units: 12,
    });
  });

  it('keeps the official website contract behind a friendly value', () => {
    expect(formatProposalValue('official_corporate_website', { exists: false, url: null })).toBe('No official website');
    expect(parseProposalValue('official_corporate_website', 'https://example.com', { exists: false, url: null })).toEqual({
      exists: true, url: 'https://example.com',
    });
  });

  it('humanizes machine field names', () => {
    expect(humanizeProposalKey('available_inventory')).toBe('Available inventory');
  });
});
