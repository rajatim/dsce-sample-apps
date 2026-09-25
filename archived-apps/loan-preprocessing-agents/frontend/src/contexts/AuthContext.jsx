import { useCallback, useEffect, useState } from 'react';
import AuthContext from './auth-context';
import { requestDemoToken } from '../services/demoAuth';
import { useTranslation } from 'react-i18next';
import './AuthContext.css';

const FRONTEND_ERROR_KEYS = {
    'The demo service could not be reached.': 'auth.errors.unreachable',
    'The demo service did not return an access token.': 'auth.errors.missingToken',
};

export const AuthProvider = ({ children }) => {
    const { t } = useTranslation('common');
    // A stored POC token may have expired; prepare a fresh session before children mount.
    const [token, setToken] = useState(null);
    const [error, setError] = useState('');
    const [loginAttempt, setLoginAttempt] = useState(0);
    
    useEffect(() => {
        // A removal invalidates this session; a new stored token is not yet trusted.
        const handleStorageChange = () => {
            if (!localStorage.getItem('token')) setToken(null);
        };

        window.addEventListener('storage', handleStorageChange);
        return () => {
            window.removeEventListener('storage', handleStorageChange);
        };
    }, []);

    const login = useCallback((newToken) => {
        localStorage.setItem('token', newToken);
        setToken(newToken);
    }, []);

    const logout = useCallback(() => {
        localStorage.removeItem('token');
        setToken(null);
    }, []);

    useEffect(() => {
        if (token) return undefined;

        let active = true;
        setError('');
        requestDemoToken()
            .then((newToken) => {
                if (active) login(newToken);
            })
            .catch((loginError) => {
                if (active) setError(loginError.message);
            });

        return () => {
            active = false;
        };
    }, [login, loginAttempt, token]);
    
    const authContextValue = {
        token,
        login,
        logout,
    };

    if (!token) {
        return (
            <main className="demo-access-state">
                <section className="demo-access-card" aria-live="polite">
                    {error ? (
                        <>
                            <h1>{t('auth.unavailable')}</h1>
                            <p>{FRONTEND_ERROR_KEYS[error] ? t(FRONTEND_ERROR_KEYS[error]) : error}</p>
                            <button type="button" onClick={() => setLoginAttempt((attempt) => attempt + 1)}>
                                {t('auth.tryAgain')}
                            </button>
                        </>
                    ) : (
                        <>
                            <h1>{t('auth.preparing')}</h1>
                            <p>{t('auth.preparingDescription')}</p>
                            <div className="demo-access-progress" aria-label={t('auth.preparingLabel')} />
                        </>
                    )}
                </section>
            </main>
        );
    }

    return (
        <AuthContext.Provider value={authContextValue}>
            {children}
        </AuthContext.Provider>
    );
};
