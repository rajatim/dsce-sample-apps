import { useEffect, useState } from 'react';
import { Routes, Route, Link, Navigate } from 'react-router-dom';
import {
  Header,
  HeaderMenuButton,
  HeaderMenuItem,
  HeaderName,
  HeaderNavigation,
  SideNav,
  SideNavItems,
  SideNavLink,
} from '@carbon/react';
import SidePanel from "./components/SidePanel/SidePanel";
import PanelContext from './contexts/PanelContext';

// Your existing page components
import LoanApplication from './components/LoanApplication/LoanApplication';
import MyApplications from './components/MyApplications/MyApplications';
import LoanCalculator from './components/LoanCalculator/LoanCalculator';
import SystemStatus from './components/SystemStatus/SystemStatus';
import { SystemStatusProvider } from './contexts/SystemStatusContext';

import './App.css';

function App() {
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [panelContent, setPanelContent] = useState(null);
  const [isMobileNavExpanded, setIsMobileNavExpanded] = useState(false);
  const closeMobileNavigation = () => setIsMobileNavExpanded(false);

  useEffect(() => {
    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        setIsMobileNavExpanded(false);
      }
    };

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, []);

  return (
    <PanelContext.Provider value={{ setIsPanelOpen, setPanelContent }}>
    <SystemStatusProvider>
      <div className="app-wrapper">
      <Header aria-label="Loan Application Platform">
        <HeaderMenuButton
          aria-label={isMobileNavExpanded ? 'Close navigation menu' : 'Open navigation menu'}
          aria-controls="mobile-navigation"
          aria-expanded={isMobileNavExpanded}
          isActive={isMobileNavExpanded}
          onClick={() => setIsMobileNavExpanded((isExpanded) => !isExpanded)}
        />
        <HeaderName as={Link} to="/apply" prefix="Financial">
          LoanHub
        </HeaderName>
        <HeaderNavigation aria-label="Main Navigation">
          <HeaderMenuItem as={Link} to="/apply">Apply</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/my-applications">My Applications</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/calculator">Loan Calculator</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/status">Demo status</HeaderMenuItem>
        </HeaderNavigation>
        <SideNav
          id="mobile-navigation"
          aria-label="Mobile navigation"
          expanded={isMobileNavExpanded}
          isPersistent={false}
          onOverlayClick={closeMobileNavigation}
          onSideNavBlur={closeMobileNavigation}
        >
          <SideNavItems>
            <SideNavLink as={Link} to="/apply" onClick={closeMobileNavigation}>
              Apply
            </SideNavLink>
            <SideNavLink as={Link} to="/my-applications" onClick={closeMobileNavigation}>
              My Applications
            </SideNavLink>
            <SideNavLink as={Link} to="/calculator" onClick={closeMobileNavigation}>
              Loan Calculator
            </SideNavLink>
            <SideNavLink as={Link} to="/status" onClick={closeMobileNavigation}>
              Demo status
            </SideNavLink>
          </SideNavItems>
        </SideNav>
      </Header>

      <main className="page-content">
        <Routes>
          <Route path="/apply" element={<LoanApplication />} />
          <Route path="/my-applications" element={<MyApplications />} />
          <Route path="/calculator" element={<LoanCalculator />} />
          <Route path="/status" element={<SystemStatus />} />
          <Route path="/" element={<Navigate to="/apply" replace />} />
          <Route path="*" element={<Navigate to="/apply" replace />} />
        </Routes>
      </main>
      <SidePanel isOpen={isPanelOpen} onClose={() => setIsPanelOpen(false)}>
        {panelContent}
      </SidePanel>
      </div>
    </SystemStatusProvider>
    </PanelContext.Provider>
  );
}

export default App;
