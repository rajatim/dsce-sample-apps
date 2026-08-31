// src/pages/LoginPage.js
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
import {
    Form,
    TextInput,
    PasswordInput,
    Button,
    InlineLoading,
    InlineNotification,
} from '@carbon/react';

const DEMO_USERNAME = 'tom_miller';
const DEMO_PASSWORD = 'Pass1234';

export const LoginPage = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const { login } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const demoMode = searchParams.get('demo') === '1';
    const [isAutoLogin, setIsAutoLogin] = useState(demoMode);
    const demoLoginStarted = useRef(false);
    const apiUrl = import.meta.env.VITE_API_URL;

    const authenticate = useCallback(async (loginUsername, loginPassword, automatic = false) => {
        setError('');

        const formData = new URLSearchParams();
        formData.append('username', loginUsername);
        formData.append('password', loginPassword);

        try {
            const response = await fetch(`${apiUrl}/token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData,
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Failed to login');
            }
            
            const data = await response.json();
            login(data.access_token);
            navigate('/apply');
        } catch (err) {
            setError(automatic ? `Automatic demo login failed: ${err.message}` : err.message);
            setIsAutoLogin(false);
        }
    }, [apiUrl, login, navigate]);

    useEffect(() => {
        if (!demoMode || demoLoginStarted.current) return;

        demoLoginStarted.current = true;
        authenticate(DEMO_USERNAME, DEMO_PASSWORD, true);
    }, [authenticate, demoMode]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        await authenticate(username, password);
    };

    const downloadUrl = `${apiUrl}/download_sample_documents`;

    if (isAutoLogin && !error) {
        return (
            <div style={{ maxWidth: '600px', margin: '4rem auto' }}>
                <h2>Preparing the loan demo</h2>
                <InlineLoading description="Entering demo..." />
            </div>
        );
    }

    // ... return a form JSX similar to your other components
    return (
        <div style={{ maxWidth: '600px', margin: '4rem auto' }}>
            <h4>Sample Username, Password and Documents for Testing -</h4>
            <h5>Username: <b>tom_miller</b></h5>
            <h5>Password: <b>Pass1234</b></h5>
            <br></br>
            <h5><a href={downloadUrl} download="sample.zip" className="text-blue-600 underline hover:text-blue-800">Click here</a> to download the sample documents for submitting loan application. 
            </h5>
            <br/><br/>
            <h2>Login</h2>
            <Form onSubmit={handleSubmit}>
                <TextInput id="username" labelText="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
                <PasswordInput id="password" labelText="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
                {error && <InlineNotification kind="error" title="Login Error" subtitle={error} />}
                <Button type="submit" style={{ marginTop: '1rem' }}>Login</Button>
                <p style={{ marginTop: '1rem' }}>Don't have an account? <Link to="/register">Register here</Link></p>
            </Form>
        </div>
    );
};
