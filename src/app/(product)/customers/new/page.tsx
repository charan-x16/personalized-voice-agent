import { ArrowLeft, KeyRound, MailCheck, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CustomerOnboardingForm } from "@/components/customer-onboarding-form";
import { getCurrentProfile } from "@/lib/server-api";
import styles from "../customers.module.css";

export default async function NewCustomerPage() {
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");
  if (profile.role !== "admin") redirect("/dashboard");

  return (
    <div className={styles.workspace}>
      <Link href="/customers" className={styles.backLink}>
        <ArrowLeft size={16} aria-hidden="true" /> Customer directory
      </Link>

      <header className={styles.onboardingHeader}>
        <div>
          <p className="eyebrow">Workspace onboarding</p>
          <h1 className={`${styles.pageTitle} display-type`}>Add a customer.</h1>
          <p className={styles.pageIntro}>
            Create a tenant-isolated profile, prepare its voice-agent defaults, and invite the
            customer to their secure workspace.
          </p>
        </div>
        <div className={styles.onboardingSteps} aria-label="Onboarding outcomes">
          <span><ShieldCheck size={16} aria-hidden="true" /> Scoped to {profile.workspace_name}</span>
          <span><MailCheck size={16} aria-hidden="true" /> Clerk invitation sent by email</span>
          <span><KeyRound size={16} aria-hidden="true" /> Database controls final access</span>
        </div>
      </header>

      <CustomerOnboardingForm />
    </div>
  );
}
