import React, { useCallback, useState, useEffect, useContext, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DataTable,
  Table,
  TableHead,
  TableRow,
  TableHeader,
  TableBody,
  TableCell,
  TableContainer,
  Loading,
  InlineNotification,
  InlineLoading,
  Tag,
  Pagination
} from '@carbon/react';
import './MyApplications.css';
import { authFetch } from '../../services/api';
import { buildApiUrl } from '../../services/apiBaseUrl';
import PanelContext from '../../contexts/PanelContext';
import LogViewer from '../LogViewer/LogViewer';
import CapabilityNotice from '../CapabilityNotice/CapabilityNotice';
import { formatDateTime, formatUsd } from '../../i18n/format';

const normalizeStatus = (status) => status?.trim().toLowerCase() || '';

// A helper function to render status tags with colors
const renderStatusTag = (status, t) => {
  const normalizedStatus = normalizeStatus(status);
  const displayStatus = {
    approved: t('statuses.approved'),
    passed: t('statuses.passed'),
    pending: t('statuses.pending'),
    processing: t('statuses.processing'),
    retrying: t('statuses.retrying'),
    rejected: t('statuses.rejected'),
    'processing failed': t('statuses.processingFailed'),
  }[normalizedStatus] || status?.trim() || '';

  switch (normalizedStatus) {
    case 'approved':
    case 'passed':
      return <Tag type="green">{displayStatus}</Tag>;
    case 'pending':
    case 'processing':
      return <Tag type="blue">{displayStatus}</Tag>;
    case 'retrying':
      return <Tag type="purple">{displayStatus}</Tag>;
    case 'rejected':
    case 'processing failed':
      return <Tag type="red">{displayStatus}</Tag>;
    default:
      return <Tag type="gray">{displayStatus}</Tag>;
  }
};

const MyApplications = () => {
  const { t, i18n } = useTranslation('applications');
  const fetchInFlightRef = useRef(new Map());
  const mountedRef = useRef(false);
  const [query, setQuery] = useState({ page: 1, sortBy: 'submitted_date', direction: 'desc' });
  const [metadata, setMetadata] = useState({ total: 0, active: false, page: 1, sortBy: 'submitted_date', direction: 'desc' });
  const [revision, setRevision] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const queryKey = new URLSearchParams({page: query.page, page_size: 50,
    sort_by: query.sortBy, sort_direction: query.direction}).toString();
  const requestKey = `${queryKey}:${revision}`;
  const currentQueryRef = useRef(requestKey);
  currentQueryRef.current = requestKey;
  const [applications, setApplications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const { setIsPanelOpen, setPanelContent } = useContext(PanelContext);
  const headers = [
    { key: 'app_id_str', header: t('headers.applicationId') },
    { key: 'applicant_name', header: t('headers.applicantName') },
    { key: 'loan_type', header: t('headers.loanType') },
    { key: 'amount', header: t('headers.amount') },
    { key: 'status', header: t('headers.status') },
    { key: 'validation_comments', header: t('headers.details') },
    { key: 'submitted_date', header: t('headers.submittedDate') },
  ];

  const fetchApplications = useCallback(() => {
    if (fetchInFlightRef.current.has(requestKey)) {
      return fetchInFlightRef.current.get(requestKey);
    }
    const isCurrent = () => mountedRef.current && currentQueryRef.current === requestKey;
    setIsRefreshing(true);
    const request = (async () => {
      try {
        const response = await authFetch(buildApiUrl(`/applications?${queryKey}`));
        if (!response.ok) throw new Error('errors.fetch');
        const data = await response.json();
        if (!isCurrent()) return;
        setApplications(data.items.map(app => ({ ...app, id: app.app_id_str })));
        const requested = new URLSearchParams(queryKey);
        setMetadata({ total: data.total, active: data.has_active_applications, page: data.page,
          sortBy: requested.get('sort_by'), direction: requested.get('sort_direction') });
        setQuery(current => current.page === data.page ? current : {...current, page: data.page});
        setError(null);
      } catch {
        if (isCurrent()) setError('errors.fetch');
      } finally {
        if (isCurrent()) { setIsLoading(false); setIsRefreshing(false); }
      }
    })();
    fetchInFlightRef.current.set(requestKey, request);
    request.finally(() => {
      if (fetchInFlightRef.current.get(requestKey) === request) {
        fetchInFlightRef.current.delete(requestKey);
      }
    });
    return request;
  }, [queryKey, requestKey]);

  const handleApplicationChange = useCallback(() => {
    // Every request started before a detail update must become obsolete.
    if (mountedRef.current) setRevision(value => value + 1);
  }, []);
  const changeSort = (field) => setQuery(current => ({page: 1, sortBy: field,
    direction: current.sortBy === field && current.direction === 'asc' ? 'desc' : 'asc'}));

  const handleRowClick = (rowId) => {
      const application = applications.find(app => app.app_id_str === rowId);
      if (application) {
          setPanelContent(
            <LogViewer
              application={application}
              onApplicationChange={handleApplicationChange}
            />
          );
          setIsPanelOpen(true);
      }
  };

  useEffect(() => {
    mountedRef.current = true;
    fetchApplications();
    return () => { mountedRef.current = false; };
  }, [fetchApplications]);

  useEffect(() => {
    if (!metadata.active) {
      return undefined;
    }

    let cancelled = false;
    let pollingTimer;

    const scheduleNextPoll = () => {
      pollingTimer = window.setTimeout(async () => {
        await fetchApplications();
        if (!cancelled) {
          scheduleNextPoll();
        }
      }, 5000);
    };

    scheduleNextPoll();
    return () => {
      cancelled = true;
      window.clearTimeout(pollingTimer);
    };
  }, [metadata.active, fetchApplications]);

  return (
    <div className="applications-container" aria-busy={isRefreshing}>
      <h1 className="applications-header">{t('page.heading')}</h1>
      <CapabilityNotice capabilityIds={['view_applications']} />
      <p>{t('page.intro')}</p>
      <p className="applications-subtitle">{t('page.subtitle')}</p>
      <p className="applications-scroll-hint">{t('page.scrollHint')}</p>
      {isRefreshing && !isLoading && <InlineLoading description={t('updating')} />}
      {isLoading ? (
        <div className="loading-container">
          <Loading description={t('loading')} withOverlay={false} />
        </div>
      ) : error ? (
        <InlineNotification
          kind="error"
          title={t('errors.title')}
          subtitle={error === 'errors.fetch' ? t(error) : error || t('errors.fallback')}
        />
      ) : applications.length === 0 ? (
        <div className="applications-empty-state">
          <h2>{t('empty.heading')}</h2>
          <p>{t('empty.description')}</p>
        </div>
      ) : <DataTable rows={applications} headers={headers}>
        {({ rows, headers, getTableProps, getRowProps }) => (
          <TableContainer>
            <Table {...getTableProps()}>
              <TableHead>
                <TableRow>
                  {headers.map((header) => (
                    <TableHeader key={header.key} isSortable
                      isSortHeader={metadata.sortBy === header.key}
                      sortDirection={metadata.sortBy === header.key ? metadata.direction.toUpperCase() : 'NONE'}
                      onClick={() => changeSort(header.key)}
                      translateWithId={() => t('sorting.description', {
                        column: header.header,
                        direction: t(query.sortBy === header.key && query.direction === 'asc'
                          ? 'sorting.descending' : 'sorting.ascending'),
                      }) + (header.key === 'validation_comments' ? ` ${t('sorting.details')}` : '')}>
                      {header.header}
                    </TableHeader>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => {
                  // Destructure the key and the rest of the props for the row
                  const { key, ...rest } = getRowProps({ row });
                    return (
                    <TableRow key={key} {...rest}
                    className="clickable-row"
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        handleRowClick(row.id);
                      }
                    }}
                    onClick={() => handleRowClick(row.id)}>
                      {row.cells.map((cell) => (
                      <TableCell key={cell.id}>
                        {cell.info.header === 'status'
                        ? renderStatusTag(cell.value, t)
                        : cell.info.header === 'validation_comments'
                          ? <span className="validation-summary">{t('viewDetails')}</span>
                          : cell.info.header === 'app_id_str'
                            ?<span style={{color: 'blue', textDecoration: 'underline'}}>{cell.value}</span>
                            : cell.info.header === 'amount'
                              ? formatUsd(cell.value, i18n.resolvedLanguage)
                              : cell.info.header === 'submitted_date'
                                ? formatDateTime(cell.value, i18n.resolvedLanguage)
                                : cell.value}
                      </TableCell>
                      ))}
                    </TableRow>
                    );
                })}
              </TableBody>
            </Table>
            <Pagination ref={node => {
              // Carbon currently ignores pageNumberText for its page select.
              const select = node?.querySelector('select[id$="-right"]');
              if (select) select.setAttribute('aria-label', t('pagination.pageNumber'));
            }} page={query.page} pageSize={50} pageSizes={[50]}
              pageSizeInputDisabled totalItems={metadata.total}
              onChange={({page}) => setQuery(current => ({...current, page}))}
              backwardText={t('pagination.previous')} forwardText={t('pagination.next')}
              itemsPerPageText={t('pagination.perPage')} pageNumberText={t('pagination.pageNumber')}
              itemRangeText={() => t('pagination.range', {
                min: Math.min((metadata.page - 1) * 50 + 1, metadata.total),
                max: Math.min(metadata.page * 50, metadata.total), total: metadata.total})}
              pageRangeText={(_page, total) => t('pagination.pages', {total})}
              pageText={page => t('pagination.page', {page})} />
          </TableContainer>
        )}
      </DataTable>}
    </div>
  );
};

export default MyApplications;
