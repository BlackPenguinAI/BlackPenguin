export interface TimezoneOption {
  value: string;
  label: string;
  summary: string;
  city: string;
  offsetMinutes: number;
  searchText: string;
}

type IntlWithSupportedValues = typeof Intl & {
  supportedValuesOf?: (key: 'timeZone') => string[];
};

// Kept only for runtimes that predate Intl.supportedValuesOf. Distinct IANA
// zones are never collapsed merely because they share an offset today.
const FALLBACK_TIMEZONES = [
  'UTC', 'Pacific/Honolulu', 'America/Anchorage', 'America/Los_Angeles',
  'America/Denver', 'America/Chicago', 'America/Bogota', 'America/Lima',
  'America/Guayaquil', 'America/New_York', 'America/Halifax',
  'America/Sao_Paulo', 'Europe/London', 'Europe/Paris', 'Europe/Athens',
  'Asia/Dubai', 'Asia/Kolkata', 'Asia/Bangkok', 'Asia/Shanghai', 'Asia/Tokyo',
  'Australia/Adelaide', 'Australia/Sydney', 'Pacific/Auckland',
];

const CITY_ALIASES: Record<string, string> = {
  'America/Bogota': 'Bogotá',
  'America/Guayaquil': 'Quito / Guayaquil',
  'America/Lima': 'Lima',
  'America/Mexico_City': 'Mexico City',
  'America/New_York': 'New York',
  'America/Los_Angeles': 'Los Angeles',
  UTC: 'Coordinated Universal Time',
};

function normalized(value: string): string {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

function validTimezone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone }).format();
    return true;
  } catch {
    return false;
  }
}

function availableTimezones(): string[] {
  const supported = (Intl as IntlWithSupportedValues).supportedValuesOf?.('timeZone') || FALLBACK_TIMEZONES;
  return [...new Set(['UTC', ...supported])].filter(validTimezone);
}

function cityLabel(zone: string): string {
  if (CITY_ALIASES[zone]) return CITY_ALIASES[zone];
  return zone.split('/').pop()?.replaceAll('_', ' ') || zone;
}

function zoneOffsetMinutes(zone: string, at: Date): number {
  try {
    const value = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      timeZoneName: 'longOffset',
    }).formatToParts(at).find(part => part.type === 'timeZoneName')?.value || 'GMT';
    if (value === 'GMT' || value === 'UTC') return 0;
    const match = value.match(/(?:GMT|UTC)([+-])(\d{1,2})(?::(\d{2}))?/);
    if (!match) return 0;
    const total = Number(match[2]) * 60 + Number(match[3] || 0);
    return match[1] === '-' ? -total : total;
  } catch {
    return 0;
  }
}

function offsetLabel(minutes: number, padded = true): string {
  const sign = minutes < 0 ? '-' : '+';
  const absolute = Math.abs(minutes);
  const hours = String(Math.floor(absolute / 60));
  const hourText = padded ? hours.padStart(2, '0') : hours;
  return `UTC${sign}${hourText}:${String(absolute % 60).padStart(2, '0')}`;
}

export function timezoneOptions(at = new Date()): TimezoneOption[] {
  return availableTimezones()
    .map(value => {
      const offsetMinutes = zoneOffsetMinutes(value, at);
      const city = cityLabel(value);
      const summary = `(${offsetLabel(offsetMinutes)}) ${city}`;
      const label = `${summary} — ${value}`;
      const shortOffset = offsetLabel(offsetMinutes, false).replace(':00', '');
      const searchText = normalized(`${label} ${shortOffset} ${shortOffset.replace('UTC', 'GMT')}`);
      return { value, label, summary, city, offsetMinutes, searchText };
    })
    .sort((left, right) => left.offsetMinutes - right.offsetMinutes || left.city.localeCompare(right.city));
}

export function supportedTimezones(at = new Date()): string[] {
  return timezoneOptions(at).map(option => option.value);
}

export function timezoneLabel(zone: string, at = new Date()): string {
  const canonical = canonicalTimezone(zone);
  const offset = zoneOffsetMinutes(canonical, at);
  return `(${offsetLabel(offset)}) ${cityLabel(canonical)} — ${canonical}`;
}

export function canonicalTimezone(zone: string): string {
  try {
    return new Intl.DateTimeFormat('en-US', { timeZone: zone || 'UTC' }).resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function deviceTimezone(): string {
  try {
    return canonicalTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  } catch {
    return 'UTC';
  }
}

export function filterTimezoneOptions(search: string, at = new Date()): TimezoneOption[] {
  const needle = normalized(search.trim());
  if (!needle) return timezoneOptions(at);
  return timezoneOptions(at).filter(option => option.searchText.includes(needle));
}

export function searchTimezone(term: string, option: TimezoneOption): boolean {
  return option.searchText.includes(normalized(term.trim()));
}
