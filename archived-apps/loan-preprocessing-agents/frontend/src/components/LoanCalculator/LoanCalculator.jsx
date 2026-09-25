import React, { useState } from 'react';
import {
  Form,
  NumberInput,
  Button,
  InlineNotification,
  Tile
} from '@carbon/react';
import { Calculator } from '@carbon/react/icons';
import { useTranslation } from 'react-i18next';
import { formatUsd } from '../../i18n/format';
import './LoanCalculator.css';

const LoanCalculator = () => {
  const { t, i18n } = useTranslation('calculator');
  const [loanAmount, setLoanAmount] = useState(100000);
  const [interestRate, setInterestRate] = useState(5);
  const [loanTerm, setLoanTerm] = useState(30);
  const [error, setError] = useState('');

  const [results, setResults] = useState({
    monthlyPayment: null,
    totalInterest: null,
    totalPayment: null,
  });

  const handleCalculate = (e) => {
    e.preventDefault();
    setError('');
    
    // Basic Validation
    if (!loanAmount || !interestRate || !loanTerm || loanAmount <= 0 || interestRate <= 0 || loanTerm <= 0) {
      setError('errors.positiveValues');
      setResults({ monthlyPayment: null, totalInterest: null, totalPayment: null });
      return;
    }

    // Calculation Logic
    const principal = parseFloat(loanAmount);
    const annualRate = parseFloat(interestRate) / 100;
    const monthlyRate = annualRate / 12;
    const numberOfPayments = parseFloat(loanTerm) * 12;

    let monthlyPayment;
    if (monthlyRate === 0) { // Handle interest-free loans
      monthlyPayment = principal / numberOfPayments;
    } else {
      monthlyPayment =
        principal *
        (monthlyRate * Math.pow(1 + monthlyRate, numberOfPayments)) /
        (Math.pow(1 + monthlyRate, numberOfPayments) - 1);
    }
    
    const totalPayment = monthlyPayment * numberOfPayments;
    const totalInterest = totalPayment - principal;

    setResults({
      monthlyPayment: monthlyPayment.toFixed(2),
      totalInterest: totalInterest.toFixed(2),
      totalPayment: totalPayment.toFixed(2),
    });
  };

  return (
    <div className="calculator-container">
      <div className="calculator-header">
        <h1>{t('page.heading')}</h1>
        <p>{t('page.subtitle')}</p>
      </div>
      <div className="calculator-layout">
        <Form onSubmit={handleCalculate} className="calculator-form">
          <NumberInput
            id="loanAmount"
            label={t('fields.amount')}
            value={loanAmount}
            onChange={(e, { value }) => setLoanAmount(value)}
            min={1}
            step={1}
            invalidText={t('fields.invalidAmount')}
          />
          <NumberInput
            id="interestRate"
            label={t('fields.rate')}
            value={interestRate}
            onChange={(e, { value }) => setInterestRate(value)}
            min={0.1}
            step={0.1}
            invalidText={t('fields.invalidRate')}
          />
          <NumberInput
            id="loanTerm"
            label={t('fields.term')}
            value={loanTerm}
            onChange={(e, { value }) => setLoanTerm(value)}
            min={1}
            step={1}
            invalidText={t('fields.invalidTerm')}
          />

          {error && (
            <InlineNotification
              kind="error"
              title={t('errors.title')}
              subtitle={t(error)}
              hideCloseButton
            />
          )}

          <Button type="submit" renderIcon={Calculator}>
            {t('actions.calculate')}
          </Button>
        </Form>
        
        <Tile className="results-card">
          <h2>{t('results.heading')}</h2>
          {results.monthlyPayment !== null ? (
            <div className="results-content">
              <div className="result-item">
                <p className="result-label">{t('results.monthly')}</p>
                <p className="monthly-payment-value">
                  {formatUsd(parseFloat(results.monthlyPayment), i18n.resolvedLanguage)}
                </p>
              </div>
              <hr />
              <div className="result-item">
                <p className="result-label">{t('results.principal')}</p>
                <p className="result-value">
                  {formatUsd(parseFloat(loanAmount), i18n.resolvedLanguage)}
                </p>
              </div>
              <div className="result-item">
                <p className="result-label">{t('results.interest')}</p>
                <p className="result-value">
                  {formatUsd(parseFloat(results.totalInterest), i18n.resolvedLanguage)}
                </p>
              </div>
              <div className="result-item total-payment-item">
                <p className="result-label">{t('results.total')}</p>
                <p className="result-value">
                  {formatUsd(parseFloat(results.totalPayment), i18n.resolvedLanguage)}
                </p>
              </div>
            </div>
          ) : (
            <p className="no-results-text">
              {t('results.empty')}
            </p>
          )}
        </Tile>
      </div>
    </div>
  );
};

export default LoanCalculator;
