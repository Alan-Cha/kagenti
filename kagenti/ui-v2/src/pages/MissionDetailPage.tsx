// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  Label,
  Button,
  ButtonVariant,
  Modal,
  ModalVariant,
  TextContent,
  Text,
  Icon,
  Tabs,
  Tab,
  TabTitleText,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  LabelGroup,
  Split,
  SplitItem,
  Form,
  FormGroup,
  TextInput,
  TextArea,
  HelperText,
  HelperTextItem,
  FormHelperText,
} from '@patternfly/react-core';
import {
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
} from '@patternfly/react-table';
import {
  ExclamationTriangleIcon,
  CheckCircleIcon,
  ArrowLeftIcon,
  PlusCircleIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import type { Mission, MissionStatus, ScopeExpansion } from '@/types/mission';
import { missionService } from '@/services/api';

const STATUS_COLORS: Record<MissionStatus, 'blue' | 'green' | 'orange' | 'red' | 'grey'> = {
  pending: 'blue',
  active: 'green',
  completed: 'grey',
  canceled: 'red',
  expired: 'orange',
};

const EXPANSION_STATUS_COLORS: Record<string, 'blue' | 'green' | 'red'> = {
  pending: 'blue',
  approved: 'green',
  denied: 'red',
};

export const MissionDetailPage: React.FC = () => {
  const { missionId } = useParams<{ missionId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState(0);
  const [approveModalOpen, setApproveModalOpen] = useState(false);
  const [cancelModalOpen, setCancelModalOpen] = useState(false);

  const {
    data: mission,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['mission', missionId],
    queryFn: () => missionService.get(missionId!),
    enabled: !!missionId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'pending' || status === 'active' ? 10000 : false;
    },
  });

  const approveMutation = useMutation({
    mutationFn: () => missionService.approve(missionId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mission', missionId] });
      queryClient.invalidateQueries({ queryKey: ['missions'] });
      setApproveModalOpen(false);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => missionService.cancel(missionId!, 'Canceled by operator'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mission', missionId] });
      queryClient.invalidateQueries({ queryKey: ['missions'] });
      setCancelModalOpen(false);
    },
  });

  const approveExpansionMutation = useMutation({
    mutationFn: (expansionId: string) =>
      missionService.approveExpansion(missionId!, expansionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mission', missionId] });
      queryClient.invalidateQueries({ queryKey: ['mission-expansions', missionId] });
    },
  });

  const denyExpansionMutation = useMutation({
    mutationFn: (expansionId: string) =>
      missionService.denyExpansion(missionId!, expansionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mission', missionId] });
      queryClient.invalidateQueries({ queryKey: ['mission-expansions', missionId] });
    },
  });

  if (isLoading) {
    return (
      <PageSection>
        <Spinner aria-label="Loading mission" />
      </PageSection>
    );
  }

  if (isError || !mission) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Mission not found"
            headingLevel="h2"
            icon={
              <EmptyStateIcon
                icon={ExclamationTriangleIcon}
                color="var(--pf-global--danger-color--100)"
              />
            }
          />
          <EmptyStateBody>{String(error ?? 'Unknown error')}</EmptyStateBody>
        </EmptyState>
      </PageSection>
    );
  }

  const canApprove = mission.status === 'pending';
  const canCancel = mission.status === 'pending' || mission.status === 'active';

  return (
    <PageSection>
      {/* Back link */}
      <Button
        variant={ButtonVariant.link}
        icon={<ArrowLeftIcon />}
        onClick={() => navigate('/missions')}
        style={{ paddingLeft: 0, marginBottom: '1rem' }}
      >
        Back to missions
      </Button>

      {/* Header */}
      <Split hasGutter style={{ alignItems: 'center', marginBottom: '1.5rem' }}>
        <SplitItem isFilled>
          <Title headingLevel="h1" size="xl">
            {mission.mission_id}
          </Title>
          <TextContent>
            <Text component="small" style={{ color: 'var(--pf-global--Color--200)' }}>
              {mission.task}
            </Text>
          </TextContent>
        </SplitItem>
        <SplitItem>
          <Label color={STATUS_COLORS[mission.status]} style={{ marginRight: '0.75rem' }}>
            {mission.status}
          </Label>
          {canApprove && (
            <Button
              variant="primary"
              icon={<CheckCircleIcon />}
              onClick={() => setApproveModalOpen(true)}
              style={{ marginRight: '0.5rem' }}
            >
              Approve
            </Button>
          )}
          {canCancel && (
            <Button variant="danger" onClick={() => setCancelModalOpen(true)}>
              Cancel
            </Button>
          )}
        </SplitItem>
      </Split>

      {/* Tabs */}
      <Tabs
        activeKey={activeTab}
        onSelect={(_e, k) => setActiveTab(Number(k))}
        aria-label="Mission details tabs"
      >
        <Tab eventKey={0} title={<TabTitleText>Overview</TabTitleText>}>
          <div style={{ paddingTop: '1.5rem' }}>
            <DescriptionList isHorizontal columnModifier={{ default: '2Col' }}>
              <DescriptionListGroup>
                <DescriptionListTerm>Mission ID</DescriptionListTerm>
                <DescriptionListDescription>
                  <code>{mission.mission_id}</code>
                </DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Status</DescriptionListTerm>
                <DescriptionListDescription>
                  <Label color={STATUS_COLORS[mission.status]} isCompact>
                    {mission.status}
                  </Label>
                </DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Agent</DescriptionListTerm>
                <DescriptionListDescription>{mission.agent_id}</DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Created by</DescriptionListTerm>
                <DescriptionListDescription>{mission.created_by}</DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Created at</DescriptionListTerm>
                <DescriptionListDescription>
                  {new Date(mission.created_at).toLocaleString()}
                </DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Expires at</DescriptionListTerm>
                <DescriptionListDescription>
                  {new Date(mission.expires_at).toLocaleString()}
                </DescriptionListDescription>
              </DescriptionListGroup>

              {mission.approved_by && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Approved by</DescriptionListTerm>
                  <DescriptionListDescription>
                    {mission.approved_by} at{' '}
                    {mission.approved_at
                      ? new Date(mission.approved_at).toLocaleString()
                      : '—'}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              )}

              <DescriptionListGroup>
                <DescriptionListTerm>Usage count</DescriptionListTerm>
                <DescriptionListDescription>
                  {mission.usage_count}
                  {mission.last_exchange_at && (
                    <span style={{ color: 'var(--pf-global--Color--200)', marginLeft: '0.5rem' }}>
                      (last: {new Date(mission.last_exchange_at).toLocaleString()})
                    </span>
                  )}
                </DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Scopes</DescriptionListTerm>
                <DescriptionListDescription>
                  <LabelGroup>
                    {mission.scope.map((s) => (
                      <Label key={s} isCompact variant="outline">
                        {s}
                      </Label>
                    ))}
                  </LabelGroup>
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </div>
        </Tab>

        <Tab eventKey={1} title={<TabTitleText>Audit Log</TabTitleText>}>
          <MissionAuditLog mission={mission} />
        </Tab>

        <Tab eventKey={2} title={<TabTitleText>Scope Expansions</TabTitleText>}>
          <ScopeExpansionsTab
            missionId={mission.mission_id}
            missionStatus={mission.status}
            onApprove={(expId) => approveExpansionMutation.mutate(expId)}
            onDeny={(expId) => denyExpansionMutation.mutate(expId)}
            isApproving={approveExpansionMutation.isPending}
            isDenying={denyExpansionMutation.isPending}
          />
        </Tab>
      </Tabs>

      {/* Approve modal */}
      <Modal
        variant={ModalVariant.small}
        title="Approve mission"
        isOpen={approveModalOpen}
        onClose={() => setApproveModalOpen(false)}
        actions={[
          <Button
            key="approve"
            variant="primary"
            isLoading={approveMutation.isPending}
            onClick={() => approveMutation.mutate()}
          >
            Approve
          </Button>,
          <Button key="cancel" variant="link" onClick={() => setApproveModalOpen(false)}>
            Cancel
          </Button>,
        ]}
      >
        <TextContent>
          <Text>
            Approve mission <strong>{mission.mission_id}</strong>?
          </Text>
          <Text component="small">
            Agent <strong>{mission.agent_id}</strong> will be granted scopes:{' '}
            {mission.scope.join(', ')}
          </Text>
        </TextContent>
      </Modal>

      {/* Cancel modal */}
      <Modal
        variant={ModalVariant.small}
        title="Cancel mission"
        isOpen={cancelModalOpen}
        onClose={() => setCancelModalOpen(false)}
        actions={[
          <Button
            key="confirm"
            variant="danger"
            isLoading={cancelMutation.isPending}
            onClick={() => cancelMutation.mutate()}
          >
            Cancel mission
          </Button>,
          <Button key="keep" variant="link" onClick={() => setCancelModalOpen(false)}>
            Keep mission
          </Button>,
        ]}
      >
        <TextContent>
          <Text>
            <Icon status="warning">
              <ExclamationTriangleIcon />
            </Icon>{' '}
            Cancel mission <strong>{mission.mission_id}</strong>? Any issued mission tokens
            will be invalidated and no further token exchanges will be permitted.
          </Text>
        </TextContent>
      </Modal>
    </PageSection>
  );
};

// ─── Audit Log sub-component ────────────────────────────────────────────────

interface AuditEvent {
  timestamp: string;
  actor: string;
  action: string;
  detail?: string;
}

const MissionAuditLog: React.FC<{ mission: Mission }> = ({ mission }) => {
  const events: AuditEvent[] = [];

  events.push({
    timestamp: mission.created_at,
    actor: mission.created_by,
    action: 'Mission requested',
    detail: `Scopes: ${mission.scope.join(', ')}`,
  });

  if (mission.approved_at && mission.approved_by) {
    events.push({
      timestamp: mission.approved_at,
      actor: mission.approved_by,
      action: 'Mission approved',
    });
  }

  if (mission.last_exchange_at) {
    events.push({
      timestamp: mission.last_exchange_at,
      actor: mission.agent_id,
      action: `Token exchanged`,
      detail: `Total exchanges: ${mission.usage_count}`,
    });
  }

  if (mission.status === 'canceled') {
    // canceled_at isn't in the response schema yet; approximate with last update
    events.push({
      timestamp: mission.last_exchange_at ?? mission.approved_at ?? mission.created_at,
      actor: '—',
      action: 'Mission canceled',
    });
  }

  if (mission.status === 'expired') {
    events.push({
      timestamp: mission.expires_at,
      actor: 'system',
      action: 'Mission expired',
    });
  }

  // Sort descending (most recent first)
  events.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  const ACTION_COLORS: Record<string, 'green' | 'blue' | 'orange' | 'red' | 'grey'> = {
    'Mission requested': 'blue',
    'Mission approved': 'green',
    'Token exchanged': 'grey',
    'Mission canceled': 'red',
    'Mission expired': 'orange',
  };

  return (
    <div style={{ paddingTop: '1rem' }}>
      <Table aria-label="Audit log" variant="compact">
        <Thead>
          <Tr>
            <Th>Time</Th>
            <Th>Actor</Th>
            <Th>Action</Th>
            <Th>Detail</Th>
          </Tr>
        </Thead>
        <Tbody>
          {events.map((ev, i) => (
            <Tr key={i}>
              <Td style={{ whiteSpace: 'nowrap' }}>
                {new Date(ev.timestamp).toLocaleString()}
              </Td>
              <Td>{ev.actor}</Td>
              <Td>
                <Label
                  isCompact
                  color={ACTION_COLORS[ev.action] ?? 'grey'}
                >
                  {ev.action}
                </Label>
              </Td>
              <Td>{ev.detail ?? '—'}</Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  );
};

// ─── Scope Expansions sub-component ─────────────────────────────────────────

interface ScopeExpansionsTabProps {
  missionId: string;
  missionStatus: MissionStatus;
  onApprove: (expansionId: string) => void;
  onDeny: (expansionId: string) => void;
  isApproving: boolean;
  isDenying: boolean;
}

const ScopeExpansionsTab: React.FC<ScopeExpansionsTabProps> = ({
  missionId,
  missionStatus,
  onApprove,
  onDeny,
  isApproving,
  isDenying,
}) => {
  const queryClient = useQueryClient();
  const [requestModalOpen, setRequestModalOpen] = useState(false);
  const [reqAgent, setReqAgent] = useState('');
  const [reqScopeInput, setReqScopeInput] = useState('');
  const [reqScopes, setReqScopes] = useState<string[]>([]);
  const [reqJustification, setReqJustification] = useState('');

  const requestMutation = useMutation({
    mutationFn: () =>
      missionService.requestExpansion(missionId, {
        requesting_agent: reqAgent,
        additional_scopes: reqScopes,
        justification: reqJustification,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mission', missionId] });
      setRequestModalOpen(false);
      setReqAgent(''); setReqScopes([]); setReqScopeInput(''); setReqJustification('');
    },
  });

  const addReqScope = () => {
    const s = reqScopeInput.trim().toLowerCase().replace(/\s+/g, '_');
    if (s && !reqScopes.includes(s)) { setReqScopes([...reqScopes, s]); setReqScopeInput(''); }
  };

  const { data: mission } = useQuery<Mission>({
    queryKey: ['mission', missionId],
    queryFn: () => missionService.get(missionId),
    enabled: !!missionId,
  });

  const expansions: ScopeExpansion[] = (mission as unknown as { expansions?: ScopeExpansion[] })
    ?.expansions ?? [];

  return (
    <div style={{ paddingTop: '1rem' }}>
      {missionStatus === 'active' && (
        <div style={{ marginBottom: '1rem' }}>
          <Button
            variant="secondary"
            icon={<PlusCircleIcon />}
            onClick={() => setRequestModalOpen(true)}
          >
            Request scope expansion
          </Button>
        </div>
      )}

      {expansions.length === 0 ? (
        <EmptyState>
          <EmptyStateHeader titleText="No scope expansion requests" headingLevel="h3" />
          <EmptyStateBody>
            Scope expansion requests will appear here. Use the button above to request
            additional scopes for this mission.
          </EmptyStateBody>
        </EmptyState>
      ) : (
        <Table aria-label="Scope expansions" variant="compact">
          <Thead>
            <Tr>
              <Th>ID</Th>
              <Th>Requested by</Th>
              <Th>Additional scopes</Th>
              <Th>Justification</Th>
              <Th>Status</Th>
              <Th>Requested at</Th>
              {missionStatus === 'active' && <Th aria-label="Actions" />}
            </Tr>
          </Thead>
          <Tbody>
            {expansions.map((exp) => (
              <Tr key={exp.expansion_id}>
                <Td><code style={{ fontSize: '0.8em' }}>{exp.expansion_id}</code></Td>
                <Td>{exp.requested_by}</Td>
                <Td>
                  <LabelGroup>
                    {exp.additional_scopes.map((s) => (
                      <Label key={s} isCompact variant="outline">{s}</Label>
                    ))}
              </LabelGroup>
            </Td>
            <Td>
              <span title={exp.justification} style={{ maxWidth: '200px', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {exp.justification}
              </span>
            </Td>
            <Td>
              <Label
                color={EXPANSION_STATUS_COLORS[exp.status] ?? 'grey'}
                isCompact
              >
                {exp.status}
              </Label>
            </Td>
            <Td>{new Date(exp.requested_at).toLocaleString()}</Td>
            {missionStatus === 'active' && (
              <Td>
                {exp.status === 'pending' && (
                  <>
                    <Button
                      variant="primary"
                      size="sm"
                      isLoading={isApproving}
                      onClick={() => onApprove(exp.expansion_id)}
                      style={{ marginRight: '0.5rem' }}
                    >
                      Approve
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      isLoading={isDenying}
                      onClick={() => onDeny(exp.expansion_id)}
                    >
                      Deny
                    </Button>
                  </>
                )}
              </Td>
            )}
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}

      {/* Request expansion modal */}
      <Modal
        variant={ModalVariant.medium}
        title="Request scope expansion"
        isOpen={requestModalOpen}
        onClose={() => setRequestModalOpen(false)}
        actions={[
          <Button
            key="submit"
            variant="primary"
            isLoading={requestMutation.isPending}
            isDisabled={!reqAgent || reqScopes.length === 0 || reqJustification.trim().length < 10}
            onClick={() => requestMutation.mutate()}
          >
            Submit request
          </Button>,
          <Button key="cancel" variant="link" onClick={() => setRequestModalOpen(false)}>
            Cancel
          </Button>,
        ]}
      >
        <Form>
          <FormGroup label="Requesting agent" isRequired fieldId="reqAgent">
            <TextInput
              id="reqAgent"
              value={reqAgent}
              onChange={(_e, v) => setReqAgent(v)}
              placeholder="e.g. research-agent"
            />
          </FormGroup>
          <FormGroup
            label="Additional scopes"
            isRequired
            fieldId="reqScopes"
          >
            <Split hasGutter>
              <SplitItem isFilled>
                <TextInput
                  id="reqScopeInput"
                  value={reqScopeInput}
                  onChange={(_e, v) => setReqScopeInput(v)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addReqScope(); } }}
                  placeholder="e.g. image_optimize"
                />
              </SplitItem>
              <SplitItem>
                <Button variant="secondary" icon={<PlusCircleIcon />} onClick={addReqScope}>Add</Button>
              </SplitItem>
            </Split>
            {reqScopes.length > 0 && (
              <LabelGroup style={{ marginTop: '0.5rem' }}>
                {reqScopes.map((s) => (
                  <Label key={s} isCompact variant="outline"
                    onClose={() => setReqScopes(reqScopes.filter((x) => x !== s))}>
                    {s}
                  </Label>
                ))}
              </LabelGroup>
            )}
          </FormGroup>
          <FormGroup
            label="Justification"
            isRequired
            fieldId="reqJustification"
          >
            <TextArea
              id="reqJustification"
              value={reqJustification}
              onChange={(_e, v) => setReqJustification(v)}
              rows={3}
              placeholder="e.g. Found 3 large diagrams that need compression before upload."
            />
            <FormHelperText>
              <HelperText>
                <HelperTextItem
                  variant={reqJustification.trim().length > 0 && reqJustification.trim().length < 10 ? 'error' : 'default'}
                >
                  {reqJustification.trim().length < 10
                    ? `At least 10 characters required (${reqJustification.trim().length}/10)`
                    : 'Explain why these additional scopes are needed.'}
                </HelperTextItem>
              </HelperText>
            </FormHelperText>
          </FormGroup>
        </Form>
      </Modal>
    </div>
  );
};
