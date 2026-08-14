import { ProjectPropertyType, SourceProposal } from './project-onboarding.models';

export type FormErrors = Record<string, string>;

const present = (value: unknown): boolean => value !== null && value !== undefined && String(value).trim() !== '';

export function validatePropertyType(value: Partial<ProjectPropertyType>): FormErrors {
  const errors: FormErrors = {};
  if (!value.name?.trim()) errors['name'] = 'Enter the property type name.';
  if (!present(value.available_units)) errors['available_units'] = 'Enter the currently available units.';
  if (!present(value.starting_price)) errors['starting_price'] = 'Enter the starting price.';
  if (!value.currency?.trim()) errors['currency'] = 'Select the commercial currency.';
  if (!value.inventory_updated_at) errors['inventory_updated_at'] = 'Select the inventory update date.';
  if ((present(value.area_min) || present(value.area_max)) && !value.area_unit) {
    errors['area_unit'] = 'Select the unit used for the area.';
  }
  if (present(value.area_min) && present(value.area_max) && Number(value.area_min) > Number(value.area_max)) {
    errors['area_max'] = 'Area maximum must be greater than or equal to area minimum.';
  }
  if (present(value.total_units) && present(value.available_units)
      && Number(value.available_units) > Number(value.total_units)) {
    errors['available_units'] = 'Available units cannot exceed total units.';
  }
  if (present(value.maximum_price) && present(value.starting_price)
      && Number(value.starting_price) > Number(value.maximum_price)) {
    errors['maximum_price'] = 'Maximum price must be greater than or equal to starting price.';
  }
  return errors;
}

export function validateSalesInvite(value: { first_name: string; last_name: string; email: string }): FormErrors {
  const errors: FormErrors = {};
  if (!value.first_name.trim()) errors['first_name'] = 'Enter the first name.';
  if (!value.last_name.trim()) errors['last_name'] = 'Enter the last name.';
  if (!value.email.trim()) errors['email'] = 'Enter the business email.';
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.email.trim())) errors['email'] = 'Enter a valid business email.';
  return errors;
}

export function validateMetaSetup(value: {
  page_id: string; ad_account_id: string; lead_form_id: string;
  page_access_confirmed: boolean; ad_account_access_confirmed: boolean; leads_access_confirmed: boolean;
}): FormErrors {
  const errors: FormErrors = {};
  if (value.page_id.trim().length < 5) errors['page_id'] = 'Enter the Page ID.';
  if (value.ad_account_id.trim().length < 5) errors['ad_account_id'] = 'Enter the Ad Account ID.';
  if (value.lead_form_id.trim().length < 5) errors['lead_form_id'] = 'Enter the Lead Form ID.';
  if (!value.page_access_confirmed) errors['page_access_confirmed'] = 'Confirm access to the Page.';
  if (!value.ad_account_access_confirmed) errors['ad_account_access_confirmed'] = 'Confirm access to the Advertising Account.';
  if (!value.leads_access_confirmed) errors['leads_access_confirmed'] = 'Confirm Leads Access.';
  return errors;
}

export function validateProposalDraft(proposal: SourceProposal): FormErrors {
  const validation = proposal.validation;
  if (!validation) return {};
  const draft = (proposal.draftValue || '').trim();
  if (validation.code === 'minimum_words' && validation.minimum_words) {
    const count = draft ? draft.split(/\s+/).length : 0;
    if (count < validation.minimum_words) {
      return { value: `${count} of ${validation.minimum_words} words. Add ${validation.minimum_words - count} more.` };
    }
    return {};
  }
  if (validation.code === 'minimum_characters' && validation.minimum_characters) {
    const count = draft.length;
    if (count < validation.minimum_characters) {
      return { value: `${count} of ${validation.minimum_characters} characters. Add ${validation.minimum_characters - count} more.` };
    }
    return {};
  }
  return proposal.draftValue === undefined || proposal.draftValue === String(proposal.value ?? '')
    ? { value: validation.message }
    : {};
}

export function errorCount(errors: FormErrors): number {
  return Object.keys(errors).length;
}
