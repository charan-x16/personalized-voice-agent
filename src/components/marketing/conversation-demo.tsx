"use client";

import { Check, CircleUserRound, Database, MessageCircleMore, Sparkles, Wrench } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";

import styles from "./conversation-demo.module.css";

const scenarios = [
  {
    id: "order",
    label: "Order status",
    prompt: "Where is my latest order?",
    intent: "Track delivery",
    context: ["Priya Sharma", "Returning customer", "Order #8294"],
    tool: "get_order_status()",
    result: "Out for delivery · arrives tomorrow",
    response: "Your order left our Bengaluru facility this morning. It should arrive tomorrow.",
  },
  {
    id: "booking",
    label: "Book a table",
    prompt: "Can you find a table for four tomorrow evening?",
    intent: "Create reservation",
    context: ["Priya Sharma", "4 guests", "Indiranagar"],
    tool: "check_availability() → create_reservation()",
    result: "7:30 PM · table confirmed",
    response: "I’ve booked a table for four tomorrow at 7:30 PM.",
  },
  {
    id: "change",
    label: "Change a booking",
    prompt: "Can I move Friday’s booking to Saturday?",
    intent: "Modify reservation",
    context: ["Priya Sharma", "Friday · 8 PM", "4 guests"],
    tool: "find_reservation() → reschedule_reservation()",
    result: "Saturday · 8 PM · confirmed",
    response: "Done. Your table is now booked for Saturday at 8 PM.",
  },
] as const;

type ConversationDemoProps = {
  variant?: "hero" | "full";
};

export function ConversationDemo({ variant = "full" }: ConversationDemoProps) {
  const [activeId, setActiveId] = useState<(typeof scenarios)[number]["id"]>("order");
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const instanceId = useId().replaceAll(":", "");
  const scenario = scenarios.find((item) => item.id === activeId) ?? scenarios[0];

  function handleTabs(event: KeyboardEvent<HTMLDivElement>) {
    const currentIndex = scenarios.findIndex((item) => item.id === activeId);
    let nextIndex = currentIndex;

    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % scenarios.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + scenarios.length) % scenarios.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = scenarios.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    setActiveId(scenarios[nextIndex].id);
    buttonRefs.current[nextIndex]?.focus();
  }

  const demo = (
    <div className={`${styles.demo} ${variant === "hero" ? styles.heroDemo : ""}`}>
      <div className={styles.demoTopline}>
        <span><i aria-hidden="true" /> Product simulation</span>
        <small>No microphone used</small>
      </div>

      <div className={styles.tabs} role="tablist" aria-label="Choose a conversation scenario" onKeyDown={handleTabs}>
        {scenarios.map((item, index) => {
          const selected = item.id === activeId;
          return (
            <button
              key={item.id}
              ref={(element) => { buttonRefs.current[index] = element; }}
              id={`${instanceId}-${item.id}-tab`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${instanceId}-${item.id}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActiveId(item.id)}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      <div
        key={scenario.id}
        className={styles.thread}
        id={`${instanceId}-${scenario.id}-panel`}
        role="tabpanel"
        aria-labelledby={`${instanceId}-${scenario.id}-tab`}
        aria-live="polite"
      >
        <div className={styles.threadLine} aria-hidden="true" />
        <article className={`${styles.event} ${styles.request}`}>
          <span className={styles.eventIcon} aria-hidden="true"><CircleUserRound size={17} /></span>
          <div><small>Customer</small><strong>“{scenario.prompt}”</strong></div>
        </article>

        <article className={`${styles.event} ${styles.intent}`}>
          <span className={styles.eventIcon} aria-hidden="true"><MessageCircleMore size={17} /></span>
          <div><small>Understood</small><strong>{scenario.intent}</strong></div>
        </article>

        <article className={`${styles.event} ${styles.context}`}>
          <span className={styles.eventIcon} aria-hidden="true"><Database size={17} /></span>
          <div>
            <small>Approved customer context</small>
            <ul>{scenario.context.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        </article>

        <article className={`${styles.event} ${styles.tool}`}>
          <span className={styles.eventIcon} aria-hidden="true"><Wrench size={17} /></span>
          <div><small>Backend action</small><code translate="no">{scenario.tool}</code></div>
        </article>

        <article className={`${styles.event} ${styles.result}`}>
          <span className={styles.eventIcon} aria-hidden="true"><Check size={17} /></span>
          <div><small>Trusted result</small><strong>{scenario.result}</strong></div>
        </article>

        <article className={`${styles.event} ${styles.response}`}>
          <span className={styles.eventIcon} aria-hidden="true"><Sparkles size={17} /></span>
          <div><small>Svara</small><strong>“{scenario.response}”</strong></div>
        </article>
      </div>
    </div>
  );

  if (variant === "hero") {
    return <div className={styles.heroWrap} role="region" aria-label="Interactive Svara product simulation">{demo}</div>;
  }

  return (
    <section className={styles.section} id="conversation-demo" aria-labelledby="conversation-demo-title">
      <div className={styles.intro}>
        <p className={styles.kicker}>See the product thinking</p>
        <h2 id="conversation-demo-title">One request. The right context. A useful answer.</h2>
        <p>
          Choose a scenario to see how a customer request becomes an approved backend action and a natural response.
          This is an interactive text demonstration, not a live call.
        </p>
      </div>
      {demo}
    </section>
  );
}
