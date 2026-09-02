import { describe, expect, it } from 'vitest';

import { activationLinkParameters } from './activation-link';

function reader(values: Record<string, string | null>) {
  return (key: string) => values[key] ?? null;
}

describe('activationLinkParameters', () => {
  it('uses direct Firebase parameters', () => {
    expect(activationLinkParameters(reader({ state: 'signed', oobCode: 'firebase-code' }))).toEqual({
      state: 'signed', oobCode: 'firebase-code', source: 'direct',
    });
  });

  it('extracts parameters from nested Firebase links', () => {
    const inner = 'https://blackpenguin.ai/activate-account?state=signed&oobCode=firebase-code';
    const outer = `https://blackpenguinai.firebaseapp.com/__/auth/action?link=${encodeURIComponent(inner)}`;
    expect(activationLinkParameters(reader({ state: null, oobCode: null, link: outer }))).toMatchObject({
      state: 'signed', oobCode: 'firebase-code', source: 'nested',
    });
  });

  it('combines a direct Firebase code with state carried by continueUrl', () => {
    const continueUrl = 'https://blackpenguin.ai/activate-account?state=signed';
    expect(activationLinkParameters(reader({
      state: null, oobCode: 'firebase-code', continueUrl,
    }))).toMatchObject({
      state: 'signed', oobCode: 'firebase-code', source: 'nested',
    });
  });

  it('extracts parameters from a fragment without exposing their values elsewhere', () => {
    expect(activationLinkParameters(reader({}), 'state=signed&oobCode=firebase-code')).toMatchObject({
      state: 'signed', oobCode: 'firebase-code', source: 'fragment',
    });
  });
});
