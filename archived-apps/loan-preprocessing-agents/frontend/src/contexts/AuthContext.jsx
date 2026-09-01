import { useCallback, useEffect, useState } from 'react';
import AuthContext from './auth-context';
import { requestDemoToken } from '../services/demoAuth';
import './AuthContext.css';

export const AuthProvider = ({ children }) => {
    const [token, setToken] = useState(localStorage.getItem('token'));
    const [error, setError] = useState('');
    const [loginAttempt, setLoginAttempt] = useState(0);
    
    useEffect(() => {
        // This effect syncs the token between localStorage and state.
        const handleStorageChange = () => {
            setToken(localStorage.getItem('token'));
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
                            <h1>Demo service unavailable</h1>
                            <p>{error}</p>
                            <button type="button" onClick={() => setLoginAttempt((attempt) => attempt + 1)}>
                                Try again
                            </button>
                        </>
                    ) : (
                        <>
                            <h1>Preparing the loan demo</h1>
                            <p>Setting up the sample workspace. This usually takes only a moment.</p>
                            <div className="demo-access-progress" aria-label="Preparing demo" />
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
