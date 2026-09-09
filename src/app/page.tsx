import {
  ArrowDown,
  ArrowRight,
  Check,
  Database,
  LockKeyhole,
  Mic2,
  MoveUpRight,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import Link from "next/link";

import { Brand } from "@/components/brand";
import styles from "./landing.module.css";

const conversationSteps = [
  {
    number: "01",
    title: "Recognise",
    copy: "A verified session tells the agent who is speaking—without exposing a customer ID to the browser.",
  },
  {
    number: "02",
    title: "Understand",
    copy: "Natural speech becomes intent across English and India’s most-used languages.",
  },
  {
    number: "03",
    title: "Retrieve",
    copy: "Purpose-built tools fetch only the account context needed for that moment.",
  },
  {
    number: "04",
    title: "Respond",
    copy: "A useful, human answer returns in the customer’s preferred voice and language.",
  },
];

const transcript = [
  {
    speaker: "Customer",
    text: "Has my replacement card been dispatched?",
    time: "10:41",
  },
  {
    speaker: "Svara",
    text: "Yes, Rahul. It left our Bengaluru centre this morning and should reach you by Friday.",
    time: "10:41",
  },
];

function SoundMark({ dark = false }: { dark?: boolean }) {
  return (
    <div className={`${styles.soundMark} ${dark ? styles.soundMarkDark : ""}`} aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
      <span />
      <span />
      <span />
      <span />
      <span />
    </div>
  );
}

export default function LandingPage() {
  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#main-content">
        Skip to content
      </a>

      <header className={styles.header}>
        <Brand />
        <nav className={styles.nav} aria-label="Main navigation">
          <a href="#product">Product</a>
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
                Create account
                <ArrowRight size={15} aria-hidden="true" />
              </button>
            </SignUpButton>
          </Show>
          <Show when="signed-in">
            <Link className={styles.headerCta} href="/voice">
              Open workspace
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
            <UserButton />
          </Show>
        </div>
      </header>

      <nav className={styles.mobileSectionNav} aria-label="Explore Svara">
        <a href="#product">Product</a>
        <a href="#how-it-works">How it works</a>
        <a href="#security">Security</a>
      </nav>

      <section className={styles.hero} id="main-content">
        <div className={styles.heroCopy}>
          <p className={`${styles.kicker} reveal`}>
            <span aria-hidden="true" />
            Private intelligence, spoken naturally
          </p>
          <h1 className={`${styles.heroTitle} display-type reveal reveal-delay-1`}>
            The voice that
            <br />
            <em>knows</em> your customer.
          </h1>
          <p className={`${styles.heroLead} reveal reveal-delay-2`}>
            A multilingual voice-agent platform that speaks with warmth, works with your systems, and uses the
            right customer context at the right moment.
          </p>
          <div className={`${styles.heroActions} reveal reveal-delay-3`}>
            <Link className={styles.primaryCta} href="/voice">
              Start a conversation
              <MoveUpRight size={17} aria-hidden="true" />
            </Link>
            <a className={styles.textCta} href="#sample-conversation">
              Read a sample conversation
              <ArrowRight size={16} aria-hidden="true" />
            </a>
          </div>
          <div className={styles.heroFootnote}>
            <div className={styles.avatarStack} aria-hidden="true">
              <span>RM</span>
              <span>AS</span>
              <span>NK</span>
            </div>
            <p>
              Built for conversations in
              <br />
              <strong>10 Indian languages + English</strong>
            </p>
          </div>
        </div>

        <div className={`${styles.heroVisual} reveal reveal-delay-2`} aria-label="Illustrative Svara conversation preview, not a live session">
          <div className={styles.visualIndex} aria-hidden="true">
            <span>SV / 01</span>
            <span>SAMPLE CONTEXT</span>
          </div>
          <div className={styles.orbit} aria-hidden="true">
            <span className={styles.orbitDot} />
          </div>
          <div className={styles.voiceCore}>
            <div className={styles.coreTopline}>
              <span className={styles.liveLabel}>
                <i aria-hidden="true" /> Preview
              </span>
            </div>
            <div className={styles.coreCenter}>
              <div className={styles.waveHalo}>
                <SoundMark dark />
              </div>
              <p>Listening</p>
              <span>English · <span lang="hi">हिन्दी</span></span>
            </div>
            <div className={styles.coreFooter}>
              <Mic2 size={16} aria-hidden="true" />
              <span>“Where is my order?”</span>
            </div>
          </div>
          <div className={`${styles.contextChip} ${styles.contextIdentity}`}>
            <span className={styles.chipIcon}>
              <Check size={14} aria-hidden="true" />
            </span>
            <span>
              <small>Identity matched</small>
              Rahul Mehta
            </span>
          </div>
          <div className={`${styles.contextChip} ${styles.contextOrder}`}>
            <span className={styles.chipIcon}>
              <Database size={14} aria-hidden="true" />
            </span>
            <span>
              <small>Secure tool response</small>
              Order #8294 · In transit
            </span>
          </div>
          <div className={styles.annotation} aria-hidden="true">
            <span />
            Context arrives only when it is needed
          </div>
        </div>

        <a className={styles.scrollCue} href="#product" aria-label="Scroll to learn more">
          <span>Explore</span>
          <ArrowDown size={15} aria-hidden="true" />
        </a>
      </section>

      <section className={styles.principleRail} aria-label="Product principles">
        <p>Human by design</p>
        <span aria-hidden="true">✦</span>
        <p>Grounded in your data</p>
        <span aria-hidden="true">✦</span>
        <p>Multilingual from the first word</p>
        <span aria-hidden="true">✦</span>
        <p>Private at every layer</p>
      </section>

      <section className={styles.manifesto} id="product">
        <div className={styles.sectionMarker}>
          <span>01</span>
          <span>Why Svara</span>
        </div>
        <div className={styles.manifestoContent}>
          <h2 className="display-type">
            Your systems stay the source of truth. Your conversations start feeling <em>personal.</em>
          </h2>
          <div className={styles.manifestoAside}>
            <p>
              Svara connects natural voice to the customer information and actions already living in your
              product—without moving the database into the conversation layer.
            </p>
            <a href="#how-it-works" className={styles.underlinedLink}>
              See the connection flow
              <ArrowRight size={15} aria-hidden="true" />
            </a>
          </div>
        </div>
      </section>

      <section className={styles.conversationSection} id="sample-conversation" aria-labelledby="conversation-heading">
        <div className={styles.conversationIntro}>
          <p className={styles.kicker}>One conversation. Full context.</p>
          <h2 id="conversation-heading" className="display-type">
            Less repetition.
            <br />
            More resolution.
          </h2>
          <p>
            The agent asks your backend for specific information, then turns that trusted response into language
            that feels clear and natural.
          </p>
        </div>

        <article className={styles.transcriptCard}>
          <div className={styles.transcriptHeader}>
            <div>
              <span className={styles.statusDot} aria-hidden="true" />
              Illustrative conversation
            </div>
            <span>SV–4829</span>
          </div>
          <div className={styles.transcriptBody}>
            {transcript.map((line) => (
              <div className={styles.transcriptLine} key={line.speaker}>
                <div className={styles.transcriptMeta}>
                  <strong>{line.speaker}</strong>
                  <time>{line.time}</time>
                </div>
                <p>{line.text}</p>
              </div>
            ))}
          </div>
          <div className={styles.toolEvent}>
            <div className={styles.toolIcon}>
              <Database size={16} aria-hidden="true" />
            </div>
            <div>
              <strong>get_order_status</strong>
              <span>Example tool response</span>
            </div>
            <Check size={17} aria-label="Completed" />
          </div>
          <div className={styles.audioFooter}>
            <SoundMark />
            <span>Speaking naturally in the customer’s language</span>
          </div>
        </article>
      </section>

      <section className={styles.flowSection} id="how-it-works" aria-labelledby="flow-heading">
        <div className={styles.flowHeading}>
          <div className={styles.sectionMarker}>
            <span>02</span>
            <span>How it works</span>
          </div>
          <h2 id="flow-heading" className="display-type">
            From a spoken question
            <br />
            to a useful answer.
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

      <section className={styles.languageSection} aria-labelledby="language-heading">
        <div className={styles.languageArt} aria-hidden="true">
          <span className={styles.hindi}>नमस्ते</span>
          <span className={styles.tamil}>வணக்கம்</span>
          <span className={styles.telugu}>నమస్కారం</span>
          <span className={styles.bengali}>নমস্কার</span>
          <span className={styles.english}>Hello</span>
          <div className={styles.languageOrb}>
            <Sparkles size={22} />
          </div>
        </div>
        <div className={styles.languageCopy}>
          <p className={styles.kicker}>Language is not a setting</p>
          <h2 id="language-heading" className="display-type">
            Meet every customer where they are.
          </h2>
          <p>
            Switch naturally between English and Indian languages. Preserve names, numbers and intent—even when
            the conversation moves between them.
          </p>
          <Link href="/voice" className={styles.underlinedLink}>
            Hear the experience
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </div>
      </section>

      <section className={styles.securitySection} id="security" aria-labelledby="security-heading">
        <div className={styles.securityTop}>
          <div className={styles.securityIcon}>
            <ShieldCheck size={24} aria-hidden="true" />
          </div>
          <p className={styles.securityEyebrow}>Built around your trust boundary</p>
        </div>
        <div className={styles.securityGrid}>
          <h2 id="security-heading" className="display-type">
            The agent can be helpful without becoming your database.
          </h2>
          <div className={styles.securityCopy}>
            <p>
              Your backend remains in control of identity, permissions and every customer lookup. The model sees
              only the context required to complete the current task.
            </p>
            <ul>
              <li>
                <LockKeyhole size={15} aria-hidden="true" /> Server-side credentials
              </li>
              <li>
                <Database size={15} aria-hidden="true" /> Tenant-scoped access
              </li>
              <li>
                <Check size={15} aria-hidden="true" /> Auditable tool calls
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section className={styles.finalCta}>
        <p className={styles.kicker}>Ready when you are</p>
        <h2 className="display-type">
          Give your product
          <br />
          a voice worth <em>hearing.</em>
        </h2>
        <div className={styles.finalActions}>
          <Link className={styles.primaryCta} href="/voice">
            Enter the voice room
            <MoveUpRight size={17} aria-hidden="true" />
          </Link>
          <Link className={styles.textCta} href="/sign-in">
            Sign in to Svara
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </section>

      <footer className={styles.footer}>
        <div className={styles.footerBrand}>
          <Brand />
          <p>Personal voice. Real context.</p>
        </div>
        <div className={styles.footerNav}>
          <a href="#product">Product</a>
          <a href="#how-it-works">How it works</a>
          <a href="#security">Security</a>
          <Link href="/sign-in">Sign in</Link>
        </div>
        <p className={styles.copyright}>© 2026 Svara</p>
      </footer>
    </main>
  );
}
