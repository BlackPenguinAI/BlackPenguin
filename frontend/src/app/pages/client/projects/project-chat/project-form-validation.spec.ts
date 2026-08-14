import {
  toPropertyTypePayload,
  validateMetaSetup,
  validatePropertyType,
  validateProposalDraft,
  validateSalesInvite,
} from './project-form-validation';

describe('project chat form validation', () => {
  it('keeps an extracted short proposal editable and reports the exact remaining words', () => {
    const errors = validateProposalDraft({
      id: 'proposal-1', field: 'target_audience', label: 'Target audience',
      value: 'Families and individuals seeking new homes',
      draftValue: 'Families and individuals seeking new homes',
      evidence: null, confidence: 'high', status: 'pending',
      validation: {
        code: 'minimum_words', field: 'target_audience',
        message: 'Enter at least 8 words.', minimum_words: 8,
      },
    });

    expect(errors['value']).toBe('6 of 8 words. Add 2 more.');
  });

  it('accepts the edited proposal once it reaches the server requirement', () => {
    const errors = validateProposalDraft({
      id: 'proposal-1', field: 'target_audience', label: 'Target audience',
      value: 'Families and individuals seeking new homes',
      draftValue: 'Families and individuals seeking new homes with community amenities',
      evidence: null, confidence: 'high', status: 'pending',
      validation: {
        code: 'minimum_words', field: 'target_audience',
        message: 'Enter at least 8 words.', minimum_words: 8,
      },
    });

    expect(errors).toEqual({});
  });

  it('blocks incomplete property data and invalid ranges', () => {
    const errors = validatePropertyType({
      name: '', available_units: 8, total_units: 5,
      starting_price: 300000, maximum_price: 250000,
      currency: null, inventory_updated_at: null,
      area_min: 120, area_max: 90, area_unit: null,
    });

    expect(errors['name']).toBeTruthy();
    expect(errors['available_units']).toContain('cannot exceed');
    expect(errors['maximum_price']).toContain('greater than or equal');
    expect(errors['area_max']).toContain('greater than or equal');
    expect(errors['currency']).toBeTruthy();
    expect(errors['inventory_updated_at']).toBeTruthy();
  });

  it('builds a normalized writable property type payload without response-only fields', () => {
    const payload = toPropertyTypePayload({
      id: 'type-2', project_id: 'project-1', name: '  Four bedrooms  ',
      available_units: 1, total_units: 1, starting_price: 10, maximum_price: 20,
      currency: 'usd', inventory_updated_at: '2026-08-01', features: [' Patio ', ''],
      review_status: 'candidate', is_complete: false, media: [],
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    });

    expect(payload.name).toBe('Four bedrooms');
    expect(payload.currency).toBe('USD');
    expect(payload.inventory_updated_at).toBe('2026-08-01T12:00:00.000Z');
    expect(payload.features).toEqual(['Patio']);
    expect(payload.review_status).toBe('confirmed');
    expect(payload).not.toHaveProperty('id');
    expect(payload).not.toHaveProperty('project_id');
    expect(payload).not.toHaveProperty('is_complete');
    expect(payload).not.toHaveProperty('media');
  });

  it('requires every Sales-user and Meta setup field before submission', () => {
    expect(Object.keys(validateSalesInvite({ first_name: '', last_name: '', email: 'invalid' }))).toEqual([
      'first_name', 'last_name', 'email',
    ]);
    expect(Object.keys(validateMetaSetup({
      page_id: '', ad_account_id: '', lead_form_id: '',
      page_access_confirmed: false, ad_account_access_confirmed: false, leads_access_confirmed: false,
    }))).toHaveLength(6);
  });
});
