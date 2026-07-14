// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Button,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  Label,
  Modal,
  ModalVariant,
  TextContent,
  Text,
  Icon,
  Dropdown,
  DropdownList,
  DropdownItem,
  MenuToggle,
  MenuToggleElement,
  FormSelect,
  FormSelectOption,
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
  ListIcon,
  EllipsisVIcon,
  ExclamationTriangleIcon,
  CheckCircleIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import type { Mission, MissionStatus } from '@/types/mission';
import { missionService } from '@/services/api';

const STATUS_COLORS: Record<MissionStatus, 'blue' | 'green' | 'orange' | 'red' | 'grey'> = {
  pending: 'blue',
  active: 'green',
  completed: 'grey',
  canceled: 'red',
  expired: 'orange',
};

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'canceled', label: 'Canceled' },
  { value: 'expired', label: 'Expired' },
];

export const MissionCatalogPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [missionToCancel, setMissionToCancel] = useState<Mission | null>(null);
  const [approveModalOpen, setApproveModalOpen] = useState(false);
  const [missionToApprove, setMissionToApprove] = useState<Mission | null>(null);

  const {
    data,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['missions', statusFilter],
    queryFn: () => missionService.list({ status: statusFilter || undefined }),
    refetchInterval: 10000,
  });

  const missions = data?.missions ?? [];

  const approveMutation = useMutation({
    mutationFn: (mission: Mission) => missionService.approve(mission.mission_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['missions'] });
      setApproveModalOpen(false);
      setMissionToApprove(null);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (mission: Mission) =>
      missionService.cancel(mission.mission_id, 'Canceled by operator'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['missions'] });
      setCancelModalOpen(false);
      setMissionToCancel(null);
    },
  });

  const handleApproveClick = (mission: Mission) => {
    setMissionToApprove(mission);
    setApproveModalOpen(true);
    setOpenMenuId(null);
  };

  const handleCancelClick = (mission: Mission) => {
    setMissionToCancel(mission);
    setCancelModalOpen(true);
    setOpenMenuId(null);
  };

  if (isLoading) {
    return (
      <PageSection>
        <Spinner aria-label="Loading missions" />
      </PageSection>
    );
  }

  if (isError) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Failed to load missions"
            headingLevel="h2"
            icon={<EmptyStateIcon icon={ExclamationTriangleIcon} color="var(--pf-global--danger-color--100)" />}
          />
          <EmptyStateBody>{String(error)}</EmptyStateBody>
        </EmptyState>
      </PageSection>
    );
  }

  return (
    <PageSection>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1rem' }}>
        Missions
      </Title>

      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <FormSelect
              value={statusFilter}
              onChange={(_e, v) => setStatusFilter(v)}
              aria-label="Filter by status"
              style={{ width: '180px' }}
            >
              {STATUS_OPTIONS.map((opt) => (
                <FormSelectOption key={opt.value} value={opt.value} label={opt.label} />
              ))}
            </FormSelect>
          </ToolbarItem>
          <ToolbarItem>
            <Button variant="primary" onClick={() => navigate('/missions/new')}>
              Request mission
            </Button>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      {missions.length === 0 ? (
        <EmptyState>
          <EmptyStateHeader
            titleText="No missions found"
            headingLevel="h2"
            icon={<EmptyStateIcon icon={ListIcon} />}
          />
          <EmptyStateBody>
            {statusFilter
              ? `No missions with status "${statusFilter}".`
              : 'No missions have been created yet.'}
          </EmptyStateBody>
        </EmptyState>
      ) : (
        <Table aria-label="Missions table" variant="compact">
          <Thead>
            <Tr>
              <Th>Mission ID</Th>
              <Th>Task</Th>
              <Th>Agent</Th>
              <Th>Status</Th>
              <Th>Scopes</Th>
              <Th>Created</Th>
              <Th>Expires</Th>
              <Th aria-label="Actions" />
            </Tr>
          </Thead>
          <Tbody>
            {missions.map((mission) => (
              <Tr
                key={mission.mission_id}
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/missions/${mission.mission_id}`)}
              >
                <Td>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.85em' }}>
                    {mission.mission_id}
                  </span>
                </Td>
                <Td>
                  <span
                    title={mission.task}
                    style={{
                      display: 'block',
                      maxWidth: '280px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {mission.task}
                  </span>
                </Td>
                <Td>{mission.agent_id}</Td>
                <Td>
                  <Label color={STATUS_COLORS[mission.status]} isCompact>
                    {mission.status}
                  </Label>
                </Td>
                <Td>
                  {mission.scope.slice(0, 2).map((s) => (
                    <Label key={s} isCompact variant="outline" style={{ marginRight: '4px' }}>
                      {s}
                    </Label>
                  ))}
                  {mission.scope.length > 2 && (
                    <Label isCompact variant="outline" color="grey">
                      +{mission.scope.length - 2}
                    </Label>
                  )}
                </Td>
                <Td>{new Date(mission.created_at).toLocaleString()}</Td>
                <Td>{new Date(mission.expires_at).toLocaleDateString()}</Td>
                <Td isActionCell onClick={(e) => e.stopPropagation()}>
                  <Dropdown
                    isOpen={openMenuId === mission.mission_id}
                    onSelect={() => setOpenMenuId(null)}
                    onOpenChange={(open) =>
                      setOpenMenuId(open ? mission.mission_id : null)
                    }
                    toggle={(ref: React.Ref<MenuToggleElement>) => (
                      <MenuToggle
                        ref={ref}
                        variant="plain"
                        aria-label="Mission actions"
                        onClick={() =>
                          setOpenMenuId(
                            openMenuId === mission.mission_id ? null : mission.mission_id,
                          )
                        }
                        isExpanded={openMenuId === mission.mission_id}
                      >
                        <EllipsisVIcon />
                      </MenuToggle>
                    )}
                    popperProps={{ position: 'right' }}
                  >
                    <DropdownList>
                      <DropdownItem
                        key="view"
                        onClick={() => navigate(`/missions/${mission.mission_id}`)}
                      >
                        View details
                      </DropdownItem>
                      {mission.status === 'pending' && (
                        <DropdownItem
                          key="approve"
                          onClick={() => handleApproveClick(mission)}
                        >
                          <Icon status="success">
                            <CheckCircleIcon />
                          </Icon>{' '}
                          Approve
                        </DropdownItem>
                      )}
                      {(mission.status === 'pending' || mission.status === 'active') && (
                        <DropdownItem
                          key="cancel"
                          onClick={() => handleCancelClick(mission)}
                          isDanger
                        >
                          Cancel
                        </DropdownItem>
                      )}
                    </DropdownList>
                  </Dropdown>
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}

      {/* Approve confirmation */}
      <Modal
        variant={ModalVariant.small}
        title="Approve mission"
        isOpen={approveModalOpen}
        onClose={() => {
          setApproveModalOpen(false);
          setMissionToApprove(null);
        }}
        actions={[
          <Button
            key="approve"
            variant="primary"
            isLoading={approveMutation.isPending}
            onClick={() => missionToApprove && approveMutation.mutate(missionToApprove)}
          >
            Approve
          </Button>,
          <Button
            key="cancel"
            variant="link"
            onClick={() => {
              setApproveModalOpen(false);
              setMissionToApprove(null);
            }}
          >
            Cancel
          </Button>,
        ]}
      >
        {missionToApprove && (
          <TextContent>
            <Text>
              Approve mission <strong>{missionToApprove.mission_id}</strong>?
            </Text>
            <Text component="small">{missionToApprove.task}</Text>
            <Text component="small">
              Scopes: {missionToApprove.scope.join(', ')}
            </Text>
          </TextContent>
        )}
      </Modal>

      {/* Cancel confirmation */}
      <Modal
        variant={ModalVariant.small}
        title="Cancel mission"
        isOpen={cancelModalOpen}
        onClose={() => {
          setCancelModalOpen(false);
          setMissionToCancel(null);
        }}
        actions={[
          <Button
            key="confirm"
            variant="danger"
            isLoading={cancelMutation.isPending}
            onClick={() => missionToCancel && cancelMutation.mutate(missionToCancel)}
          >
            Cancel mission
          </Button>,
          <Button
            key="close"
            variant="link"
            onClick={() => {
              setCancelModalOpen(false);
              setMissionToCancel(null);
            }}
          >
            Keep mission
          </Button>,
        ]}
      >
        {missionToCancel && (
          <TextContent>
            <Text>
              <Icon status="warning">
                <ExclamationTriangleIcon />
              </Icon>{' '}
              Cancel mission <strong>{missionToCancel.mission_id}</strong>? This will
              revoke the mission and prevent any further token exchanges.
            </Text>
          </TextContent>
        )}
      </Modal>
    </PageSection>
  );
};
