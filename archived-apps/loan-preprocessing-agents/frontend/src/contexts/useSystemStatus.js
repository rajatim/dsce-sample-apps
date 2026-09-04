import { createContext, useContext } from 'react';

export const SystemStatusContext = createContext(null);

export const useSystemStatus = () => useContext(SystemStatusContext);
