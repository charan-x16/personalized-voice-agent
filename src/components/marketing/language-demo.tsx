"use client";

import { ArrowRight, Languages } from "lucide-react";
import { useState } from "react";

import { INDIAN_LANGUAGE_COUNT, supportedLanguageByCode } from "@/lib/languages";
import styles from "./language-demo.module.css";

const examples = [
  {
    code: "en",
    utterance: "Can you move my booking to tomorrow evening?",
    response: "Of course. I found your booking and moved it to tomorrow at 7:30 PM.",
  },
  {
    code: "hi",
    utterance: "क्या आप मेरी बुकिंग कल शाम के लिए बदल सकते हैं?",
    response: "ज़रूर। आपकी बुकिंग अब कल शाम 7:30 बजे के लिए तय है।",
  },
  {
    code: "ta",
    utterance: "என் முன்பதிவை நாளை மாலைக்கு மாற்ற முடியுமா?",
    response: "நிச்சயமாக. உங்கள் முன்பதிவு நாளை மாலை 7:30 மணிக்கு மாற்றப்பட்டது.",
  },
  {
    code: "te",
    utterance: "నా బుకింగ్‌ను రేపు సాయంత్రానికి మార్చగలరా?",
    response: "తప్పకుండా. మీ బుకింగ్ రేపు సాయంత్రం 7:30కి మార్చబడింది.",
  },
  {
    code: "bn",
    utterance: "আমার বুকিংটা কি আগামীকাল সন্ধ্যায় বদলাতে পারবেন?",
    response: "অবশ্যই। আপনার বুকিং আগামীকাল সন্ধ্যা ৭:৩০-এ বদলে দেওয়া হয়েছে।",
  },
] as const;

export function LanguageDemo() {
  const [activeCode, setActiveCode] = useState<(typeof examples)[number]["code"]>("en");
  const active = examples.find((example) => example.code === activeCode) ?? examples[0];

  return (
    <section className={styles.section} aria-labelledby="language-demo-title">
      <div className={styles.copy}>
        <p className={styles.kicker}><Languages size={16} aria-hidden="true" /> Multilingual by design</p>
        <h2 id="language-demo-title">The same intent, naturally expressed.</h2>
        <p>
          Explore one interaction across English and selected Indian languages. Svara’s Voice Agents officially
          support English and {INDIAN_LANGUAGE_COUNT} Indian languages.
        </p>
        <a href="#conversation-demo">
          Explore the conversation flow <ArrowRight size={15} aria-hidden="true" />
        </a>
      </div>

      <div className={styles.demo}>
        <div className={styles.languageChoices} role="group" aria-label="Choose an example language">
          {examples.map((example) => {
            const language = supportedLanguageByCode(example.code);
            return (
              <button
                key={example.code}
                type="button"
                aria-pressed={example.code === activeCode}
                onClick={() => setActiveCode(example.code)}
              >
                <span>{language?.displayName ?? example.code}</span>
                <small lang={example.code}>{language?.nativeName}</small>
              </button>
            );
          })}
        </div>

        <div key={active.code} className={styles.exchange} aria-live="polite">
          <div className={styles.connection} aria-hidden="true" />
          <article>
            <small>Customer</small>
            <p lang={active.code}>{active.utterance}</p>
          </article>
          <article className={styles.agentReply}>
            <small>Svara</small>
            <p lang={active.code}>{active.response}</p>
          </article>
        </div>
        <p className={styles.disclaimer}>Interactive text example · no audio playback</p>
      </div>
    </section>
  );
}
