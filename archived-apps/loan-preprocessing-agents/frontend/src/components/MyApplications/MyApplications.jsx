import React, { useCallback, useState, useEffect, useContext, useRef } from 'react';
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
import PanelContext from '../../contexts/PanelContext';
import LogViewer from '../LogViewer/LogViewer';

// Define the headers for our table
const headers = [
  { key: 'app_id_str', header: 'Application ID' },
  { key: 'applicant_name', header: 'Applicant Name' },
  { key: 'loan_type', header: 'Loan Type' },
  { key: 'amount', header: 'Amount' },
  { key: 'status', header: 'Status' },
  { key: 'validation_comments', header: 'Details' },
  { key: 'submitted_date', header: 'Submitted Date' },
];

const ACTIVE_STATUSES = new Set(['pending', 'processing', 'retrying']);

const normalizeStatus = (status) => status?.trim().toLowerCase() || '';

const hasActiveApplications = (applications) =>
  applications.some((application) => ACTIVE_STATUSES.has(normalizeStatus(application.status)));

// A helper function to render status tags with colors
const renderStatusTag = (status) => {
  const normalizedStatus = normalizeStatus(status);
  const displayStatus = {
    approved: 'Approved',
    passed: 'Passed',
    pending: 'Pending',
    processing: 'Processing',
    retrying: 'Retrying',
    rejected: 'Rejected',
    'processing failed': 'Processing Failed',
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
  const fetchInFlightRef = useRef(null);
  const [applications, setApplications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const { setIsPanelOpen, setPanelContent } = useContext(PanelContext);

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
        const apiUrl = import.meta.env.VITE_API_URL;
        const response = await authFetch(`${apiUrl}/list_applications`);
        if (!response.ok) {
          throw new Error('Failed to fetch applications.');
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

  if (isLoading) {
    return (
      <div className="loading-container">
        <Loading description="Loading applications..." withOverlay={false} />
      </div>
    );
  }

  if (error) {
    return (
      <InlineNotification
        kind="error"
        title="Failed to load applications"
        subtitle={error || 'Please try again later.'}
      />
    );
  }

  return (
    <div className="applications-container">
      <h1 className="applications-header">My Applications</h1>
      <p>Here is a list of your submitted loan applications.</p>
      <p className="applications-subtitle">You can hover on a row and click to see the detailed steps followed by agents.</p>
      
      <DataTable rows={applications} headers={headers}>
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
                        ? renderStatusTag(cell.value)
                        : cell.info.header === 'validation_comments'
                          ? <span className="validation-summary">View processing details</span>
                          : cell.info.header === 'app_id_str'
                            ?<span style={{color: 'blue', textDecoration: 'underline'}}>{cell.value}</span>
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
      </DataTable>
    </div>
  );
};

export default MyApplications;
