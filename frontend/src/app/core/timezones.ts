const FALLBACK_TIMEZONES = [
  'UTC', 'America/Lima', 'America/Bogota', 'America/Guayaquil', 'America/Mexico_City',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Toronto', 'America/Vancouver', 'America/Santiago', 'America/Argentina/Buenos_Aires',
  'America/Sao_Paulo', 'Europe/London', 'Europe/Madrid', 'Europe/Paris', 'Asia/Dubai', 'Asia/Tokyo',
];

export function supportedTimezones(): string[] {
  const supported = (Intl as any).supportedValuesOf?.('timeZone') as string[] | undefined;
  return Array.from(new Set([...(supported || FALLBACK_TIMEZONES), 'UTC'])).sort();
}

export function timezoneLabel(zone: string, at = new Date()): string {
  const offset = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    timeZoneName: 'longOffset',
  }).formatToParts(at).find(part => part.type === 'timeZoneName')?.value
    ?.replace('GMT', 'UTC') || 'UTC';
  const cities = zone === 'UTC' ? 'Coordinated Universal Time' : zone.split('/').slice(1).join(' / ').replace(/_/g, ' ');
  return `${offset} · ${cities}`;
}
