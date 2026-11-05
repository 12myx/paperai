import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { EvidenceTarget } from "../lib/types";
import { EvidenceDrawer } from "../components/EvidenceDrawer";

interface EvidenceContextValue {
  openEvidence: (sourceType: string, sourceId: string, label?: string) => void;
  closeEvidence: () => void;
}

const EvidenceContext = createContext<EvidenceContextValue | null>(null);

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<EvidenceTarget | null>(null);

  const openEvidence = useCallback((sourceType: string, sourceId: string, label?: string) => {
    if (!sourceId) return;
    setTarget({ sourceType, sourceId, label });
  }, []);

  const closeEvidence = useCallback(() => setTarget(null), []);

  const value = useMemo(() => ({ openEvidence, closeEvidence }), [openEvidence, closeEvidence]);

  return (
    <EvidenceContext.Provider value={value}>
      {children}
      <EvidenceDrawer target={target} onClose={closeEvidence} />
    </EvidenceContext.Provider>
  );
}

export function useEvidence(): EvidenceContextValue {
  const context = useContext(EvidenceContext);
  if (!context) throw new Error("useEvidence must be used inside EvidenceProvider");
  return context;
}
