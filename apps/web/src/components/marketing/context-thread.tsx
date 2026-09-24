"use client";

import { useEffect, useRef, useState } from "react";

import styles from "./context-thread.module.css";

const contextSteps = [
  { number: "01", label: "Voice", value: "“Can I move my reservation?”", state: "Customer request" },
  { number: "02", label: "Understand", value: "Modify reservation", state: "Intent recognised" },
  { number: "03", label: "Context", value: "Friday · 8 PM · 4 guests · Indiranagar", state: "Customer scoped" },
  { number: "04", label: "Tool", value: "find_reservation() → reschedule_reservation()", state: "Backend approved" },
  { number: "05", label: "Action", value: "Saturday · 8 PM · 6 guests · confirmed", state: "Record updated" },
  { number: "06", label: "Response", value: "“Done. Your table is updated.”", state: "Spoken naturally" },
] as const;

export function ContextThread() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section || !("IntersectionObserver" in window)) {
      setActive(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setActive(true);
          observer.disconnect();
        }
      },
      { rootMargin: "-12% 0px" },
    );
    observer.observe(section);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={sectionRef}
      className={styles.section}
      id="product"
      aria-labelledby="context-thread-title"
      data-active={active || undefined}
    >
      <div className={styles.heading}>
        <div className={styles.marker}><span>01</span><span>Product</span></div>
        <div>
          <h2 id="context-thread-title">The conversation becomes context.</h2>
          <p>
            Your systems remain the source of truth. Svara asks for only the information a conversation needs,
            then turns an approved result into a clear response.
          </p>
        </div>
      </div>

      <ol className={styles.thread}>
        {contextSteps.map((step, index) => (
          <li key={step.number} style={{ "--step-index": index } as React.CSSProperties}>
            <span className={styles.node} aria-hidden="true" />
            <span className={styles.number}>{step.number}</span>
            <div className={styles.stepCopy}>
              <small>{step.label}</small>
              {step.label === "Tool" ? <code translate="no">{step.value}</code> : <strong>{step.value}</strong>}
            </div>
            <span className={styles.state}>{step.state}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
