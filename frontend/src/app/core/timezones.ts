export interface TimezoneOption {
  value: string;
  label: string;
  cities: string;
  offsetMinutes: number;
}

// Preference order inside an offset. Only the first zone for each current UTC
// offset is exposed, avoiding repeated UTC+10 (and similar) entries.
const TIMEZONE_CANDIDATES: ReadonlyArray<readonly [string, string]> = [
  ['Etc/GMT+12', 'International Date Line West'], ['Pacific/Pago_Pago', 'Pago Pago'],
  ['Pacific/Honolulu', 'Honolulu'], ['Pacific/Marquesas', 'Marquesas'],
  ['America/Anchorage', 'Anchorage'], ['America/Los_Angeles', 'Los Angeles, Vancouver'],
  ['America/Denver', 'Denver, Edmonton'], ['America/Lima', 'Bogotá, Lima, Quito'],
  ['America/Chicago', 'Chicago, Mexico City'], ['America/Halifax', 'Halifax'],
  ['America/St_Johns', "St. John's"], ['America/Sao_Paulo', 'Brasília, São Paulo'],
  ['Atlantic/South_Georgia', 'South Georgia'], ['UTC', 'Coordinated Universal Time'],
  ['Atlantic/Azores', 'Azores'], ['Europe/London', 'London, Dublin'],
  ['Europe/Paris', 'Paris, Madrid, Berlin'], ['Europe/Athens', 'Athens, Bucharest'],
  ['Europe/Moscow', 'Moscow'], ['Asia/Tehran', 'Tehran'], ['Asia/Dubai', 'Dubai, Abu Dhabi'],
  ['Asia/Kabul', 'Kabul'], ['Asia/Karachi', 'Karachi'], ['Asia/Kolkata', 'Delhi, Kolkata, Mumbai'],
  ['Asia/Kathmandu', 'Kathmandu'], ['Asia/Dhaka', 'Dhaka'], ['Asia/Yangon', 'Yangon'],
  ['Asia/Bangkok', 'Bangkok, Jakarta'], ['Asia/Shanghai', 'Beijing, Shanghai'],
  ['Australia/Eucla', 'Eucla'], ['Asia/Tokyo', 'Tokyo, Seoul'],
  ['Australia/Adelaide', 'Adelaide'], ['Australia/Brisbane', 'Brisbane'],
  ['Australia/Lord_Howe', 'Lord Howe'], ['Pacific/Noumea', 'Nouméa'],
  ['Pacific/Auckland', 'Auckland'], ['Pacific/Chatham', 'Chatham Islands'],
  ['Pacific/Tongatapu', "Nuku'alofa"], ['Pacific/Kiritimati', 'Kiritimati'],
];

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
  } catch { return 0; }
}

function offsetLabel(minutes: number): string {
  const sign = minutes < 0 ? '-' : '+';
  const absolute = Math.abs(minutes);
  return `UTC${sign}${String(Math.floor(absolute / 60)).padStart(2, '0')}:${String(absolute % 60).padStart(2, '0')}`;
}

export function timezoneOptions(at = new Date()): TimezoneOption[] {
  const byOffset = new Map<number, TimezoneOption>();
  for (const [value, cities] of TIMEZONE_CANDIDATES) {
    const offsetMinutes = zoneOffsetMinutes(value, at);
    if (!byOffset.has(offsetMinutes)) {
      byOffset.set(offsetMinutes, { value, cities, offsetMinutes, label: `(${offsetLabel(offsetMinutes)}) ${cities}` });
    }
  }
  return [...byOffset.values()].sort((left, right) => left.offsetMinutes - right.offsetMinutes);
}

export function supportedTimezones(at = new Date()): string[] {
  return timezoneOptions(at).map(option => option.value);
}

export function timezoneLabel(zone: string, at = new Date()): string {
  const exact = TIMEZONE_CANDIDATES.find(([value]) => value === zone);
  const offset = zoneOffsetMinutes(zone || 'UTC', at);
  const representative = timezoneOptions(at).find(option => option.offsetMinutes === offset);
  return `(${offsetLabel(offset)}) ${exact?.[1] || representative?.cities || zone.replaceAll('_', ' ')}`;
}

export function canonicalTimezone(zone: string, at = new Date()): string {
  const targetOffset = zoneOffsetMinutes(zone || 'UTC', at);
  return timezoneOptions(at).find(option => option.offsetMinutes === targetOffset)?.value || 'UTC';
}

export function deviceTimezone(at = new Date()): string {
  try { return canonicalTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', at); }
  catch { return 'UTC'; }
}

export function filterTimezoneOptions(search: string, at = new Date()): TimezoneOption[] {
  const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const needle = normalize(search.trim());
  if (!needle) return timezoneOptions(at);
  return timezoneOptions(at).filter(option => normalize(`${option.label} ${option.value}`).includes(needle));
}
