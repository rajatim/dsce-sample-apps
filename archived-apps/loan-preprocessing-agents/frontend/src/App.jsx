import { useEffect, useState } from 'react';
import { Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft } from '@carbon/icons-react';
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
import LanguageSwitcher from './components/LanguageSwitcher/LanguageSwitcher';
import { resolveDsceReturnUrl } from './services/dsceReturn';

import './App.css';

function App() {
  const { t, i18n } = useTranslation('common');
  const location = useLocation();
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [panelContent, setPanelContent] = useState(null);
  const [isMobileNavExpanded, setIsMobileNavExpanded] = useState(false);
  const [dsceReturnUrl] = useState(() =>
    resolveDsceReturnUrl({
      search: location.search,
      locale: i18n.resolvedLanguage,
    })
  );
  const closeMobileNavigation = () => setIsMobileNavExpanded(false);

  const returnToDsce = (event) => {
    if (!window.opener || window.opener.closed) return;
    event.preventDefault();
    window.opener.focus();
    window.close();
  };

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
      <Header aria-label={t('app.ariaLabel')}>
        <HeaderMenuButton
          aria-label={isMobileNavExpanded ? t('menu.close') : t('menu.open')}
          aria-controls="mobile-navigation"
          aria-expanded={isMobileNavExpanded}
          isActive={isMobileNavExpanded}
          onClick={() => setIsMobileNavExpanded((isExpanded) => !isExpanded)}
        />
        <HeaderName as={Link} to="/apply" prefix={t('brand.platformLabel')}>
          LoanHub
        </HeaderName>
        <HeaderNavigation aria-label={t('navigation.main')}>
          <HeaderMenuItem as={Link} to="/apply">{t('navigation.apply')}</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/my-applications">{t('navigation.applications')}</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/calculator">{t('navigation.calculator')}</HeaderMenuItem>
          <HeaderMenuItem as={Link} to="/status">{t('navigation.status')}</HeaderMenuItem>
        </HeaderNavigation>
        {dsceReturnUrl && (
          <a
            className="dsce-return-link dsce-return-link--desktop"
            href={dsceReturnUrl}
            onClick={returnToDsce}
          >
            <ArrowLeft aria-hidden="true" />
            <span>{t('navigation.backToDsce')}</span>
          </a>
        )}
        <div className="desktop-language-switcher">
          <LanguageSwitcher id="desktop-language" />
        </div>
        <SideNav
          id="mobile-navigation"
          aria-label={t('navigation.mobile')}
          expanded={isMobileNavExpanded}
          isPersistent={false}
          onOverlayClick={closeMobileNavigation}
          onSideNavBlur={closeMobileNavigation}
        >
          <SideNavItems>
            {dsceReturnUrl && (
              <li className="mobile-dsce-return">
                <a href={dsceReturnUrl} onClick={returnToDsce}>
                  <ArrowLeft aria-hidden="true" />
                  <span>{t('navigation.backToDsce')}</span>
                </a>
              </li>
            )}
            {isMobileNavExpanded && (
              <li className="mobile-language-switcher">
                <LanguageSwitcher id="mobile-language" />
              </li>
            )}
            <SideNavLink as={Link} to="/apply" onClick={closeMobileNavigation}>
              {t('navigation.apply')}
            </SideNavLink>
            <SideNavLink as={Link} to="/my-applications" onClick={closeMobileNavigation}>
              {t('navigation.applications')}
            </SideNavLink>
            <SideNavLink as={Link} to="/calculator" onClick={closeMobileNavigation}>
              {t('navigation.calculator')}
            </SideNavLink>
            <SideNavLink as={Link} to="/status" onClick={closeMobileNavigation}>
              {t('navigation.status')}
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
