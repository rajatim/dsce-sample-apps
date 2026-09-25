import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Button,
  TextInput,
  Select,
  SelectItem,
  NumberInput,
  DatePicker,
  DatePickerInput,
  Checkbox,
  RadioButton,
  RadioButtonGroup,
  ProgressIndicator,
  ProgressStep,
  FormGroup,
  Heading,
  Section,
  Modal,
  Loading,
  FileUploader,
  Tile,
  InlineNotification
} from '@carbon/react';
import { User, Settings, Help, DocumentPdf, Document } from '@carbon/react/icons';
import { authFetch } from '../../services/api';
import { buildApiUrl } from '../../services/apiBaseUrl';
import CapabilityNotice from '../CapabilityNotice/CapabilityNotice';
import { formatNumber } from '../../i18n/format';

// Import the new CSS file
import './LoanApplication.css';

const DEMO_PRESETS = {
  pass: {
    firstName: 'Tom',
    lastName: 'Miller',
    email: 'tom.miller@example.com',
    phone: '555-0100',
    dateOfBirth: '1980-01-21',
    ssn: '987-65-4321',
    passportNumber: 'AB1234567',
    address: '2570 24TH STREET, ANYTOWN, CA 95818',
    maritalStatus: 'married',
    employmentStatus: 'employed',
    employer: 'Acme Corporation',
    jobTitle: 'Operations Manager',
    monthlyIncome: 8500,
    employmentDuration: '5-10',
    loanType: 'Home Renovation',
    loanAmount: 50000,
    loanPurpose: 'Home renovation',
    downPayment: 10000,
    monthlyExpenses: 3200,
    creditScore: 'good',
    bankingRelationship: true,
    hasOtherLoans: false,
    agreeToTerms: true,
    agreeToCredit: true,
  },
  reject: {
    firstName: 'Jordan',
    lastName: 'Example',
    email: 'jordan.example@example.com',
    phone: '555-0199',
    dateOfBirth: '2015-01-21',
    ssn: '111-22-3333',
    passportNumber: 'MISMATCH-001',
    address: '999 DIFFERENT STREET, ANYTOWN, CA 95818',
    maritalStatus: 'single',
    employmentStatus: 'employed',
    employer: 'Example Company',
    jobTitle: 'Analyst',
    monthlyIncome: 4200,
    employmentDuration: '1-2',
    loanType: 'Personal',
    loanAmount: 25000,
    loanPurpose: 'POC rejection scenario',
    downPayment: 0,
    monthlyExpenses: 3900,
    creditScore: 'poor',
    bankingRelationship: false,
    hasOtherLoans: true,
    agreeToTerms: true,
    agreeToCredit: true,
  },
};

const DISPLAY_OPTION_KEYS = {
  marital: {
    single: 'single',
    married: 'married',
    divorced: 'divorced',
    widowed: 'widowed',
  },
  employment: {
    employed: 'employed',
    'self-employed': 'selfEmployed',
    unemployed: 'unemployed',
    retired: 'retired',
    student: 'student',
  },
  loanType: {
    Personal: 'personal',
    Auto: 'auto',
    Home: 'home',
    Business: 'business',
    'Home Renovation': 'homeRenovation',
  },
  credit: {
    excellent: 'excellent',
    good: 'good',
    fair: 'fair',
    poor: 'poor',
    unknown: 'unknown',
  },
};

const LoanApplication = () => {
  const { i18n, t } = useTranslation('application');
  const demoRequestIdRef = useRef(0);
  const [applicationMode, setApplicationMode] = useState(null); // 'form' or 'pdf'
  const [currentStep, setCurrentStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [submittedAppId, setSubmittedAppId] = useState(null);
  const [demoScenario, setDemoScenario] = useState(null);
  const [loadingDemoScenario, setLoadingDemoScenario] = useState(null);
  const [demoPresetError, setDemoPresetError] = useState(null);
  const [uploadedFiles, setUploadedFiles] = useState({
    applicationPdf: null,
    idProof: null,
    incomeProof: null,
    addressProof: null,
    additionalDocs: []
  });
  
  const [formData, setFormData] = useState({
    // Personal Information
    firstName: '',
    lastName: '',
    email: '',
    phone: '',
    dateOfBirth: '',
    ssn: '',
    maritalStatus: '',
    
    // Employment Information
    employmentStatus: '',
    employer: '',
    jobTitle: '',
    monthlyIncome: 0,
    employmentDuration: '',
    
    // Loan Information
    loanType: '',
    loanAmount: 0,
    loanPurpose: '',
    downPayment: 0,
    
    // Financial Information
    monthlyExpenses: 0,
    creditScore: '',
    bankingRelationship: false,
    hasOtherLoans: false,
    
    // Terms Agreement
    agreeToTerms: false,
    agreeToCredit: false
  });

  const [errors, setErrors] = useState({});

  const displayOption = (group, value) => {
    const key = DISPLAY_OPTION_KEYS[group]?.[value];
    return key ? t(`options.${group}.${key}`) : value;
  };

  const formSteps = [
    t('steps.personal'),
    t('steps.employment'),
    t('steps.loan'),
    t('steps.financial'),
    t('steps.documents'),
    t('steps.review')
  ];

  const pdfSteps = [
    t('steps.pdfUpload'),
    t('steps.supportingDocuments'),
    t('steps.review')
  ];

  const steps = applicationMode === 'form' ? formSteps : pdfSteps;

  useEffect(() => {
    const prefillRequestId = demoRequestIdRef.current;
    const fetchUserData = async () => {
      try {
        const response = await authFetch(buildApiUrl('/users/me'));
        if (!response.ok) {
          throw new Error("Could not fetch user data.");
        }
        const userData = await response.json();
        if (demoRequestIdRef.current !== prefillRequestId) {
          return;
        }
        
        // Pre-fill the form data with the fetched user details
        setFormData(prevData => ({
          ...prevData,
          // Map backend snake_case names to frontend camelCase names
          firstName: userData.first_name || '',
          lastName: userData.last_name || '',
          dateOfBirth: userData.date_of_birth ? new Date(userData.date_of_birth) : '',
        }));

      } catch (error) {
        console.error("Error pre-filling user data:", error);
      }
    };

    fetchUserData();
  }, []);

  const handleFileUpload = (fileType, files) => {
    if (files.length > 0) {
      if (fileType === 'additionalDocs') {
        const newFiles = Array.from(files);
        setUploadedFiles(prev => ({
          ...prev,
          additionalDocs: [...prev.additionalDocs, ...newFiles]
        }));
      } else {
        const file = files[0];
        setUploadedFiles(prev => ({
          ...prev,
          [fileType]: file
        }));
      }
    }
  };

  const handleLoadDemoPreset = async (scenario) => {
    const requestId = ++demoRequestIdRef.current;
    const selectedMode = applicationMode;
    setLoadingDemoScenario(scenario);
    setDemoPresetError(null);
    const fileKeys = selectedMode === 'pdf'
      ? ['applicationPdf', 'idProof', 'incomeProof', 'addressProof', 'ssn']
      : ['idProof', 'incomeProof', 'addressProof', 'ssn'];

    try {
      const response = await authFetch(buildApiUrl(`/demo_fixtures/${scenario}/manifest`));
      if (!response.ok) {
        throw new Error(t('errors.fixtureLoad', { document: t('preset.title') }));
      }
      const manifest = await response.json();
      const fixtureEntries = fileKeys.map((fileKey) => {
        const fixture = manifest.files?.[fileKey];
        if (!fixture?.filename || !fixture?.content_type) {
          throw new Error(t('errors.fixtureLoad', { document: t(`documents.names.${fileKey}`) }));
        }
        return [fileKey, new File([], fixture.filename, { type: fixture.content_type })];
      });
      const fixtures = Object.fromEntries(fixtureEntries);
      if (demoRequestIdRef.current !== requestId) {
        return;
      }

      setFormData(prev => ({ ...prev, ...DEMO_PRESETS[scenario] }));
      setUploadedFiles({
        applicationPdf: fixtures.applicationPdf || null,
        idProof: fixtures.idProof,
        incomeProof: fixtures.incomeProof,
        addressProof: fixtures.addressProof,
        additionalDocs: [fixtures.ssn],
      });
      setDemoScenario(scenario);
      setErrors({});
      setCurrentStep(selectedMode === 'form' ? formSteps.length - 1 : pdfSteps.length - 1);
    } catch (error) {
      if (demoRequestIdRef.current === requestId) {
        setDemoPresetError(error.message);
      }
    } finally {
      if (demoRequestIdRef.current === requestId) {
        setLoadingDemoScenario(null);
      }
    }
  };

  const removeFile = (fileType, index = null) => {
    if (fileType === 'additionalDocs' && index !== null) {
      setUploadedFiles(prev => ({
        ...prev,
        additionalDocs: prev.additionalDocs.filter((_, i) => i !== index)
      }));
    } else {
      setUploadedFiles(prev => ({
        ...prev,
        [fileType]: null
      }));
    }
  };

  const validateStep = (step) => {
    const newErrors = {};
    
    if (applicationMode === 'form') {
      switch(step) {
        case 0: // Personal Information
          if (!formData.firstName) newErrors.firstName = 'validation.firstName';
          if (!formData.lastName) newErrors.lastName = 'validation.lastName';
          if (!formData.email) newErrors.email = 'validation.email';
          if (!formData.phone) newErrors.phone = 'validation.phone';
          if (!formData.dateOfBirth) newErrors.dateOfBirth = 'validation.dateOfBirth';
          if (!formData.ssn) newErrors.ssn = 'validation.ssn';
          if (!formData.maritalStatus) newErrors.maritalStatus = 'validation.maritalStatus';
          break;
          
        case 1: // Employment
          if (!formData.employmentStatus) newErrors.employmentStatus = 'validation.employmentStatus';
          if (!formData.employer) newErrors.employer = 'validation.employer';
          if (!formData.jobTitle) newErrors.jobTitle = 'validation.jobTitle';
          if (!formData.monthlyIncome || formData.monthlyIncome <= 0) newErrors.monthlyIncome = 'validation.monthlyIncome';
          break;
          
        case 2: // Loan Information
          if (!formData.loanType) newErrors.loanType = 'validation.loanType';
          if (!formData.loanAmount || formData.loanAmount <= 0) newErrors.loanAmount = 'validation.loanAmount';
          if (!formData.loanPurpose) newErrors.loanPurpose = 'validation.loanPurpose';
          break;
          
        case 3: // Financial Details
          if (formData.monthlyExpenses < 0) newErrors.monthlyExpenses = 'validation.monthlyExpenses';
          if (!formData.creditScore) newErrors.creditScore = 'validation.creditScore';
          break;
          
        case 4: // Document Upload
          if (!uploadedFiles.idProof) newErrors.idProof = 'validation.idProof';
          if (!uploadedFiles.incomeProof) newErrors.incomeProof = 'validation.incomeProof';
          if (!uploadedFiles.addressProof) newErrors.addressProof = 'validation.addressProof';
          break;
          
        case 5: // Review & Submit
          if (!formData.agreeToTerms) newErrors.agreeToTerms = 'validation.agreeToTerms';
          if (!formData.agreeToCredit) newErrors.agreeToCredit = 'validation.agreeToCredit';
          break;
      }
    } else {
      switch(step) {
        case 0: // Upload Application
          if (!uploadedFiles.applicationPdf) newErrors.applicationPdf = 'validation.applicationPdf';
          break;
          
        case 1: // Supporting Documents
          if (!uploadedFiles.idProof) newErrors.idProof = 'validation.idProof';
          if (!uploadedFiles.incomeProof) newErrors.incomeProof = 'validation.incomeProof';
          if (!uploadedFiles.addressProof) newErrors.addressProof = 'validation.addressProof';
          break;
          
        case 2: // Review & Submit
          if (!formData.agreeToTerms) newErrors.agreeToTerms = 'validation.agreeToTerms';
          if (!formData.agreeToCredit) newErrors.agreeToCredit = 'validation.agreeToCredit';
          break;
      }
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleInputChange = (field, value) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
    
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  const handleNext = () => {
    if (validateStep(currentStep)) {
      setCurrentStep(prev => prev + 1);
    }
  };

  const handlePrevious = () => {
    setCurrentStep(prev => prev - 1);
  };

  const handleSubmit = async () => {
    // 1. Validate the current step's inputs first
    if (!validateStep(currentStep)) return;

    setIsSubmitting(true);

    const data = new FormData();
    let endpoint = '';
    try {
        if (demoScenario) {
            data.append('demoScenario', demoScenario);
            if (applicationMode === 'form') {
                endpoint = buildApiUrl('/submit_demo_form');
                data.append('formDataJson', JSON.stringify(formData));
            } else {
                endpoint = buildApiUrl('/submit_demo_pdf');
            }
        // 2. Build the FormData object based on the application mode
        } else if (applicationMode === 'form') {
            endpoint = buildApiUrl('/submit_form');
            
            // Append the form field data as a single JSON string
            data.append('formDataJson', JSON.stringify(formData));

            // --- THIS IS THE COMPLETED FILE APPENDING LOGIC FOR 'FORM' MODE ---
            // Check if each file exists before appending to avoid errors
            if (uploadedFiles.idProof) {
                data.append('idProof', uploadedFiles.idProof);
            }
            if (uploadedFiles.incomeProof) {
                data.append('incomeProof', uploadedFiles.incomeProof);
            }
            if (uploadedFiles.addressProof) {
                data.append('addressProof', uploadedFiles.addressProof);
            }
            // Loop through the additionalDocs array and append each file
            // The backend (FastAPI with List[UploadFile]) will correctly handle multiple files with the same key.
            uploadedFiles.additionalDocs.forEach((file) => {
                data.append('additionalDocs', file);
            });
            // -------------------------------------------------------------

        } else if (applicationMode === 'pdf') {
            endpoint = buildApiUrl('/submit_pdf_form');

            // --- THIS IS THE COMPLETED FILE APPENDING LOGIC FOR 'PDF' MODE ---
            if (uploadedFiles.applicationPdf) {
                data.append('applicationPdf', uploadedFiles.applicationPdf);
            }
            if (uploadedFiles.idProof) {
                data.append('idProof', uploadedFiles.idProof);
            }
            if (uploadedFiles.incomeProof) {
                data.append('incomeProof', uploadedFiles.incomeProof);
            }
            if (uploadedFiles.addressProof) {
                data.append('addressProof', uploadedFiles.addressProof);
            }
            uploadedFiles.additionalDocs.forEach((file) => {
                data.append('additionalDocs', file);
            });
            // -----------------------------------------------------------
        }

        // 3. Make the API call using the centralized authFetch service
        const response = await authFetch(endpoint, {
            method: 'POST',
            body: data,
            // Reminder: Do not manually set the 'Content-Type' header for FormData.
            // The browser sets it automatically with the correct boundary.
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || t('errors.submissionFallback'));
        }

        const result = await response.json();
        setSubmittedAppId(result.application_id);
        setShowSuccessModal(true);

    } catch (error) {
        // 5. Handle errors
        console.error('Submission failed:', error);
        alert(t('errors.submission', { message: error.message }));
    } finally {
        // 6. Always stop the loading indicator
        setIsSubmitting(false);
    }
  };

  const renderModeSelection = () => (
    <div className="form-step-container centered-content">
      <div className="text-center">
        <Heading>{t('method.heading')}</Heading>
        <CapabilityNotice capabilityIds={['submit_application', 'process_documents', 'generate_decision']} />
        <p className="page-subtitle">{t('method.subtitle')}</p>
      </div>
      
      <div className="mode-selection-grid">
        <Tile className="mode-selection-tile" onClick={() => setApplicationMode('form')}>
          <Document size={48} className="tile-icon icon-blue" />
          <Heading className="tile-heading">{t('method.form.title')}</Heading>
          <p>{t('method.form.description')}</p>
        </Tile>
        
        <Tile className="mode-selection-tile" onClick={() => setApplicationMode('pdf')}>
          <DocumentPdf size={48} className="tile-icon icon-red" />
          <Heading className="tile-heading">{t('method.pdf.title')}</Heading>
          <p>{t('method.pdf.description')}</p>
        </Tile>
      </div>
    </div>
  );

  const renderDocumentUpload = () => (
    <div className="form-step-container">
      <Heading>{t('documents.heading')}</Heading>
      <p className="page-subtitle">{t('documents.subtitle')}</p>
      
      <div className="document-upload-grid">
        <FormGroup legendText={t('documents.idProof.legend')}>
          <FileUploader
            accept={['.pdf', '.jpg', '.jpeg', '.png']}
            buttonLabel={t('documents.chooseFile')} filenameStatus="edit" iconDescription={t('documents.clearFile')}
            labelDescription={t('documents.idProof.upload')}
            onChange={(e) => handleFileUpload('idProof', e.target.files)}
            onDelete={() => removeFile('idProof')} size="md"
          />
          {uploadedFiles.idProof && (
            <InlineNotification kind="success" title={t('documents.fileUploaded')} subtitle={uploadedFiles.idProof.name} hideCloseButton />
          )}
          {errors.idProof && <InlineNotification kind="error" title={t(errors.idProof)} hideCloseButton />}
        </FormGroup>
        
        <FormGroup legendText={t('documents.incomeProof.legend')}>
          <FileUploader
            accept={['.pdf', '.jpg', '.jpeg', '.png']}
            buttonLabel={t('documents.chooseFile')} filenameStatus="edit" iconDescription={t('documents.clearFile')}
            labelDescription={t('documents.incomeProof.upload')}
            onChange={(e) => handleFileUpload('incomeProof', e.target.files)}
            onDelete={() => removeFile('incomeProof')} size="md"
          />
          {uploadedFiles.incomeProof && (
            <InlineNotification kind="success" title={t('documents.fileUploaded')} subtitle={uploadedFiles.incomeProof.name} hideCloseButton />
          )}
          {errors.incomeProof && <InlineNotification kind="error" title={t(errors.incomeProof)} hideCloseButton />}
        </FormGroup>
        
        <FormGroup legendText={t('documents.addressProof.legend')}>
          <FileUploader
            accept={['.pdf', '.jpg', '.jpeg', '.png']}
            buttonLabel={t('documents.chooseFile')} filenameStatus="edit" iconDescription={t('documents.clearFile')}
            labelDescription={t('documents.addressProof.upload')}
            onChange={(e) => handleFileUpload('addressProof', e.target.files)}
            onDelete={() => removeFile('addressProof')} size="md"
          />
          {uploadedFiles.addressProof && (
            <InlineNotification kind="success" title={t('documents.fileUploaded')} subtitle={uploadedFiles.addressProof.name} hideCloseButton />
          )}
          {errors.addressProof && <InlineNotification kind="error" title={t(errors.addressProof)} hideCloseButton />}
        </FormGroup>
        
        <FormGroup legendText={t('documents.additional.legend')}>
          <FileUploader
            accept={['.pdf', '.jpg', '.jpeg', '.png']}
            buttonLabel={t('documents.chooseFile')} filenameStatus="edit" iconDescription={t('documents.clearFile')}
            labelDescription={t('documents.additional.upload')}
            onChange={(e) => handleFileUpload('additionalDocs', e.target.files)} size="md" multiple
          />
          {uploadedFiles.additionalDocs.map((file, index) => (
            <InlineNotification key={index} kind="success" title={t('documents.fileUploaded')} subtitle={file.name} onClose={() => removeFile('additionalDocs', index)} />
          ))}
        </FormGroup>
      </div>
    </div>
  );

  const renderPdfUpload = () => (
    <div className="form-step-container">
      <Heading>{t('pdf.heading')}</Heading>
      <p className="page-subtitle">{t('pdf.subtitle')}</p>
      
      <FormGroup legendText={t('pdf.legend')}>
        <FileUploader
          accept={['.pdf']} buttonLabel={t('pdf.chooseFile')} filenameStatus="edit" iconDescription={t('documents.clearFile')}
          labelDescription={t('pdf.upload')}
          onChange={(e) => handleFileUpload('applicationPdf', e.target.files)}
          onDelete={() => removeFile('applicationPdf')} size="lg"
        />
        {uploadedFiles.applicationPdf && (
          <InlineNotification kind="success" title={t('pdf.uploaded')} subtitle={uploadedFiles.applicationPdf.name} hideCloseButton />
        )}
        {errors.applicationPdf && <InlineNotification kind="error" title={t(errors.applicationPdf)} hideCloseButton />}
      </FormGroup>
    </div>
  );

  const renderPersonalInformation = () => (
    <div className="form-step-container">
      <Heading>{t('sections.personal')}</Heading>
      
      <TextInput
        id="firstName" labelText={t('fields.firstName')} value={formData.firstName}
        onChange={(e) => handleInputChange('firstName', e.target.value)}
        invalid={!!errors.firstName} invalidText={errors.firstName ? t(errors.firstName) : ''}
      />
      
      <TextInput
        id="lastName" labelText={t('fields.lastName')} value={formData.lastName}
        onChange={(e) => handleInputChange('lastName', e.target.value)}
        invalid={!!errors.lastName} invalidText={errors.lastName ? t(errors.lastName) : ''}
      />
      
      <TextInput
        id="email" labelText={t('fields.email')} type="email" value={formData.email}
        onChange={(e) => handleInputChange('email', e.target.value)}
        invalid={!!errors.email} invalidText={errors.email ? t(errors.email) : ''}
      />
      
      <TextInput
        id="phone" labelText={t('fields.phone')} type="tel" value={formData.phone}
        onChange={(e) => handleInputChange('phone', e.target.value)}
        invalid={!!errors.phone} invalidText={errors.phone ? t(errors.phone) : ''}
      />
      
      <DatePicker datePickerType="single" onChange={(dates) => handleInputChange('dateOfBirth', dates[0])} value={formData.dateOfBirth ? [formData.dateOfBirth] : []}>
        <DatePickerInput
          id="dateOfBirth" labelText={t('fields.dateOfBirth')} placeholder={t('fields.datePlaceholder')}
          invalid={!!errors.dateOfBirth} invalidText={errors.dateOfBirth ? t(errors.dateOfBirth) : ''}
        />
      </DatePicker>
      
      <TextInput
        id="ssn" labelText={t('fields.ssn')} type="password" value={formData.ssn}
        onChange={(e) => handleInputChange('ssn', e.target.value)}
        invalid={!!errors.ssn} invalidText={errors.ssn ? t(errors.ssn) : ''}
      />
      
      <Select
        id="maritalStatus" labelText={t('fields.maritalStatus')} value={formData.maritalStatus}
        onChange={(e) => handleInputChange('maritalStatus', e.target.value)}
        invalid={!!errors.maritalStatus} invalidText={errors.maritalStatus ? t(errors.maritalStatus) : ''}
      >
        <SelectItem value="" text={t('options.marital.placeholder')} />
        <SelectItem value="single" text={t('options.marital.single')} />
        <SelectItem value="married" text={t('options.marital.married')} />
        <SelectItem value="divorced" text={t('options.marital.divorced')} />
        <SelectItem value="widowed" text={t('options.marital.widowed')} />
      </Select>
    </div>
  );

  const renderEmploymentDetails = () => (
    <div className="form-step-container">
        <Heading>{t('sections.employment')}</Heading>
        <Select id="employmentStatus" labelText={t('fields.employmentStatus')} value={formData.employmentStatus}
          onChange={(e) => handleInputChange('employmentStatus', e.target.value)}
          invalid={!!errors.employmentStatus} invalidText={errors.employmentStatus ? t(errors.employmentStatus) : ''}>
          <SelectItem value="" text={t('options.employment.placeholder')} />
          <SelectItem value="employed" text={t('options.employment.employed')} />
          <SelectItem value="self-employed" text={t('options.employment.selfEmployed')} />
          <SelectItem value="unemployed" text={t('options.employment.unemployed')} />
          <SelectItem value="retired" text={t('options.employment.retired')} />
          <SelectItem value="student" text={t('options.employment.student')} />
        </Select>
        <TextInput id="employer" labelText={t('fields.employer')} value={formData.employer}
          onChange={(e) => handleInputChange('employer', e.target.value)}
          invalid={!!errors.employer} invalidText={errors.employer ? t(errors.employer) : ''}/>
        <TextInput id="jobTitle" labelText={t('fields.jobTitle')} value={formData.jobTitle}
          onChange={(e) => handleInputChange('jobTitle', e.target.value)}
          invalid={!!errors.jobTitle} invalidText={errors.jobTitle ? t(errors.jobTitle) : ''}/>
        <NumberInput id="monthlyIncome" label={t('fields.monthlyIncome')} value={formData.monthlyIncome}
          onChange={(e, { value }) => handleInputChange('monthlyIncome', value)}
          min={0} step={100} invalid={!!errors.monthlyIncome} invalidText={errors.monthlyIncome ? t(errors.monthlyIncome) : ''}/>
        <Select id="employmentDuration" labelText={t('fields.employmentDuration')} value={formData.employmentDuration}
          onChange={(e) => handleInputChange('employmentDuration', e.target.value)}>
          <SelectItem value="" text={t('options.duration.placeholder')} />
          <SelectItem value="less-than-1" text={t('options.duration.lessThanOne')} />
          <SelectItem value="1-2" text={t('options.duration.oneToTwo')} />
          <SelectItem value="2-5" text={t('options.duration.twoToFive')} />
          <SelectItem value="5-10" text={t('options.duration.fiveToTen')} />
          <SelectItem value="more-than-10" text={t('options.duration.moreThanTen')} />
        </Select>
    </div>
  );

  const renderLoanInformation = () => (
    <div className="form-step-container">
        <Heading>{t('sections.loan')}</Heading>
        <Select id="loanType" labelText={t('fields.loanType')} value={formData.loanType}
          onChange={(e) => handleInputChange('loanType', e.target.value)}
          invalid={!!errors.loanType} invalidText={errors.loanType ? t(errors.loanType) : ''}>
          <SelectItem value="" text={t('options.loanType.placeholder')} />
          <SelectItem value="Personal" text={t('options.loanType.personal')} />
          <SelectItem value="Auto" text={t('options.loanType.auto')} />
          <SelectItem value="Home" text={t('options.loanType.home')} />
          <SelectItem value="Business" text={t('options.loanType.business')} />
        </Select>
        <NumberInput id="loanAmount" label={t('fields.loanAmount')} value={formData.loanAmount}
          onChange={(e, { value }) => handleInputChange('loanAmount', value)}
          min={1000} step={1000} invalid={!!errors.loanAmount} invalidText={errors.loanAmount ? t(errors.loanAmount) : ''}/>
        <TextInput id="loanPurpose" labelText={t('fields.loanPurpose')} value={formData.loanPurpose}
          onChange={(e) => handleInputChange('loanPurpose', e.target.value)}
          invalid={!!errors.loanPurpose} invalidText={errors.loanPurpose ? t(errors.loanPurpose) : ''}
          helperText={t('fields.loanPurposeHelp')}/>
        <NumberInput id="downPayment" label={t('fields.downPayment')} value={formData.downPayment}
          onChange={(e, { value }) => handleInputChange('downPayment', value)} min={0} step={500}/>
    </div>
  );

  const renderFinancialDetails = () => (
    <div className="form-step-container">
        <Heading>{t('sections.financial')}</Heading>
        <NumberInput id="monthlyExpenses" label={t('fields.monthlyExpenses')} value={formData.monthlyExpenses}
          onChange={(e, { value }) => handleInputChange('monthlyExpenses', value)}
          min={0} step={100} invalid={!!errors.monthlyExpenses} invalidText={errors.monthlyExpenses ? t(errors.monthlyExpenses) : ''}
          helperText={t('fields.monthlyExpensesHelp')}/>
        <RadioButtonGroup legendText={t('fields.creditScore')} name="creditScore"
          valueSelected={formData.creditScore} onChange={(value) => handleInputChange('creditScore', value)}>
          <RadioButton labelText={t('options.credit.excellent')} value="excellent" />
          <RadioButton labelText={t('options.credit.good')} value="good" />
          <RadioButton labelText={t('options.credit.fair')} value="fair" />
          <RadioButton labelText={t('options.credit.poor')} value="poor" />
          <RadioButton labelText={t('options.credit.unknown')} value="unknown" />
        </RadioButtonGroup>
        <FormGroup legendText={t('fields.additionalInformation')}>
          <Checkbox id="bankingRelationship" labelText={t('fields.bankingRelationship')}
            checked={formData.bankingRelationship}
            onChange={(e, { checked }) => handleInputChange('bankingRelationship', checked)}/>
          <Checkbox id="hasOtherLoans" labelText={t('fields.hasOtherLoans')}
            checked={formData.hasOtherLoans}
            onChange={(e, { checked }) => handleInputChange('hasOtherLoans', checked)}/>
        </FormGroup>
    </div>
  );

  const renderReviewSubmit = () => (
    <div className="form-step-container review-container">
        <Heading>{t('review.heading')}</Heading>
        <div className="review-sections-wrapper">
          {applicationMode === 'form' && (
            <>
              <Section level={4} className="review-section">
                <Heading>{t('sections.personal')}</Heading>
                <p><strong>{t('review.name')}:</strong> {formData.firstName} {formData.lastName}</p>
                <p><strong>{t('review.email')}:</strong> {formData.email}</p>
                <p><strong>{t('review.phone')}:</strong> {formData.phone}</p>
                <p><strong>{t('review.maritalStatus')}:</strong> {displayOption('marital', formData.maritalStatus)}</p>
              </Section>
              
              <Section level={4} className="review-section">
                <Heading>{t('review.employment')}</Heading>
                <p><strong>{t('review.status')}:</strong> {displayOption('employment', formData.employmentStatus)}</p>
                <p><strong>{t('review.employer')}:</strong> {formData.employer}</p>
                <p><strong>{t('review.jobTitle')}:</strong> {formData.jobTitle}</p>
                <p><strong>{t('review.monthlyIncome')}:</strong> {t('review.usdAmount', { value: formatNumber(formData.monthlyIncome, i18n.language) })}</p>
              </Section>
              
              <Section level={4} className="review-section">
                <Heading>{t('review.loanDetails')}</Heading>
                <p><strong>{t('review.type')}:</strong> {displayOption('loanType', formData.loanType)}</p>
                <p><strong>{t('review.amount')}:</strong> {t('review.usdAmount', { value: formatNumber(formData.loanAmount, i18n.language) })}</p>
                <p><strong>{t('review.purpose')}:</strong> {formData.loanPurpose}</p>
                {formData.downPayment > 0 && <p><strong>{t('review.downPayment')}:</strong> {t('review.usdAmount', { value: formatNumber(formData.downPayment, i18n.language) })}</p>}
              </Section>
              
              <Section level={4} className="review-section">
                <Heading>{t('review.financialInformation')}</Heading>
                <p><strong>{t('review.monthlyExpenses')}:</strong> {t('review.usdAmount', { value: formatNumber(formData.monthlyExpenses, i18n.language) })}</p>
                <p><strong>{t('review.creditScore')}:</strong> {displayOption('credit', formData.creditScore)}</p>
              </Section>
            </>
          )}
          
          <Section level={4} className="review-section">
            <Heading>{t('review.uploadedDocuments')}</Heading>
            {applicationMode === 'pdf' && uploadedFiles.applicationPdf && (
              <p><strong>{t('review.applicationPdf')}:</strong> {uploadedFiles.applicationPdf.name}</p>
            )}
            {uploadedFiles.idProof && <p><strong>{t('review.idProof')}:</strong> {uploadedFiles.idProof.name}</p>}
            {uploadedFiles.incomeProof && <p><strong>{t('review.incomeProof')}:</strong> {uploadedFiles.incomeProof.name}</p>}
            {uploadedFiles.addressProof && <p><strong>{t('review.addressProof')}:</strong> {uploadedFiles.addressProof.name}</p>}
            {uploadedFiles.additionalDocs.length > 0 && (
              <div>
                <strong>{t('review.additionalDocuments')}:</strong>
                <ul className="review-doc-list">
                  {uploadedFiles.additionalDocs.map((file, index) => (
                    <li key={index}>{file.name}</li>
                  ))}
                </ul>
              </div>
            )}
          </Section>
        </div>
        
        <FormGroup legendText={t('agreements.heading')}>
          <Checkbox id="agreeToTerms" labelText={t('agreements.terms')}
            checked={formData.agreeToTerms}
            onChange={(e, { checked }) => handleInputChange('agreeToTerms', checked)}
            invalid={!!errors.agreeToTerms} invalidText={errors.agreeToTerms ? t(errors.agreeToTerms) : ''}/>
          <Checkbox id="agreeToCredit" labelText={t('agreements.credit')}
            checked={formData.agreeToCredit}
            onChange={(e, { checked }) => handleInputChange('agreeToCredit', checked)}
            invalid={!!errors.agreeToCredit} invalidText={errors.agreeToCredit ? t(errors.agreeToCredit) : ''}/>
        </FormGroup>
    </div>
  );

  const renderStepContent = () => {
    if (!applicationMode) {
      return renderModeSelection();
    }

    if (applicationMode === 'form') {
      switch(currentStep) {
        case 0: return renderPersonalInformation();
        case 1: return renderEmploymentDetails();
        case 2: return renderLoanInformation();
        case 3: return renderFinancialDetails();
        case 4: return renderDocumentUpload();
        case 5: return renderReviewSubmit();
        default: return null;
      }
    } else {
      switch(currentStep) {
        case 0: return renderPdfUpload();
        case 1: return renderDocumentUpload();
        case 2: return renderReviewSubmit();
        default: return null;
      }
    }
  };

  const resetApplication = () => {
    demoRequestIdRef.current += 1;
    setApplicationMode(null);
    setCurrentStep(0);
    setErrors({});
    setDemoScenario(null);
    setLoadingDemoScenario(null);
    setDemoPresetError(null);
    setUploadedFiles({ applicationPdf: null, idProof: null, incomeProof: null, addressProof: null, additionalDocs: [] });
  };

  return (
    <>
      <main className="main-content-container">
        {!applicationMode ? (
          renderStepContent()
        ) : (
          <>
            <div className="page-header">
              <div>
                <Heading>{t('header.heading')}</Heading>
                <CapabilityNotice capabilityIds={['submit_application', 'process_documents', 'generate_decision']} />
                <p className="page-subtitle">
                  {applicationMode === 'form' 
                    ? t('header.formSubtitle')
                    : t('header.pdfSubtitle')
                  }
                </p>
                <Button kind="ghost" size="sm" onClick={resetApplication}>
                  {t('header.changeMethod')}
                </Button>
              </div>
            </div>

            <section className="demo-preset-panel" aria-labelledby="demo-preset-title">
              <div className="demo-preset-copy">
                <p className="demo-preset-eyebrow">{t('preset.eyebrow')}</p>
                <Heading id="demo-preset-title">{t('preset.heading')}</Heading>
                <p>{t('preset.description')}</p>
              </div>
              <div className="demo-preset-actions">
                <Button
                  kind="tertiary"
                  size="sm"
                  disabled={Boolean(loadingDemoScenario)}
                  onClick={() => handleLoadDemoPreset('pass')}
                >
                  {loadingDemoScenario === 'pass' ? t('preset.loadingPass') : t('preset.loadPass')}
                </Button>
                <Button
                  kind="danger--tertiary"
                  size="sm"
                  disabled={Boolean(loadingDemoScenario)}
                  onClick={() => handleLoadDemoPreset('reject')}
                >
                  {loadingDemoScenario === 'reject' ? t('preset.loadingReject') : t('preset.loadReject')}
                </Button>
              </div>
              {demoScenario && (
                <InlineNotification
                  kind={demoScenario === 'pass' ? 'success' : 'warning'}
                  title={demoScenario === 'pass' ? t('preset.passLoaded') : t('preset.rejectLoaded')}
                  subtitle={t('preset.loadedSubtitle')}
                  hideCloseButton
                />
              )}
              {demoPresetError && (
                <InlineNotification
                  kind="error"
                  title={t('preset.loadError')}
                  subtitle={demoPresetError}
                  hideCloseButton
                />
              )}
            </section>
            
            <ProgressIndicator currentIndex={currentStep}>
              {steps.map((step, index) => (
                <ProgressStep key={index} label={step} complete={index < currentStep}/>
              ))}
            </ProgressIndicator>
            
            <div className="form-content-wrapper">
              {renderStepContent()}
              
              <div className="button-container">
                <Button kind="secondary" onClick={handlePrevious} disabled={currentStep === 0}>
                  {t('actions.previous')}
                </Button>
                
                {currentStep < steps.length - 1 ? (
                  <Button onClick={handleNext}>{t('actions.next')}</Button>
                ) : (
                  <Button onClick={handleSubmit} disabled={isSubmitting}>
                    {isSubmitting ? <Loading small withOverlay={false} /> : t('actions.submit')}
                  </Button>
                )}
              </div>
            </div>
          </>
        )}
      </main>
      
      <Modal
        open={showSuccessModal} onRequestClose={() => setShowSuccessModal(false)}
        modalHeading={t('success.heading')} primaryButtonText={t('actions.close')}
        onRequestSubmit={() => { setShowSuccessModal(false); resetApplication(); setSubmittedAppId(null); }}>
        <div className="modal-content">
          <p>{t('success.description')}</p>
          {submittedAppId && (
            <p>
                {t('success.reference')} <strong>{submittedAppId}</strong>
            </p>
          )}
        </div>
      </Modal>
    </>
  );
};

export default LoanApplication;
