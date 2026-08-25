// One representative IANA zone per current UTC offset. IANA values preserve
// daylight-saving rules while the UI avoids dozens of equivalent city aliases.
const TIMEZONE_CANDIDATES = [
  'Etc/GMT+12', 'Pacific/Pago_Pago', 'Pacific/Honolulu', 'Pacific/Marquesas',
  'America/Anchorage', 'America/Los_Angeles', 'America/Denver', 'America/Lima',
  'America/Chicago', 'America/Halifax', 'America/St_Johns', 'America/Sao_Paulo',
  'Atlantic/South_Georgia', 'UTC', 'Atlantic/Azores', 'Europe/London', 'Europe/Paris',
  'Europe/Athens', 'Europe/Moscow', 'Asia/Tehran', 'Asia/Dubai', 'Asia/Kabul',
  'Asia/Karachi', 'Asia/Kolkata', 'Asia/Kathmandu', 'Asia/Dhaka', 'Asia/Yangon',
  'Asia/Bangkok', 'Asia/Shanghai', 'Australia/Eucla', 'Asia/Tokyo',
  'Australia/Adelaide', 'Australia/Brisbane', 'Australia/Lord_Howe', 'Pacific/Noumea',
  'Pacific/Auckland', 'Pacific/Chatham', 'Pacific/Tongatapu', 'Pacific/Kiritimati',
] as const;

function offsetMinutes(zone: string, at: Date): number {
  const part = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    timeZoneName: 'longOffset',
  }).formatToParts(at).find(value => value.type === 'timeZoneName')?.value || 'GMT';
  if (part === 'GMT' || part === 'UTC') return 0;
  const match = part.match(/(?:GMT|UTC)([+-])(\d{1,2})(?::(\d{2}))?/);
  if (!match) return 0;
  const total = Number(match[2]) * 60 + Number(match[3] || 0);
  return match[1] === '-' ? -total : total;
}

function offsetLabel(minutes: number): string {
  const sign = minutes < 0 ? '-' : '+';
  const absolute = Math.abs(minutes);
  return `UTC${sign}${String(Math.floor(absolute / 60)).padStart(2, '0')}:${String(absolute % 60).padStart(2, '0')}`;
}

function standardName(zone: string, at: Date): string {
  if (zone === 'UTC') return 'Coordinated Universal Time';
  return new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    timeZoneName: 'longGeneric',
  }).formatToParts(at).find(value => value.type === 'timeZoneName')?.value
    || zone.replaceAll('_', ' ');
}

export function supportedTimezones(at = new Date()): string[] {
  const byOffset = new Map<number, string>();
  for (const zone of TIMEZONE_CANDIDATES) {
    const offset = offsetMinutes(zone, at);
    if (!byOffset.has(offset)) byOffset.set(offset, zone);
  }
  return [...byOffset.entries()]
    .sort(([left], [right]) => left - right)
    .map(([, zone]) => zone);
}

export function timezoneLabel(zone: string, at = new Date()): string {
  return `${offsetLabel(offsetMinutes(zone, at))} - ${standardName(zone, at)}`;
}

export function canonicalTimezone(zone: string, at = new Date()): string {
  const targetOffset = offsetMinutes(zone || 'UTC', at);
  return supportedTimezones(at).find(item => offsetMinutes(item, at) === targetOffset) || 'UTC';
}
