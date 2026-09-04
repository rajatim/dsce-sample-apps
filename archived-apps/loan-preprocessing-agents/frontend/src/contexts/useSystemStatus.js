import { createContext, useContext } from 'react';

export const SystemStatusContext = createContext(null);

export const useSystemStatus = () => {
  const context = useContext(SystemStatusContext);
  if (!context) throw new Error('useSystemStatus must be used within SystemStatusProvider');
  return context;
};
