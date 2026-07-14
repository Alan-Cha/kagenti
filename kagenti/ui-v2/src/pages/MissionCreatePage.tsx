// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Button,
  Form,
  FormGroup,
  TextInput,
  TextArea,
  FormSelect,
  FormSelectOption,
  ActionGroup,
  Alert,
  Label,
  LabelGroup,
  Split,
  SplitItem,
  Card,
  CardBody,
  CardTitle,
  NumberInput,
  Grid,
  GridItem,
} from '@patternfly/react-core';
import { PlusCircleIcon, ArrowLeftIcon } from '@patternfly/react-icons';
import { useMutation } from '@tanstack/react-query';

import type { MissionCreateRequest, ValidationPolicy } from '@/types/mission';
import { missionService } from '@/services/api';

const VALIDATION_TYPES = [
  { value: 'on_demand', label: 'On demand — limited uses with expiry date' },
  { value: 'scheduled', label: 'Scheduled — runs on a cron schedule' },
];

export const MissionCreatePage: React.FC = () => {
  const navigate = useNavigate();

  // Core fields
  const [task, setTask] = useState('');
  const [agentId, setAgentId] = useState('');
  const [scopeInput, setScopeInput] = useState('');
  const [scopes, setScopes] = useState<string[]>([]);

  // Validation policy
  const [validationType, setValidationType] = useState<'on_demand' | 'scheduled'>('on_demand');
  const [maxUses, setMaxUses] = useState<number>(10);
  const [validUntil, setValidUntil] = useState<string>('');
  const [schedule, setSchedule] = useState('0 9 * * *');
  const [durationDays, setDurationDays] = useState<number>(30);

  // Labels
  const [labelKey, setLabelKey] = useState('');
  const [labelValue, setLabelValue] = useState('');
  const [labels, setLabels] = useState<Record<string, string>>({});

  // Validation errors
  const [errors, setErrors] = useState<Record<string, string>>({});

  const createMutation = useMutation({
    mutationFn: (req: MissionCreateRequest) => missionService.create(req),
    onSuccess: (data) => navigate(`/missions/${data.mission_id}`),
  });

  const addScope = () => {
    const s = scopeInput.trim().toLowerCase().replace(/\s+/g, '_');
    if (s && !scopes.includes(s)) {
      setScopes([...scopes, s]);
      setScopeInput('');
    }
  };

  const removeScope = (s: string) => setScopes(scopes.filter((x) => x !== s));

  const addLabel = () => {
    const k = labelKey.trim();
    const v = labelValue.trim();
    if (k && v) {
      setLabels({ ...labels, [k]: v });
      setLabelKey('');
      setLabelValue('');
    }
  };

  const removeLabel = (k: string) => {
    const next = { ...labels };
    delete next[k];
    setLabels(next);
  };

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!task.trim()) e.task = 'Task description is required';
    if (!agentId.trim()) e.agentId = 'Agent ID is required';
    if (scopes.length === 0) e.scopes = 'At least one scope is required';
    if (validationType === 'on_demand' && !validUntil) e.validUntil = 'Expiry date is required';
    if (validationType === 'scheduled' && !schedule.trim()) e.schedule = 'Schedule is required';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = () => {
    if (!validate()) return;

    let validation: ValidationPolicy;
    if (validationType === 'on_demand') {
      validation = {
        type: 'on_demand',
        max_uses: maxUses,
        valid_until: new Date(validUntil).toISOString(),
      };
    } else {
      validation = {
        type: 'scheduled',
        schedule,
        timezone: 'UTC',
        window_minutes: 30,
        duration_days: durationDays,
      };
    }

    createMutation.mutate({
      task: task.trim(),
      agent_id: agentId.trim(),
      scope: scopes,
      validation,
      labels: Object.keys(labels).length > 0 ? labels : undefined,
    });
  };

  const defaultValidUntil = () => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return d.toISOString().split('T')[0];
  };

  return (
    <PageSection>
      <Button
        variant="link"
        icon={<ArrowLeftIcon />}
        onClick={() => navigate('/missions')}
        style={{ paddingLeft: 0, marginBottom: '1rem' }}
      >
        Back to missions
      </Button>

      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1.5rem' }}>
        Request a mission
      </Title>

      {createMutation.isError && (
        <Alert
          variant="danger"
          title="Failed to create mission"
          style={{ marginBottom: '1.5rem' }}
        >
          {String(createMutation.error)}
        </Alert>
      )}

      <Form style={{ maxWidth: '720px' }}>

        {/* Task */}
        <FormGroup
          label="Task description"
          isRequired
          fieldId="task"
        >
          <TextArea
            id="task"
            value={task}
            onChange={(_e, v) => setTask(v)}
            rows={3}
            placeholder="e.g. Research AI safety literature and update the wiki with a summary"
            validated={errors.task ? 'error' : 'default'}
          />
        </FormGroup>

        {/* Agent ID */}
        <FormGroup
          label="Agent ID"
          isRequired
          fieldId="agentId"
        >
          <TextInput
            id="agentId"
            value={agentId}
            onChange={(_e, v) => setAgentId(v)}
            placeholder="e.g. research-agent"
            validated={errors.agentId ? 'error' : 'default'}
          />
        </FormGroup>

        {/* Scopes */}
        <FormGroup
          label="Scopes"
          isRequired
          fieldId="scopes"
        >
          <Split hasGutter>
            <SplitItem isFilled>
              <TextInput
                id="scopes"
                value={scopeInput}
                onChange={(_e, v) => setScopeInput(v)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addScope(); } }}
                placeholder="e.g. wiki_read"
                validated={errors.scopes && scopes.length === 0 ? 'error' : 'default'}
              />
            </SplitItem>
            <SplitItem>
              <Button variant="secondary" icon={<PlusCircleIcon />} onClick={addScope}>
                Add
              </Button>
            </SplitItem>
          </Split>
          {scopes.length > 0 && (
            <LabelGroup style={{ marginTop: '0.5rem' }}>
              {scopes.map((s) => (
                <Label
                  key={s}
                  isCompact
                  variant="outline"
                  onClose={() => removeScope(s)}
                >
                  {s}
                </Label>
              ))}
            </LabelGroup>
          )}
        </FormGroup>

        {/* Validation policy */}
        <Card style={{ marginTop: '0.5rem' }}>
          <CardTitle>Validation policy</CardTitle>
          <CardBody>
            <FormGroup label="Type" fieldId="validationType">
              <FormSelect
                id="validationType"
                value={validationType}
                onChange={(_e, v) => setValidationType(v as 'on_demand' | 'scheduled')}
              >
                {VALIDATION_TYPES.map((t) => (
                  <FormSelectOption key={t.value} value={t.value} label={t.label} />
                ))}
              </FormSelect>
            </FormGroup>

            {validationType === 'on_demand' && (
              <Grid hasGutter style={{ marginTop: '1rem' }}>
                <GridItem span={6}>
                  <FormGroup
                    label="Maximum uses"
                    fieldId="maxUses"
                  >
                    <NumberInput
                      id="maxUses"
                      value={maxUses}
                      min={1}
                      max={1000}
                      onMinus={() => setMaxUses(Math.max(1, maxUses - 1))}
                      onPlus={() => setMaxUses(maxUses + 1)}
                      onChange={(e) => setMaxUses(Number((e.target as HTMLInputElement).value))}
                    />
                  </FormGroup>
                </GridItem>
                <GridItem span={6}>
                  <FormGroup
                    label="Valid until"
                    isRequired
                    fieldId="validUntil"
                  >
                    <TextInput
                      id="validUntil"
                      type="date"
                      value={validUntil || defaultValidUntil()}
                      onChange={(_e, v) => setValidUntil(v)}
                      validated={errors.validUntil ? 'error' : 'default'}
                    />
                  </FormGroup>
                </GridItem>
              </Grid>
            )}

            {validationType === 'scheduled' && (
              <Grid hasGutter style={{ marginTop: '1rem' }}>
                <GridItem span={6}>
                  <FormGroup
                    label="Cron schedule"
                    isRequired
                    fieldId="schedule"
                  >
                    <TextInput
                      id="schedule"
                      value={schedule}
                      onChange={(_e, v) => setSchedule(v)}
                      placeholder="0 9 * * *"
                      validated={errors.schedule ? 'error' : 'default'}
                    />
                  </FormGroup>
                </GridItem>
                <GridItem span={6}>
                  <FormGroup
                    label="Duration (days)"
                    fieldId="durationDays"
                  >
                    <NumberInput
                      id="durationDays"
                      value={durationDays}
                      min={1}
                      max={365}
                      onMinus={() => setDurationDays(Math.max(1, durationDays - 1))}
                      onPlus={() => setDurationDays(durationDays + 1)}
                      onChange={(e) => setDurationDays(Number((e.target as HTMLInputElement).value))}
                    />
                  </FormGroup>
                </GridItem>
              </Grid>
            )}
          </CardBody>
        </Card>

        {/* Labels (optional) */}
        <FormGroup
          label="Labels"
          fieldId="labels"
        >
          <Split hasGutter>
            <SplitItem>
              <TextInput
                id="labelKey"
                value={labelKey}
                onChange={(_e, v) => setLabelKey(v)}
                placeholder="key"
                style={{ width: '160px' }}
              />
            </SplitItem>
            <SplitItem>
              <TextInput
                id="labelValue"
                value={labelValue}
                onChange={(_e, v) => setLabelValue(v)}
                placeholder="value"
                style={{ width: '160px' }}
              />
            </SplitItem>
            <SplitItem>
              <Button variant="secondary" icon={<PlusCircleIcon />} onClick={addLabel}>
                Add
              </Button>
            </SplitItem>
          </Split>
          {Object.keys(labels).length > 0 && (
            <LabelGroup style={{ marginTop: '0.5rem' }}>
              {Object.entries(labels).map(([k, v]) => (
                <Label
                  key={k}
                  isCompact
                  color="blue"
                  onClose={() => removeLabel(k)}
                >
                  {k}={v}
                </Label>
              ))}
            </LabelGroup>
          )}
        </FormGroup>

        <ActionGroup>
          <Button
            variant="primary"
            isLoading={createMutation.isPending}
            isDisabled={createMutation.isPending}
            onClick={handleSubmit}
          >
            Request mission
          </Button>
          <Button variant="link" onClick={() => navigate('/missions')}>
            Cancel
          </Button>
        </ActionGroup>
      </Form>
    </PageSection>
  );
};
