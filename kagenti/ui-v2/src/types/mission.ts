// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

export type MissionStatus = 'pending' | 'active' | 'completed' | 'canceled' | 'expired';

export interface Mission {
  mission_id: string;
  status: MissionStatus;
  task: string;
  agent_id: string;
  scope: string[];
  created_at: string;
  created_by: string;
  approved_at: string | null;
  approved_by: string | null;
  expires_at: string;
  usage_count: number;
  last_exchange_at: string | null;
}

export interface MissionCreateRequest {
  task: string;
  agent_id: string;
  scope: string[];
  validation: ValidationPolicy;
  labels?: Record<string, string>;
}

export interface MissionCreateResponse {
  mission_id: string;
  status: MissionStatus;
  created_at: string;
  expires_at: string;
  approval_url: string | null;
}

export interface MissionApproveResponse {
  mission_id: string;
  status: MissionStatus;
  approved_at: string;
  approved_by: string;
  mission_token: string;
}

export interface MissionListResponse {
  missions: Mission[];
  total: number;
  page: number;
  page_size: number;
}

export interface ValidationPolicy {
  type: 'on_demand' | 'scheduled' | 'custom';
  max_uses?: number;
  valid_until?: string;
  schedule?: string;
  timezone?: string;
  window_minutes?: number;
  duration_days?: number;
}

export interface ScopeExpansion {
  expansion_id: string;
  mission_id: string;
  status: 'pending' | 'approved' | 'denied';
  requested_at: string;
  requested_by: string;
  additional_scopes: string[];
  justification: string;
  approved_by: string | null;
  approved_at: string | null;
}

export interface ScopeExpansionRequest {
  requesting_agent: string;
  additional_scopes: string[];
  justification: string;
}
