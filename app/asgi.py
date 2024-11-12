"""Application implementation - ASGI."""

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import config
from app.models.exception import HttpException
from app.router import root_api_router
from app.utils import utils


def exception_handler(request: Request, e: HttpException):
    """Handle exceptions by returning a JSON response.

    This function takes an HTTP request and an exception as input, and it
    constructs a JSON response with the appropriate status code and content
    based on the exception details. It utilizes a utility function to format
    the response content, ensuring that the client receives a structured
    error message.

    Args:
        request (Request): The HTTP request object that triggered the exception.
        e (HttpException): The exception object containing details about the error.

    Returns:
        JSONResponse: A JSON response with the status code and error message.
    """

    return JSONResponse(
        status_code=e.status_code,
        content=utils.get_response(e.status_code, e.data, e.message),
    )


def validation_exception_handler(request: Request, e: RequestValidationError):
    """Handle request validation exceptions.

    This function is designed to handle exceptions that occur during request
    validation. When a validation error is encountered, it constructs a JSON
    response with a 400 status code, indicating that the request was
    invalid. The response includes details about the validation errors that
    occurred, allowing the client to understand what fields are required or
    what issues were found in the request.

    Args:
        request (Request): The incoming request object that triggered
            the validation error.
        e (RequestValidationError): The exception raised during
            request validation, containing details about the errors.

    Returns:
        JSONResponse: A JSON response with a status code of 400 and
            a message indicating that fields are required, along with
            the specific validation errors.
    """

    return JSONResponse(
        status_code=400,
        content=utils.get_response(
            status=400, data=e.errors(), message="field required"
        ),
    )


def get_application() -> FastAPI:
    """Initialize a FastAPI application.

    This function creates and configures an instance of a FastAPI
    application. It sets the title, description, and version of the
    application based on the provided configuration. Additionally, it
    includes a router for handling API requests and adds exception handlers
    for specific exceptions.

    Returns:
        FastAPI: An instance of the FastAPI application.
    """
    instance = FastAPI(
        title=config.project_name,
        description=config.project_description,
        version=config.project_version,
        debug=False,
    )
    instance.include_router(root_api_router)
    instance.add_exception_handler(HttpException, exception_handler)
    instance.add_exception_handler(RequestValidationError, validation_exception_handler)
    return instance


app = get_application()

# Configures the CORS middleware for the FastAPI app
cors_allowed_origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "")
origins = cors_allowed_origins_str.split(",") if cors_allowed_origins_str else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

task_dir = utils.task_dir()
app.mount(
    "/tasks", StaticFiles(directory=task_dir, html=True, follow_symlink=True), name=""
)

public_dir = utils.public_dir()
app.mount("/", StaticFiles(directory=public_dir, html=True), name="")


@app.on_event("shutdown")
def shutdown_event():
    logger.info("shutdown event")


@app.on_event("startup")
def startup_event():
    logger.info("startup event")
