import React, { useMemo, useState } from 'react';
import { Button } from '@carbon/react';
import { useTranslation } from 'react-i18next';
import {
  JsonView,
  allExpanded,
  collapseAllNested,
  defaultStyles,
} from 'react-json-view-lite';
import 'react-json-view-lite/dist/index.css';

const MAX_NESTED_JSON_DEPTH = 8;

const stripJsonFence = (value) => {
  const match = value.match(/^```(?:json)?\s*([\s\S]*?)```$/i);
  return (match?.[1] || value).trim();
};

const normalizeNestedJson = (value, depth = 0) => {
  if (depth >= MAX_NESTED_JSON_DEPTH || value === null) return value;

  if (Array.isArray(value)) {
    return value.map((item) => normalizeNestedJson(item, depth + 1));
  }

  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        normalizeNestedJson(item, depth + 1),
      ])
    );
  }

  if (typeof value !== 'string') return value;

  const candidate = stripJsonFence(value);
  if (!candidate) return value;

  try {
    const parsed = JSON.parse(candidate);
    return normalizeNestedJson(parsed, depth + 1);
  } catch {
    return value;
  }
};

const isStructuredValue = (value) => (
  value !== null && (Array.isArray(value) || typeof value === 'object')
);

const StructuredLogData = ({ data }) => {
  const { t } = useTranslation('logs');
  const normalized = useMemo(() => normalizeNestedJson(data), [data]);
  const [shouldExpandNode, setShouldExpandNode] = useState(() => collapseAllNested);

  if (!isStructuredValue(normalized)) {
    return <pre className="technical-plain-text">{String(normalized ?? '')}</pre>;
  }

  const copyJson = async () => {
    await navigator.clipboard?.writeText(JSON.stringify(normalized, null, 2));
  };

  return (
    <div className="structured-log-data">
      <div className="structured-log-actions" aria-label={t('json.controls')}>
        <Button kind="ghost" size="sm" onClick={() => setShouldExpandNode(() => allExpanded)}>
          {t('json.expand')}
        </Button>
        <Button kind="ghost" size="sm" onClick={() => setShouldExpandNode(() => collapseAllNested)}>
          {t('json.collapse')}
        </Button>
        <Button kind="ghost" size="sm" onClick={copyJson}>
          {t('json.copy')}
        </Button>
      </div>
      <div
        className="structured-log-tree"
      >
        <JsonView
          data={normalized}
          style={defaultStyles}
          shouldExpandNode={shouldExpandNode}
          clickToExpandNode
          aria-label={t('json.treeLabel')}
        />
      </div>
    </div>
  );
};

export default StructuredLogData;
