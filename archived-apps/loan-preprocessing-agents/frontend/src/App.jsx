import { useState } from 'react';
import { Routes, Route, Link, Navigate } from 'react-router-dom';
import { Header, HeaderName, HeaderNavigation, HeaderMenuItem } from '@carbon/react';
import SidePanel from "./components/SidePanel/SidePanel";
import PanelContext from './contexts/PanelContext';

// Your existing page components
import LoanApplication from './components/LoanApplication/LoanApplication';
import MyApplications from './components/MyApplications/MyApplications';
import LoanCalculator from './components/LoanCalculator/LoanCalculator';

import './App.css';

function App() {
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [panelContent, setPanelContent] = useState(null);

  return (
    <PanelContext.Provider value={{ setIsPanelOpen, setPanelContent }}>
    <div className="app-wrapper">
      <Header aria-label="Loan Application Platform">
        <HeaderName as={Link} to="/apply" prefix="Financial">
          LoanHub
        </HeaderName>
        <HeaderNavigation aria-label="Main Navigation">
          <HeaderMenuItem as={Link} to="/apply">Apply</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/my-applications">My Applications</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/calculator">Loan Calculator</HeaderMenuItem>
        </HeaderNavigation>
      </Header>

      <main className="page-content">
        <Routes>
          <Route path="/apply" element={<LoanApplication />} />
          <Route path="/my-applications" element={<MyApplications />} />
          <Route path="/calculator" element={<LoanCalculator />} />
          <Route path="/" element={<Navigate to="/apply" replace />} />
          <Route path="*" element={<Navigate to="/apply" replace />} />
        </Routes>
      </main>
      <SidePanel isOpen={isPanelOpen} onClose={() => setIsPanelOpen(false)}>
        {panelContent}
      </SidePanel>
    </div>
    </PanelContext.Provider>
  );
}

export default App;
