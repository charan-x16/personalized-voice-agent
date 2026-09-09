"use client";

import { useClerk, UserButton } from "@clerk/nextjs";
import {
  AudioLines,
  History,
  Home,
  LogOut,
  Menu,
  UsersRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Brand } from "@/components/brand";
import { useConfirmSignOut } from "@/components/editor-drafts";
import type { MeResponse } from "@/lib/api-types";
import styles from "./app-shell.module.css";

type AppShellProfile = Pick<
  MeResponse,
  "full_name" | "initials" | "workspace_name" | "role"
>;

const customerNavigation = [
  { href: "/dashboard", label: "Overview", icon: Home },
  { href: "/voice", label: "Voice room", icon: AudioLines },
  { href: "/conversations", label: "Conversations", icon: History },
];

const adminNavigation = [
  { href: "/customers", label: "Customers", icon: UsersRound },
];

export function AppShell({
  children,
  profile,
}: {
  children: React.ReactNode;
  profile: AppShellProfile;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut: clerkSignOut } = useClerk();
  const confirmSignOut = useConfirmSignOut();
  const [menuOpen, setMenuOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);

  const closeMenu = useCallback((restoreFocus = false) => {
    setMenuOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => menuButtonRef.current?.focus());
    }
  }, []);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 780px)");
    const syncViewport = () => {
      setIsMobile(query.matches);
      if (!query.matches) setMenuOpen(false);
    };

    syncViewport();
    query.addEventListener("change", syncViewport);
    return () => query.removeEventListener("change", syncViewport);
  }, []);

  useEffect(() => {
    if (!isMobile || !menuOpen) return;

    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu(true);
        return;
      }

      if (event.key !== "Tab") return;
      const focusable = Array.from(
        sidebarRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => !element.hasAttribute("inert"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [closeMenu, isMobile, menuOpen]);

  const drawerHidden = isMobile && !menuOpen;
  const isAdmin = profile.role === "admin";
  const navigation = isAdmin ? adminNavigation : customerNavigation;

  const signOut = useCallback(async () => {
    if (isSigningOut) return;
    if (!confirmSignOut()) return;
    setIsSigningOut(true);
    setSignOutError(null);

    try {
      await clerkSignOut({ redirectUrl: "/" });
      router.refresh();
    } catch {
      setSignOutError("Could not sign out. Please try again.");
      setIsSigningOut(false);
    }
  }, [clerkSignOut, confirmSignOut, isSigningOut, router]);

  return (
    <div className={styles.shell}>
      <a
        className={styles.skipLink}
        href="#workspace-main"
        tabIndex={isMobile && menuOpen ? -1 : undefined}
      >
        Skip to main content
      </a>
      <aside
        ref={sidebarRef}
        id="workspace-navigation"
        className={`${styles.sidebar} ${menuOpen ? styles.sidebarOpen : ""}`}
        aria-hidden={drawerHidden || undefined}
        aria-modal={isMobile && menuOpen ? true : undefined}
        aria-label={isMobile && menuOpen ? "Workspace navigation" : undefined}
        role={isMobile && menuOpen ? "dialog" : undefined}
        inert={drawerHidden || undefined}
      >
        <div className={styles.brandRow}>
          <Brand />
          <button
            ref={closeButtonRef}
            className={styles.mobileClose}
            onClick={() => closeMenu(true)}
            aria-label="Close navigation"
          >
            <X size={19} aria-hidden="true" />
          </button>
        </div>

        <div className={styles.workspaceContext}>
          <span>{isAdmin ? "Workspace admin" : "Personal workspace"}</span>
          <strong>{profile.workspace_name}</strong>
        </div>

        <nav className={styles.nav} aria-label="Workspace navigation">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));
            return (
              <Link
                key={href}
                href={href}
                className={`${styles.navItem} ${active ? styles.active : ""}`}
                onClick={() => setMenuOpen(false)}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className={styles.sidebarFoot}>
          <button
            type="button"
            className={`${styles.navItem} ${styles.signOutButton}`}
            onClick={signOut}
            disabled={isSigningOut}
          >
            <LogOut size={17} strokeWidth={1.8} aria-hidden="true" />
            <span>{isSigningOut ? "Signing out\u2026" : "Sign out"}</span>
          </button>
          {signOutError && (
            <p className={styles.signOutError} role="alert">
              {signOutError}
            </p>
          )}
          <div className={styles.profile}>
            <span className={styles.userButton}>
              <UserButton
                appearance={{ elements: { avatarBox: styles.userButtonAvatar } }}
              />
            </span>
            <span className={styles.profileCopy}>
              <strong>{profile.full_name}</strong>
              <small>{isAdmin ? "Administrator access" : "Customer access"}</small>
            </span>
          </div>
        </div>
      </aside>

      {menuOpen && <button className={styles.scrim} aria-label="Close navigation" onClick={() => closeMenu(true)} />}

      <main
        className={styles.main}
        id="workspace-main"
        inert={(isMobile && menuOpen) || undefined}
        aria-hidden={(isMobile && menuOpen) || undefined}
      >
        <header className={styles.mobileHeader}>
          <Brand />
          <button
            ref={menuButtonRef}
            className={styles.menuButton}
            onClick={() => setMenuOpen(true)}
            aria-label="Open navigation"
            aria-expanded={menuOpen}
            aria-controls="workspace-navigation"
          >
            <Menu size={20} aria-hidden="true" />
          </button>
        </header>
        {children}
      </main>
    </div>
  );
}
