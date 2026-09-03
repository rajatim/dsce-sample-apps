from dotenv import load_dotenv
load_dotenv()

import os
import hashlib
import hmac
import json
import zipfile
import yaml
import shutil
import uvicorn
import uuid
from functools import lru_cache
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, File, Form, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from utils.cos_client import COSClient
from utils.agents import invoke_agents, get_logs
from utils.chat_image import ChatWithImage
from utils.kv_extraction import extract_key_value_pairs

# These are your local modules
import models, schemas, security, database

app = FastAPI(title="Loan Application API")


@lru_cache(maxsize=1)
def get_image_client():
    return ChatWithImage(
        model_id="meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
        max_tokens=2000,
        top_p=0.1,
        temperature=0,
    )


@lru_cache(maxsize=1)
def get_cos_client():
    return COSClient()

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COS_BUCKET_NAME = os.getenv("COS_BUCKET_NAME", "loan-processing-bucket")
# --- File Handling ---
UPLOAD_DIRECTORY = "./uploads"
ZIP_FILE_PATH = "data/sample_documents.zip"
DEMO_FIXTURE_FILES = {
    "applicationPdf": ("Loan Application Form.pdf", "Loan-Application-Form.pdf", "application/pdf"),
    "idProof": ("ID Doc.png", "ID-Doc.png", "image/png"),
    "incomeProof": ("Income Doc.png", "Income-Doc.png", "image/png"),
    "addressProof": ("Address Doc.png", "Address-Doc.png", "image/png"),
    "ssn": ("SSN.png", "SSN.png", "image/png"),
}
PASS_DEMO_APPLICATION_DATA = {
    "full_name": "Tom Miller",
    "firstName": "Tom",
    "lastName": "Miller",
    "date_of_birth": "1980-01-21",
    "dateOfBirth": "1980-01-21",
    "ssn": "987-65-4321",
    "id_passport_number": "AB1234567",
    "passportNumber": "AB1234567",
    "residential_address": "2570 24TH STREET, ANYTOWN, CA 95818",
    "address": "2570 24TH STREET, ANYTOWN, CA 95818",
    "employer": "Acme Corporation",
    "position": "Operations Manager",
    "monthly_income": 8500,
    "loan_type": "Home Renovation",
    "loan_amount": 50000,
    "loan_purpose": "Home renovation",
}
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)
def save_upload_file(upload_file: UploadFile, destination: str):
    """Safely saves an uploaded file to a destination path."""
    try:
        with open(destination, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        get_cos_client().upload_local_file_to_cos(
            local_filepath=destination,
            bucket_name=COS_BUCKET_NAME,
            output_filepath=destination,
        )
    finally:
        upload_file.file.close()


def _fixture_sha256(file_key: str) -> Optional[str]:
    fixture = DEMO_FIXTURE_FILES.get(file_key)
    if not fixture or not os.path.exists(ZIP_FILE_PATH):
        return None
    archive_name = fixture[0]
    with zipfile.ZipFile(ZIP_FILE_PATH) as fixture_archive:
        return hashlib.sha256(fixture_archive.read(archive_name)).hexdigest()


def resolve_upload_name(
    file_key: str,
    original_filename: str,
    demo_scenario: Optional[str],
    content_sha256: str,
) -> str:
    normalized_name = (original_filename or "upload").replace("\\", "/")
    safe_name = os.path.basename(normalized_name).replace("\x00", "") or "upload"
    expected_digest = _fixture_sha256(file_key)
    if (
        demo_scenario in {"pass", "reject"}
        and expected_digest
        and hmac.compare_digest(content_sha256, expected_digest)
    ):
        return f"demo-{demo_scenario}-{DEMO_FIXTURE_FILES[file_key][1]}"
    if safe_name in {".", ".."}:
        safe_name = "upload"
    return f"{file_key}-{uuid.uuid4().hex[:12]}-{safe_name}"


def save_application_upload(
    upload_file: UploadFile,
    app_upload_dir: str,
    file_key: str,
    demo_scenario: Optional[str],
) -> str:
    digest = hashlib.sha256()
    upload_file.file.seek(0)
    while chunk := upload_file.file.read(1024 * 1024):
        digest.update(chunk)
    upload_file.file.seek(0)
    safe_name = resolve_upload_name(
        file_key,
        upload_file.filename,
        demo_scenario,
        digest.hexdigest(),
    )
    destination = os.path.join(app_upload_dir, safe_name)
    save_upload_file(upload_file, destination)
    return destination


def stream_fixture_member(archive_name: str):
    """Yield one bundled fixture in bounded chunks while the ZIP stays open."""
    with zipfile.ZipFile(ZIP_FILE_PATH) as fixture_archive:
        with fixture_archive.open(archive_name) as fixture_file:
            while chunk := fixture_file.read(64 * 1024):
                yield chunk


def _normalize_upload_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("uploads/"):
        return f"./{normalized}"
    return normalized


def _is_application_form(path: str) -> bool:
    filename = os.path.basename(path).lower()
    return (
        filename.startswith("applicationpdf-")
        or filename in {"loan application form.pdf", "loan-application-form.pdf"}
        or filename.endswith("-loan-application-form.pdf")
    )


def recover_application_inputs(app_id_str: str):
    """Recover the exact COS paths needed to rerun a failed application."""
    upload_folder = _normalize_upload_path(
        os.path.join(UPLOAD_DIRECTORY, app_id_str)
    )
    source_paths = set()

    if os.path.isdir(upload_folder):
        source_paths.update(
            _normalize_upload_path(os.path.join(upload_folder, filename))
            for filename in os.listdir(upload_folder)
            if os.path.isfile(os.path.join(upload_folder, filename))
        )

    source_paths.update(
        _normalize_upload_path(path)
        for path in get_cos_client().get_contents_of_folder_in_bucket(
            COS_BUCKET_NAME,
            f"{upload_folder}/",
        )
    )

    application_data_path = f"{upload_folder}/application_data.json"
    if application_data_path not in source_paths:
        raise FileNotFoundError("Application data is no longer available.")

    document_paths = sorted(
        path
        for path in source_paths
        if path != application_data_path and not _is_application_form(path)
    )
    if not document_paths:
        raise FileNotFoundError("Source documents are no longer available.")

    return document_paths, application_data_path

def dict_to_markdown(data, indent=0):
    md = ''
    indent_str = '    ' * indent  # 4 spaces per indent level
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                md += f"{indent_str}- **{key}**:\n"
                md += dict_to_markdown(value, indent + 1)
            else:
                md += f"{indent_str}- **{key}**: {value}\n"
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                md += dict_to_markdown(item, indent)
            else:
                md += f"{indent_str}- {item}\n"
    return md

def process_application_in_background(app_id, uploaded_files, application_file_path, db):
    db = database.SessionLocal()
    try:
        application_to_update = db.query(models.Application).filter(models.Application.id == app_id).first()
        if not application_to_update:
            print(f"BACKGROUND TASK ERROR: Application with ID {app_id} not found.")
            return

        app_id_str = application_to_update.app_id_str
        application_to_update.status = "Processing"
        db.commit()

        def mark_retrying(next_attempt, error):
            application_to_update.status = "Retrying"
            application_to_update.validation_comments = dict_to_markdown({
                "status": f"Temporary agent interruption; retrying attempt {next_attempt} of 3."
            })
            db.commit()

        print("Processing application...")
        application_status = invoke_agents(
            document_names=uploaded_files,
            loan_application_file=application_file_path,
            application_id=app_id_str,
            on_retry=mark_retrying,
        )
        print("Application Status from Agents:\n", application_status)
        application_to_update.status = application_status.get("loan_application_status", "Processing Failed")
        validation_comments = application_status.get("validation_details", {"error": "Error processing application"})
        application_to_update.validation_comments = dict_to_markdown(validation_comments)
        db.commit()
    except Exception as error:
        print(f"BACKGROUND TASK ERROR: Application {app_id} processing failed: {error}")
        if 'application_to_update' in locals() and application_to_update:
            application_to_update.status = "Processing Failed"
            application_to_update.validation_comments = dict_to_markdown({
                "error": "Application processing failed. Please retry."
            })
            db.commit()
    finally:
        db.close()

# --- Authentication Endpoints ---

@app.post("/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    db_user = security.get_user(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = security.get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        hashed_password=hashed_password,
        first_name=user.firstName,
        last_name=user.lastName,
        date_of_birth=user.dateOfBirth
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = security.get_user(db, username=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=schemas.UserDetail)
async def read_users_me(current_user: models.User = Depends(security.get_current_user)):
    return current_user

@app.get("/list_applications", response_model=List[schemas.Application])
async def get_user_applications(
    current_user: schemas.User = Depends(security.get_current_user),
    db: Session = Depends(database.get_db)
):
    # This now only returns applications for the logged-in user
    apps = db.query(models.Application).filter(models.Application.owner_id == current_user.id).all()
    apps = [schemas.Application.model_validate(app) for app in apps]
    return apps


@app.get("/applications/{app_id_str}", response_model=schemas.Application)
async def get_application(
    app_id_str: str,
    current_user: schemas.User = Depends(security.get_current_user),
    db: Session = Depends(database.get_db),
):
    application = db.query(models.Application).filter(
        models.Application.app_id_str == app_id_str,
        models.Application.owner_id == current_user.id,
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found or access denied.")
    return application


@app.post("/applications/{app_id_str}/retry", response_model=schemas.Application)
async def retry_application(
    app_id_str: str,
    background_tasks: BackgroundTasks,
    current_user: schemas.User = Depends(security.get_current_user),
    db: Session = Depends(database.get_db),
):
    application = db.query(models.Application).filter(
        models.Application.app_id_str == app_id_str,
        models.Application.owner_id == current_user.id,
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found or access denied.")
    if application.status.strip().lower() != "processing failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only applications with Processing Failed status can be retried.",
        )

    try:
        uploaded_files, application_file_path = recover_application_inputs(app_id_str)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    application.status = "Pending"
    application.validation_comments = dict_to_markdown({
        "status": "Retry requested. Waiting for agent processing."
    })
    db.commit()

    background_tasks.add_task(
        process_application_in_background,
        application.id,
        uploaded_files,
        application_file_path,
        db,
    )
    return application

@app.post("/submit_form")
async def submit_application_form(
    background_tasks: BackgroundTasks,
    formDataJson: str = Form(...),
    idProof: UploadFile = File(...),
    incomeProof: UploadFile = File(...),
    addressProof: UploadFile = File(...),
    additionalDocs: Optional[List[UploadFile]] = None,
    demoScenario: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
    current_user: schemas.User = Depends(security.get_current_user),
):
    form_data = json.loads(formDataJson)
    app_id_str = f"app_{int(datetime.now().timestamp())}"
    
    # Associate with current user
    new_application = models.Application(
        app_id_str=app_id_str,
        applicant_name=f"{form_data.get('firstName', '')} {form_data.get('lastName', '')}",
        loan_type=form_data.get("loanType", "N/A"),
        amount=float(form_data.get("loanAmount", 0)),
        status="Pending",
        validation_comments="",
        submitted_date=datetime.now().strftime("%Y-%m-%d"),
        owner_id=current_user.id
    )
    db.add(new_application)
    db.commit()

    # --- File Saving Logic ---
    app_upload_dir = os.path.join(UPLOAD_DIRECTORY, app_id_str)
    application_file_path = os.path.join(app_upload_dir, "application_data.json")
    get_cos_client().upload_json_to_cos(
        json_content=form_data,
        bucket_name=COS_BUCKET_NAME,
        output_filepath=application_file_path,
    )

    os.makedirs(app_upload_dir, exist_ok=True)
    uploaded_files = []
    try:
        uploaded_files.extend([
            save_application_upload(idProof, app_upload_dir, "idProof", demoScenario),
            save_application_upload(incomeProof, app_upload_dir, "incomeProof", demoScenario),
            save_application_upload(addressProof, app_upload_dir, "addressProof", demoScenario),
        ])
        if additionalDocs:
            for doc in additionalDocs:
                file_key = "ssn" if doc.filename.rsplit("/", 1)[-1].endswith("SSN.png") else "additional"
                uploaded_files.append(
                    save_application_upload(doc, app_upload_dir, file_key, demoScenario)
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving files: {e}")

    background_tasks.add_task(
        process_application_in_background,
        new_application.id,
        uploaded_files,
        application_file_path,
        db
    )
        
    return {"status": "success", "message": "Application submitted.", "application_id": app_id_str}

@app.post("/submit_pdf_form")
async def submit_pdf_form(
    background_tasks: BackgroundTasks,
    applicationPdf: UploadFile = File(...),
    idProof: UploadFile = File(...),
    incomeProof: UploadFile = File(...),
    addressProof: UploadFile = File(...),
    additionalDocs: List[UploadFile] = File([]),
    demoScenario: Optional[str] = Form(None),
    db: Session = Depends(database.get_db),
    current_user: schemas.User = Depends(security.get_current_user)
):
    app_id_str = f"pdf_{int(datetime.now().timestamp())}"

    # --- File Saving Logic ---
    app_upload_dir = os.path.join(UPLOAD_DIRECTORY, app_id_str)
    os.makedirs(app_upload_dir, exist_ok=True)
    uploaded_files = []
    try:
        application_pdf_path = save_application_upload(
            applicationPdf,
            app_upload_dir,
            "applicationPdf",
            demoScenario,
        )
        uploaded_files.extend([
            save_application_upload(idProof, app_upload_dir, "idProof", demoScenario),
            save_application_upload(incomeProof, app_upload_dir, "incomeProof", demoScenario),
            save_application_upload(addressProof, app_upload_dir, "addressProof", demoScenario),
        ])
        for doc in additionalDocs:
            file_key = "ssn" if doc.filename.rsplit("/", 1)[-1].endswith("SSN.png") else "additional"
            uploaded_files.append(
                save_application_upload(doc, app_upload_dir, file_key, demoScenario)
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving files: {e}")
    
    if demoScenario == "pass" and os.path.basename(application_pdf_path).startswith("demo-pass-"):
        form_data = dict(PASS_DEMO_APPLICATION_DATA)
    else:
        form_data = extract_key_value_pairs(
            get_image_client(),
            filename=application_pdf_path,
        )
    applicant_name = form_data.get("full_name", current_user.username)
    loan_type = form_data.get("loan_type", "PDF Application")
    loan_amount = form_data.get("loan_amount", 0)

    application_file_path = os.path.join(app_upload_dir, "application_data.json")
    get_cos_client().upload_json_to_cos(
        json_content=form_data,
        bucket_name=COS_BUCKET_NAME,
        output_filepath=application_file_path,
    )

    new_application = models.Application(
        app_id_str=app_id_str,
        applicant_name=applicant_name,
        loan_type=loan_type,
        amount=loan_amount,
        status="Pending ",
        submitted_date=datetime.now().strftime("%Y-%m-%d"),
        owner_id=current_user.id
    )
    db.add(new_application)
    db.commit()


    background_tasks.add_task(
        process_application_in_background,
        new_application.id,
        uploaded_files,
        application_file_path,
        db
    )

    return {"status": "success", "message": "PDF application submitted successfully.", "application_id": app_id_str}

@app.get("/get_logs/{app_id_str}")
async def get_application_logs(
    app_id_str: str,
    current_user: models.User = Depends(security.get_current_user),
    db: Session = Depends(database.get_db)
):
    # Find the application and ensure it belongs to the current user
    application = db.query(models.Application).filter(
        models.Application.app_id_str == app_id_str,
        models.Application.owner_id == current_user.id
    ).first()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found or access denied.")
    logs = get_logs(app_id_str)
    return {"logs": logs}

@app.get("/download_sample_documents")
async def download_file():
    if not os.path.exists(ZIP_FILE_PATH):
        return {"error": "File not found"}
    return FileResponse(
        path=ZIP_FILE_PATH,
        media_type="application/zip",
        filename="sample_documents.zip"
    )


@app.get("/demo_fixtures/{scenario}/{file_key}")
async def get_demo_fixture(scenario: str, file_key: str):
    if scenario not in {"pass", "reject"} or file_key not in DEMO_FIXTURE_FILES:
        raise HTTPException(status_code=404, detail="Demo fixture not found")
    if not os.path.exists(ZIP_FILE_PATH):
        raise HTTPException(status_code=404, detail="Sample documents not found")

    archive_name, download_name, media_type = DEMO_FIXTURE_FILES[file_key]
    scenario_filename = f"demo-{scenario}-{download_name}"
    return StreamingResponse(
        stream_fixture_member(archive_name),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{scenario_filename}"'},
    )
    
# Standard entry point to run the app
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
