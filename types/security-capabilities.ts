// types/security-capabilities.ts
// Data contracts for the JAKAL Security Capabilities Engine (7 domains).
// Mirrors backend/services/capabilities_engine.py — keep in sync.

export type ModuleCategory =
  | "fleet_rmm"
  | "remote_access"
  | "detect_respond"
  | "soar_playbooks"
  | "patch_vulnerability"
  | "dark_web"
  | "ai_safety_fabric";

export type RiskLevel = "low" | "medium" | "high" | "critical";

/** UI hints so the frontend can render the right control for each action. */
export interface ActionUiHints {
  button?: "primary" | "secondary" | "danger" | "dot";
  cog?: boolean;
  slider?: { field: string; min: number; max: number; value: number };
  radial?: { field: string; options: string[] };
  color?: string;
}

export interface ModuleAction {
  id: string; // e.g. "fleet:isolate_host"
  category: ModuleCategory;
  name: string;
  description: string;
  permission_required: string;
  risk: RiskLevel;
  payload_schema: Record<string, string>;
  ui: ActionUiHints;
}

export interface EndpointCapabilityState {
  agentId: string;
  rmmOnline: boolean;
  remoteAccessActive: boolean;
  edrShieldActive: boolean;
  pendingPatchesCount: number;
  darkWebThreatLevel: RiskLevel;
  aiSafetyFilterEnabled: boolean;
}

// NOTE: fixed the malformed generic from the original spec
// (`SecurityActionPayload<T Record<string, any>>` -> a proper constraint).
export interface SecurityActionPayload<T extends Record<string, any> = Record<string, any>> {
  actionId: string;
  targetEndpointId: string;
  executorId: string;
  timestamp: string;
  params: T;
}

export interface GuardrailResult {
  allowed: boolean;
  exempt?: boolean;
  injection?: { safe: boolean; matched_signatures: string[] };
  blocked_tokens?: string[];
}

export interface ExecuteResult<R = Record<string, any>> {
  ok: boolean;
  blocked?: boolean;
  reason?: string;
  guardrail?: GuardrailResult;
  requires_approval?: boolean;
  approval_id?: string;
  action?: ModuleAction;
  prompt?: string;
  result?: R;
}

export interface PendingApproval {
  approval_id: string;
  action_id: string;
  payload: Record<string, any>;
  executor: string;
  created_at: string;
  risk: RiskLevel;
}

export interface CapabilityCatalog {
  actions: ModuleAction[];
  by_category: Record<ModuleCategory, ModuleAction[]>;
  count: number;
}
