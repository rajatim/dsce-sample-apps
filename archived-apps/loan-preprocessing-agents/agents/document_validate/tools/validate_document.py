from datetime import datetime
import ibm_boto3
import base64
import hashlib
import mimetypes
from ibm_botocore.client import Config
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from langchain_ibm import ChatWatsonx
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.agent_builder.connections import ConnectionType, ExpectedCredentials

def read_image_from_cos_with_sha256(cos, bucket_name: str, image_filepath: str):
    """
    Reads an image file from COS and returns its content as a Base64-encoded data URI.

    Args:
        bucket_name (str): The name of the bucket.
        image_filepath (str): The path to the image file in the bucket.

    Returns:
        str: The Base64-encoded data URI of the image (e.g., "data:image/png;base64,...").
    """
    response = cos.get_object(Bucket=bucket_name, Key=image_filepath)
    image_bytes = response['Body'].read()
    base64_encoded = base64.b64encode(image_bytes).decode("utf-8")
    mime_type, _ = mimetypes.guess_type(image_filepath)
    if mime_type is None:
        mime_type = "image/png"
    return (
        f"data:{mime_type};base64,{base64_encoded}",
        hashlib.sha256(image_bytes).hexdigest(),
    )


def read_image_from_cos_as_base64(cos, bucket_name: str, image_filepath: str) -> str:
    image_base64, _ = read_image_from_cos_with_sha256(
        cos,
        bucket_name,
        image_filepath,
    )
    return image_base64

def get_message(
    image_base64,
    prompt_text: str,
    system_message: str = ""
) :
    """
    Build a message list with the given image and prompt text.
    If a system message is provided, it is prepended to the message list.

    :param image_base64: Base64 encoded image strings.
    :param prompt_text: The text prompt.
    :param system_message: An optional system message.
    :return: A list of messages (SystemMessage and HumanMessage).
    """
    content = [{"type": "text", "text": prompt_text}]
    content.append({
        "type": "image_url",
        "image_url": {"url": image_base64}
    })
    message = HumanMessage(content=content)
    if system_message:
        sys_message = SystemMessage(content=system_message)
        return [sys_message, message]
    return [message]

WATSONX_CONFIG = {
    "model_id": "meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
    "params": {
        "max_tokens": 350,
        "temperature": 0.0,
        "top_p": 0.1,
    }
}

DOC_VALIDATION_SYSTEM_PROMPT = """
You verify documents for a loan-processing POC. Inspect the supplied image and
decide whether it is acceptable. Check visible signs of tampering or sample/mock
content, expiry, cropping or missing information, and document-specific layout or
number formats. If evidence is insufficient, mark it invalid and request manual
review. Today's date is {today}.

Return only this compact JSON object. Keep each reason to one short sentence:
{{
  "document_type": "Passport, Driving License, SSN, Utility Bill, Salary Slip, Bank Statement, or Other",
  "valid": true,
  "risk_level": "Low, Medium, or High",
  "authenticity": "Passed or Failed: short reason",
  "expiry": "Valid, Expired, or Not applicable: short reason",
  "completeness": "Complete or Incomplete: short reason",
  "failure_codes": ["zero or more of: synthetic_sample_marking, historical_fixture_date, visible_tampering, cropped_or_missing_content, inconsistent_data, unreadable_content, suspected_forgery, or other"],
  "reason": "one-sentence final justification"
}}
"""

AUTHORIZED_POC_FIXTURE_GUIDANCE = """
This filename identifies an authorized POC fixture. Ignore SAMPLE/DEMO markings
and historical dates that exist only because the fixture is synthetic. Treat the
document as valid when it is readable, complete for its document type, internally
consistent, and shows no other visible tampering. This exception applies only to
filenames beginning with demo-pass-.
"""

AUTHORIZED_POC_FIXTURE_SHA256 = {
    "ID-Doc.png": "a739dda06b35ce0dbf1068f3867b7942595d5687dcccc90f2a726036f4453ae7",
    "Income-Doc.png": "5ac95e27c87835003c0c6e1495418f825b6786613859ee853fec8598776de4c8",
    "Address-Doc.png": "0168cf7445d57223aa35a628af1f266fba89b3bdd7454d35ce3d74a649cfddac",
    "SSN.png": "65f7cf41a8b710dab6234b5a00ca6788f51c6a7fa493f4cf80e5e55fd1d8da5d",
}
AUTHORIZED_POC_FAILURE_CODES = {
    "synthetic_sample_marking",
    "historical_fixture_date",
}


def _is_authorized_poc_fixture(file_name: str, content_sha256: str) -> bool:
    filename = file_name.rsplit("/", 1)[-1]
    if not filename.startswith("demo-pass-"):
        return False
    fixture_name = filename.removeprefix("demo-pass-")
    return content_sha256 == AUTHORIZED_POC_FIXTURE_SHA256.get(fixture_name)


def build_validation_system_prompt(
    file_name: str,
    content_sha256: str = "",
) -> str:
    today = datetime.today().strftime("%d-%b-%Y")
    prompt = DOC_VALIDATION_SYSTEM_PROMPT.format(today=today)
    if _is_authorized_poc_fixture(file_name, content_sha256):
        prompt += AUTHORIZED_POC_FIXTURE_GUIDANCE
    return prompt


def apply_authorized_poc_policy(
    file_name: str,
    validation_result: dict,
    content_sha256: str = "",
) -> dict:
    """Allow only known synthetic-fixture limitations in the Pass POC path."""
    normalized_result = dict(validation_result)
    failure_codes = validation_result.get("failure_codes")
    if not isinstance(failure_codes, list):
        return normalized_result

    is_authorized_fixture = _is_authorized_poc_fixture(
        file_name,
        content_sha256,
    )
    failure_code_set = set(failure_codes)
    if failure_code_set and not (
        is_authorized_fixture
        and failure_code_set.issubset(AUTHORIZED_POC_FAILURE_CODES)
    ):
        normalized_result["valid"] = False
        return normalized_result
    if not failure_code_set or not is_authorized_fixture:
        return normalized_result

    authorized_result = normalized_result
    authorized_result.update({
        "valid": True,
        "risk_level": "Low",
        "authenticity": "Passed: authorized POC fixture",
        "failure_codes": [],
        "reason": "Accepted as an authorized synthetic POC fixture.",
    })
    if "expiry" in authorized_result:
        authorized_result["expiry"] = "Valid for authorized POC fixture"
    return authorized_result

@tool(
    expected_credentials=[
        ExpectedCredentials(
            app_id = "wxai_credential",
            type = ConnectionType.KEY_VALUE
        ),
        ExpectedCredentials(
            app_id = "cos_credential",
            type = ConnectionType.KEY_VALUE
        )
    ]
)
def validate_document(file_name: str) -> dict:
    """
    Validate the scanned document as True or False stored in IBM Cloud Object Storage (COS)
        by analyzing its visual content using a Watsonx.ai vision-capable model.

    Parameters:
        file_name (str): The name (key) of the file stored in the COS bucket.

    Returns:
        str: valid document or not true or false along with the reason.
        
    Raises:
        Exception: If the Watsonx API call fails or a supported model is unavailable.
    """
    wxai_creds = connections.key_value("wxai_credential")
    cos_creds = connections.key_value("cos_credential")

    cos = ibm_boto3.client("s3",
        ibm_api_key_id=cos_creds["COS_API_KEY"],
        ibm_service_instance_id=cos_creds["COS_SERVICE_INSTANCE_ID"],
        config=Config(signature_version="oauth"),
        endpoint_url=cos_creds["COS_ENDPOINT"]
    )

    llm = ChatWatsonx(
        model_id=WATSONX_CONFIG["model_id"],
        apikey=wxai_creds["WATSONX_APIKEY"],
        url=wxai_creds["WATSONX_URL"],
        project_id=wxai_creds["WATSONX_PROJECT_ID"],
        params=WATSONX_CONFIG["params"],
    )

    bucket_name = cos_creds["COS_BUCKET_NAME"]

    image_base64, content_sha256 = read_image_from_cos_with_sha256(
        cos,
        bucket_name,
        file_name,
    )
    system_prompt = build_validation_system_prompt(file_name, content_sha256)
    messages = get_message(image_base64, prompt_text="Validate the document", system_message=system_prompt)
    response = llm.invoke(messages)
    output_parser = JsonOutputParser()
    try:
        parsed_response = output_parser.parse(response.content)
        parsed_response["filename"] = file_name
        return apply_authorized_poc_policy(
            file_name,
            parsed_response,
            content_sha256,
        )
    except Exception as e:
        print(f"Error parsing response: {e}")
    return {"error": "Failed to parse response"}

# if __name__ == "__main__":
#     # Example usage
#     filename = "doc.gif" #"Angelina_DL.png" "doc.gif" "card.jpg"
#     result = validate_document(filename)
#     print(result)
