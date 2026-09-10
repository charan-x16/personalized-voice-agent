import {
  ArrowDown,
  ArrowRight,
  AudioLines,
  Check,
  Database,
  LockKeyhole,
  MoveUpRight,
  ShieldCheck,
  UserRoundCheck,
  Wrench,
} from "lucide-react";
import { Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import Link from "next/link";

import { Brand } from "@/components/brand";
import { ContextThread } from "@/components/marketing/context-thread";
import { ConversationDemo } from "@/components/marketing/conversation-demo";
import { LanguageDemo } from "@/components/marketing/language-demo";
import { SUPPORTED_LANGUAGE_SUMMARY } from "@/lib/languages";
import styles from "./landing.module.css";

const conversationSteps = [
  { number: "01", title: "Speak", copy: "A customer starts a natural voice conversation in a supported language." },
  { number: "02", title: "Understand", copy: "Speech is interpreted as a clear intent while the conversation stays fluid." },
  { number: "03", title: "Context", copy: "Your backend supplies only the verified customer information needed for this request." },
  { number: "04", title: "Act", copy: "An approved tool reads or updates your system according to your own business rules." },
  { number: "05", title: "Respond", copy: "The result returns as a concise answer in the customer’s preferred voice and language." },
] as const;

const productProof = [
  {
    icon: UserRoundCheck,
    eyebrow: "Admin workspace",
    title: "Personalisation you can inspect.",
    copy: "Manage verified customer profiles and the agent configuration attached to each account.",
    detail: "Customer scope · prompt version · voice mode",
  },
  {
    icon: AudioLines,
    eyebrow: "Customer experience",
    title: "A calm place to start talking.",
    copy: "Customers see their connected assistant, preferred language, and recent conversation activity.",
    detail: "Verified identity · session status · clear recovery",
  },
  {
    icon: Database,
    eyebrow: "Conversation records",
    title: "Useful history, not a black box.",
    copy: "Review saved summaries, durations, languages, and outcomes inside the authenticated workspace.",
    detail: "Tenant scoped · outcome aware · auditable",
  },
] as const;

export default function LandingPage() {
  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#main-content">Skip to content</a>

      <header className={styles.header}>
        <Brand />
        <nav className={styles.nav} aria-label="Main navigation">
          <a href="#product">Product</a>
          <a href="#conversation-demo">Demo</a>
          <a href="#how-it-works">How it works</a>
          <a href="#security">Security</a>
        </nav>
        <div className={styles.headerActions}>
          <Show when="signed-out">
            <SignInButton mode="redirect">
              <button className={styles.signInLink} type="button">Sign in</button>
            </SignInButton>
            <SignUpButton mode="redirect">
              <button className={styles.headerCta} type="button">
                Create account <ArrowRight size={15} aria-hidden="true" />
              </button>
            </SignUpButton>
          </Show>
          <Show when="signed-in">
            <Link className={styles.headerCta} href="/voice">
              Open workspace <ArrowRight size={15} aria-hidden="true" />
            </Link>
            <UserButton />
          </Show>
        </div>
      </header>

      <nav className={styles.mobileSectionNav} aria-label="Explore Svara">
        <a href="#product">Product</a>
        <a href="#conversation-demo">Demo</a>
        <a href="#how-it-works">How it works</a>
        <a href="#security">Security</a>
      </nav>

      <section className={styles.hero} id="main-content" tabIndex={-1}>
        <div className={styles.heroCopy}>
          <p className={`${styles.kicker} reveal`}><span aria-hidden="true" /> Private intelligence, spoken naturally</p>
          <h1 className={`${styles.heroTitle} display-type reveal reveal-delay-1`}>
            The voice that<br /><em>knows</em> your customer.
          </h1>
          <p className={`${styles.heroLead} reveal reveal-delay-2`}>
            Svara gives your product a multilingual voice that can understand a request, use customer context
            from your systems, and return a useful answer—without making the voice layer your database.
          </p>
          <div className={`${styles.heroActions} reveal reveal-delay-3`}>
            <a className={styles.primaryCta} href="#conversation-demo">
              Explore the demo <MoveUpRight size={17} aria-hidden="true" />
            </a>
            <a className={styles.textCta} href="#how-it-works">
              See how it works <ArrowRight size={16} aria-hidden="true" />
            </a>
          </div>
          <div className={styles.heroFootnote}>
            <span className={styles.contextLine} aria-hidden="true"><i /></span>
            <p>Voice Agents support<br /><strong>{SUPPORTED_LANGUAGE_SUMMARY}</strong></p>
          </div>
        </div>

        <div className={`${styles.heroDemo} reveal reveal-delay-2`}>
          <ConversationDemo variant="hero" />
        </div>

        <a className={styles.scrollCue} href="#product" aria-label="Scroll to learn more">
          <span>Explore</span><ArrowDown size={15} aria-hidden="true" />
        </a>
      </section>

      <section className={styles.principleRail} aria-label="Product principles">
        <p>Human by design</p><span aria-hidden="true">✦</span>
        <p>Grounded in your data</p><span aria-hidden="true">✦</span>
        <p>Multilingual from the first word</p><span aria-hidden="true">✦</span>
        <p>Private at every layer</p>
      </section>

      <ContextThread />
      <ConversationDemo />

      <section className={styles.flowSection} id="how-it-works" aria-labelledby="flow-heading">
        <div className={styles.flowHeading}>
          <div className={styles.sectionMarker}><span>02</span><span>How it works</span></div>
          <h2 id="flow-heading" className="display-type">
            From a spoken question<br />to an approved action.
          </h2>
        </div>
        <div className={styles.steps}>
          {conversationSteps.map((step) => (
            <article className={styles.step} key={step.number}>
              <span className={styles.stepNumber}>{step.number}</span>
              <h3>{step.title}</h3>
              <p>{step.copy}</p>
              <ArrowRight className={styles.stepArrow} size={18} aria-hidden="true" />
            </article>
          ))}
        </div>
      </section>

      <LanguageDemo />

      <section className={styles.securitySection} id="security" aria-labelledby="security-heading">
        <div className={styles.securityTop}>
          <div className={styles.securityIcon}><ShieldCheck size={24} aria-hidden="true" /></div>
          <p className={styles.securityEyebrow}>Built around your trust boundary</p>
        </div>
        <div className={styles.securityGrid}>
          <div>
            <h2 id="security-heading" className="display-type">
              The agent can be helpful without becoming your database.
            </h2>
            <div className={styles.trustFlow}>
              <div><UserRoundCheck size={18} aria-hidden="true" /><span>Customer session</span><small>Verified identity</small></div>
              <ArrowRight size={17} aria-hidden="true" />
              <div><AudioLines size={18} aria-hidden="true" /><span>Svara voice agent</span><small>Conversation layer</small></div>
              <ArrowRight size={17} aria-hidden="true" />
              <div><Database size={18} aria-hidden="true" /><span>Your backend</span><small>Data + business rules</small></div>
            </div>
          </div>
          <div className={styles.securityCopy}>
            <p>
              Your backend remains in control of identity, permissions, and each customer lookup. The agent
              receives only the approved context needed to complete the current task.
            </p>
            <ul>
              <li><LockKeyhole size={15} aria-hidden="true" /> Server-side credentials</li>
              <li><Database size={15} aria-hidden="true" /> Tenant-scoped access</li>
              <li><Wrench size={15} aria-hidden="true" /> Backend-approved actions</li>
              <li><Check size={15} aria-hidden="true" /> Saved conversation outcomes</li>
            </ul>
          </div>
        </div>
      </section>

      <section className={styles.proofSection} aria-labelledby="proof-title">
        <div className={styles.proofHeading}>
          <p className={styles.kicker}>A product, not just a promise</p>
          <h2 id="proof-title" className="display-type">Every conversation has a place to land.</h2>
        </div>
        <div className={styles.proofGrid}>
          {productProof.map((item) => {
            const Icon = item.icon;
            return (
              <article className={styles.proofItem} key={item.eyebrow}>
                <span className={styles.proofIcon} aria-hidden="true"><Icon size={19} /></span>
                <p>{item.eyebrow}</p>
                <h3>{item.title}</h3>
                <div className={styles.proofFrame} aria-hidden="true"><i /><i /><i /><span /></div>
                <p>{item.copy}</p>
                <small>{item.detail}</small>
              </article>
            );
          })}
        </div>
      </section>

      <section className={styles.finalCta}>
        <p className={styles.kicker}>See what context changes</p>
        <h2 className="display-type">Give your product<br />a voice worth <em>hearing.</em></h2>
        <div className={styles.finalActions}>
          <a className={styles.primaryCta} href="#conversation-demo">
            Explore the demo <MoveUpRight size={17} aria-hidden="true" />
          </a>
          <Link className={styles.textCta} href="/sign-in">
            Sign in to Svara <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </section>

      <footer className={styles.footer}>
        <div className={styles.footerBrand}><Brand /><p>Personal voice. Real context.</p></div>
        <div className={styles.footerNav}>
          <a href="#product">Product</a><a href="#conversation-demo">Demo</a>
          <a href="#how-it-works">How it works</a><a href="#security">Security</a>
          <Link href="/sign-in">Sign in</Link>
        </div>
        <p className={styles.copyright}>© 2026 Svara</p>
      </footer>
    </main>
  );
}
