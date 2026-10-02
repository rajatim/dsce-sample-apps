import { useLocation } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import App from './App';

export default function LoanSession() {
  const { pathname } = useLocation();
  return <AuthProvider publicStatus={pathname === '/status' || pathname === '/status/'}><App /></AuthProvider>;
}
