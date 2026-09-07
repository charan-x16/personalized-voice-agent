"use client";

import { createContext, useCallback, useContext, useEffect, useState, type Dispatch, type SetStateAction } from "react";

type DraftStore = { values: Map<string, unknown>; dirty: Set<string> };
const DraftContext = createContext<DraftStore | null>(null);

/** Memory-only and scoped to the authenticated workspace. Never persist customer data to storage. */
export function EditorDraftProvider({ children }: { children: React.ReactNode }) {
  const [store] = useState<DraftStore>(() => ({ values: new Map(), dirty: new Set() }));

  useEffect(() => {
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!store.dirty.size) return;
      event.preventDefault();
      event.returnValue = "";
    }
    function beforeNavigate(event: MouseEvent) {
      if (!store.dirty.size || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      const destination = new URL(link.href, window.location.href);
      if (destination.pathname === location.pathname && destination.search === location.search && destination.origin === location.origin) return;
      if (!window.confirm("You have unsaved changes. Leave this page? Drafts are kept only while this workspace remains open; signing out or reloading clears them.")) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", beforeNavigate, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", beforeNavigate, true);
    };
  }, [store]);

  return <DraftContext.Provider value={store}>{children}</DraftContext.Provider>;
}

export function useEditorDraftState<T>(key: string, initialValue: T): [T, Dispatch<SetStateAction<T>>] {
  const store = useContext(DraftContext);
  const [value, setValue] = useState<T>(() => store?.values.has(key) ? store.values.get(key) as T : initialValue);
  const update = useCallback<Dispatch<SetStateAction<T>>>((next) => {
    // Editors use value updates. Functional updates resolve against the last stored draft.
    const previous = store?.values.has(key) ? store.values.get(key) as T : initialValue;
    const resolved = typeof next === "function" ? (next as (value: T) => T)(previous) : next;
    store?.values.set(key, resolved);
    setValue(resolved);
  }, [initialValue, key, store]);
  return [value, update];
}

export function useUnsavedEditor(isDirty: boolean, key: string) {
  const store = useContext(DraftContext);
  const clearDraft = useCallback(() => {
    store?.dirty.delete(key);
    for (const draftKey of store?.values.keys() ?? []) {
      if (draftKey.startsWith(`${key}:`)) store?.values.delete(draftKey);
    }
  }, [key, store]);
  useEffect(() => {
    if (isDirty) store?.dirty.add(key);
    else clearDraft();
    // Keep drafts after unmount, including browser Back/Forward navigation.
  }, [clearDraft, key, isDirty, store]);
  return clearDraft;
}

export function useConfirmSignOut() {
  const store = useContext(DraftContext);
  return () => !store?.dirty.size || window.confirm("Sign out? Any unsaved editor drafts in this workspace will be cleared.");
}
