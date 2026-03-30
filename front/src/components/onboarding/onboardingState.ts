export const ONBOARDING_STATE_KEY = "onboarding_state";

const LEGACY_TIPS_STORAGE_KEY = "onboarding_functionality_state";
const LEGACY_SETUP_STORAGE_KEYS = [
  "onboarding_setup_complete",
  "onboarding_setup_completed",
] as const;

export interface OnboardingState {
  setup_seen: boolean;
  chat_feature_tour_seen: boolean;
  response_attachment_tip_seen: boolean;
}

const DEFAULT_ONBOARDING_STATE: OnboardingState = {
  setup_seen: false,
  chat_feature_tour_seen: false,
  response_attachment_tip_seen: false,
};

function parseJson(raw: string | null): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readLegacySetupSeen(): boolean {
  return LEGACY_SETUP_STORAGE_KEYS.some(
    (key) => localStorage.getItem(key) === "true",
  );
}

function readLegacyTips(): Partial<OnboardingState> {
  const parsed = parseJson(localStorage.getItem(LEGACY_TIPS_STORAGE_KEY));
  if (!isRecord(parsed)) return {};

  return {
    chat_feature_tour_seen: parsed.chat_feature_tour_seen === true,
    response_attachment_tip_seen: parsed.response_attachment_tip_seen === true,
  };
}

function removeLegacyKeys(): void {
  localStorage.removeItem(LEGACY_TIPS_STORAGE_KEY);
  for (const key of LEGACY_SETUP_STORAGE_KEYS) {
    localStorage.removeItem(key);
  }
}

export function saveOnboardingState(state: OnboardingState): void {
  localStorage.setItem(ONBOARDING_STATE_KEY, JSON.stringify(state));
}

export function getOnboardingState(): OnboardingState {
  const parsed = parseJson(localStorage.getItem(ONBOARDING_STATE_KEY));
  if (isRecord(parsed)) {
    return {
      setup_seen: parsed.setup_seen === true,
      chat_feature_tour_seen: parsed.chat_feature_tour_seen === true,
      response_attachment_tip_seen:
        parsed.response_attachment_tip_seen === true,
    };
  }

  const migrated: OnboardingState = {
    ...DEFAULT_ONBOARDING_STATE,
    ...readLegacyTips(),
    setup_seen: readLegacySetupSeen(),
  };
  saveOnboardingState(migrated);
  removeLegacyKeys();
  return migrated;
}

export function updateOnboardingState(
  patch: Partial<OnboardingState>,
): OnboardingState {
  const next = { ...getOnboardingState(), ...patch };
  saveOnboardingState(next);
  return next;
}

export function clearOnboardingState(): void {
  localStorage.removeItem(ONBOARDING_STATE_KEY);
  removeLegacyKeys();
}
