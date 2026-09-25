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
  Tag
} from '@carbon/react';
import './MyApplications.css';
import { authFetch } from '../../services/api';
import { buildApiUrl } from '../../services/apiBaseUrl';
import PanelContext from '../../contexts/PanelContext';
import LogViewer from '../LogViewer/LogViewer';
import CapabilityNotice from '../CapabilityNotice/CapabilityNotice';
import { formatDateTime, formatUsd } from '../../i18n/format';

const ACTIVE_STATUSES = new Set(['pending', 'processing', 'retrying']);

const normalizeStatus = (status) => status?.trim().toLowerCase() || '';

const hasActiveApplications = (applications) =>
  applications.some((application) => ACTIVE_STATUSES.has(normalizeStatus(application.status)));

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
  const fetchInFlightRef = useRef(null);
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

  const handleApplicationChange = useCallback((updatedApplication) => {
    setApplications((currentApplications) => currentApplications.map((application) => (
      application.app_id_str === updatedApplication.app_id_str
        ? { ...updatedApplication, id: updatedApplication.app_id_str }
        : application
    )));
  }, []);

  const fetchApplications = useCallback(() => {
    if (fetchInFlightRef.current) {
      return fetchInFlightRef.current;
    }
    const request = (async () => {
      try {
        const response = await authFetch(buildApiUrl('/list_applications'));
        if (!response.ok) {
          throw new Error('errors.fetch');
        }
        const data = await response.json();
        setApplications(data.map(app => ({
          ...app,
          id: app.app_id_str,
        })));
        setError(null);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    })();
    fetchInFlightRef.current = request;
    request.finally(() => {
      if (fetchInFlightRef.current === request) {
        fetchInFlightRef.current = null;
      }
    });
    return request;
  }, []);

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
    fetchApplications();
  }, [fetchApplications]);

  useEffect(() => {
    if (!hasActiveApplications(applications)) {
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
  }, [applications, fetchApplications]);

  return (
    <div className="applications-container">
      <h1 className="applications-header">{t('page.heading')}</h1>
      <CapabilityNotice capabilityIds={['view_applications']} />
      <p>{t('page.intro')}</p>
      <p className="applications-subtitle">{t('page.subtitle')}</p>
      <p className="applications-scroll-hint">{t('page.scrollHint')}</p>
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
        {({ rows, headers, getTableProps, getHeaderProps, getRowProps }) => (
          <TableContainer>
            <Table {...getTableProps()}>
              <TableHead>
                <TableRow>
                  {headers.map((header) => {
                    // Destructure the key and the rest of the props
                    const { key, ...rest } = getHeaderProps({ header });
                    return (
                      // Apply the key directly, and spread the rest
                      <TableHeader key={key} {...rest}>
                        {header.header}
                      </TableHeader>
                    );
                  })}
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
          </TableContainer>
        )}
      </DataTable>}
    </div>
  );
};

export default MyApplications;
