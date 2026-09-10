export type SupportedLanguage = {
  code: string;
  displayName: string;
  nativeName: string;
  selectable: boolean;
};

/**
 * Languages exposed by Svara's current Voice Agents product experience.
 *
 * Keep this list limited to languages confirmed for Sarvam Voice Agents and
 * supported by the FastAPI adapter. An SDK enum alone is not enough to make a
 * language selectable. Marketing and customer configuration both consume this
 * module so their claims cannot drift independently.
 */
export const SUPPORTED_LANGUAGES = [
  { code: "en", displayName: "English", nativeName: "English", selectable: true },
  { code: "as", displayName: "Assamese", nativeName: "অসমীয়া", selectable: true },
  { code: "bn", displayName: "Bengali", nativeName: "বাংলা", selectable: true },
  { code: "gu", displayName: "Gujarati", nativeName: "ગુજરાતી", selectable: true },
  { code: "hi", displayName: "Hindi", nativeName: "हिन्दी", selectable: true },
  { code: "kn", displayName: "Kannada", nativeName: "ಕನ್ನಡ", selectable: true },
  { code: "ml", displayName: "Malayalam", nativeName: "മലയാളം", selectable: true },
  { code: "mr", displayName: "Marathi", nativeName: "मराठी", selectable: true },
  { code: "or", displayName: "Odia", nativeName: "ଓଡ଼ିଆ", selectable: true },
  { code: "pa", displayName: "Punjabi", nativeName: "ਪੰਜਾਬੀ", selectable: true },
  { code: "ta", displayName: "Tamil", nativeName: "தமிழ்", selectable: true },
  { code: "te", displayName: "Telugu", nativeName: "తెలుగు", selectable: true },
] as const satisfies readonly SupportedLanguage[];

export const SELECTABLE_LANGUAGES = SUPPORTED_LANGUAGES.filter(
  (language) => language.selectable,
);

export const INDIAN_LANGUAGE_COUNT = SELECTABLE_LANGUAGES.filter(
  (language) => language.code !== "en",
).length;

export const SUPPORTED_LANGUAGE_SUMMARY = `English and ${INDIAN_LANGUAGE_COUNT} Indian languages`;

export function supportedLanguageByCode(code: string) {
  return SUPPORTED_LANGUAGES.find((language) => language.code === code);
}
